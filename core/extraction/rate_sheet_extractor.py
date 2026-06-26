"""PL-D — Platform Studio rate-sheet CSV extractor (the EXTRACT stage).

Turns a lender's rate-sheet CSV into TWO structured proposals:
  - rate_sheet_entry_rows  → tenant base rates (feeds the EXISTING
                             POST /api/accord/rules/rate-sheet/upload endpoint)
  - llpa_rows              → the FICO×LTV grid + purpose/property/occupancy
                             adjustment blocks (feeds the EXISTING
                             scripts/refresh_llpa_grid.py stage→promote path)

Stdlib `csv` only — NO openpyxl/pandas/xlrd dependency (none are installed; a
lender exports their Excel as CSV — same data). Pure + sync + DB-less. RULE 11:
every row carries `confidence` + `source_row`, and `extract()` returns
`data_source` + `missing_inputs`; unparseable cells/rows surface in
`unmapped_items`, never silently dropped.

Produces a DRAFT PROPOSAL ONLY — it writes nothing. Review + activation reuse the
EXISTING plumbing (rate_sheet_upload for base rates, refresh_llpa_grid promote for
the LLPA grid). Same three-stage posture as PL-C: EXTRACT → REVIEW → ACTIVATE.
Decision-path-safe: rate_pricing computes its own inline rate and does not read
rate_sheet_entry/llpa_adjustments, so 16/16 holds by construction.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class LLPARow:
    agency: str
    adjustment_type: str
    credit_score_min: Optional[int]
    credit_score_max: Optional[int]
    ltv_min: Optional[float]
    ltv_max: Optional[float]
    property_type: str
    loan_purpose: str
    occupancy_type: str
    adjustment_pct: float
    description: str
    confidence: float
    source_row: str  # raw CSV provenance for audit


@dataclass
class RateSheetRow:
    product_id: str
    credit_band: str  # e.g. "720-739"
    ltv_max: float
    base_rate: float
    llpa_adjustment: float
    effective_date: str
    confidence: float
    source_row: str


class RateSheetExtractor:
    """Parse lender rate-sheet CSV into structured DRAFT proposals.

    Stdlib only (csv module). No openpyxl/pandas. No DB. No API key.
    RULE 11: confidence + source_row + missing_inputs on every row.
    """

    # Credit-score band normalization (reference bands; the grid parser reads
    # the bands FROM the CSV — these are only a documented canonical reference).
    FICO_BANDS = [
        (300, 619), (620, 639), (640, 659), (660, 679),
        (680, 699), (700, 719), (720, 739), (740, 759),
        (760, 779), (780, 850),
    ]

    # Order matters — most specific first. "refi" is a substring of
    # "cash_out_refi", so the cash-out keys MUST be tested before it (else a
    # cash-out label would be mislabeled rate/term).
    LOAN_PURPOSE_MAP = {
        "purchase": "purchase",
        "purch": "purchase",
        "cashout": "cash_out_refi",
        "cash": "cash_out_refi",
        "c/o": "cash_out_refi",
        "r/t": "rate_term_refi",
        "r&t": "rate_term_refi",
        "rate": "rate_term_refi",
        "refi": "rate_term_refi",
    }

    PROPERTY_TYPE_MAP = {
        "sfr": "single_family",
        "single": "single_family",
        "sf": "single_family",
        "1 unit": "single_family",
        "condo": "condo",
        "coop": "coop",
        "2-4": "multi_unit",
        "multi": "multi_unit",
        "2 unit": "multi_unit",
    }

    OCCUPANCY_MAP = {
        "primary": "primary",
        "owner": "primary",
        "o/o": "primary",
        "second": "second_home",
        "2nd": "second_home",
        "vacation": "second_home",
        "invest": "investment",
        "noo": "investment",
        "rental": "investment",
    }

    # ── primitives ──────────────────────────────────────────────────
    def _parse_pct(self, val: str) -> Optional[float]:
        """Parse "0.250", "0.250%", "-0.125" → float or None.

        Strips a trailing % and treats a comma as a decimal separator (some
        lenders export European decimals); LLPA adjustments are always small
        so this never collides with a thousands separator."""
        if val is None or str(val).strip() == "":
            return None
        try:
            return float(str(val).replace("%", "").replace(",", ".").strip())
        except ValueError:
            return None

    def _parse_score_band(self, band: str) -> tuple:
        """Parse "720-739", ">=780", "<620", "780+" → (min, max)."""
        band = str(band).strip().replace(" ", "")
        m = re.match(r"(\d{3})-(\d{3})", band)
        if m:
            return int(m.group(1)), int(m.group(2))
        m = re.match(r">=?(\d{3})", band)
        if m:
            return int(m.group(1)), 850
        m = re.match(r"<=?(\d{3})", band)
        if m:
            return 300, int(m.group(1))
        m = re.match(r"(\d{3})\+", band)
        if m:
            return int(m.group(1)), 850
        return None, None

    def _normalize_purpose(self, val: str) -> str:
        v = str(val).lower().strip()
        for k, norm in self.LOAN_PURPOSE_MAP.items():
            if k in v:
                return norm
        return v

    def _normalize_property(self, val: str) -> str:
        v = str(val).lower().strip()
        for k, norm in self.PROPERTY_TYPE_MAP.items():
            if k in v:
                return norm
        return "single_family"  # default

    def _normalize_occupancy(self, val: str) -> str:
        v = str(val).lower().strip()
        for k, norm in self.OCCUPANCY_MAP.items():
            if k in v:
                return norm
        return "primary"  # default

    @staticmethod
    def _non_blank_rows(csv_text: str) -> list:
        """csv rows with every fully-blank line dropped (a leading/trailing
        blank line must never be mistaken for the header / a data row)."""
        return [r for r in csv.reader(io.StringIO(csv_text))
                if any((c or "").strip() for c in r)]

    # ── LLPA grid + adjustment blocks ───────────────────────────────
    def parse_fico_ltv_grid(self, csv_text: str, agency: str = "fannie") -> tuple:
        """Parse a FICO×LTV adjustment matrix.

        Row 1   = header with LTV bands (≤60, ≤65, ≤70, ...).
        Col 1   = FICO band (620-639, 640-659, ...).
        Cells   = adjustment_pct values.

        Returns: (llpa_rows, unmapped, missing_inputs).
        """
        rows: list = []
        unmapped: list = []
        missing: list = []

        try:
            all_rows = self._non_blank_rows(csv_text)
        except Exception as e:  # malformed CSV
            return [], [], [f"CSV parse error: {e}"]

        if len(all_rows) < 2:
            return [], [], ["FICO×LTV grid: insufficient rows in CSV"]

        # First non-blank row = headers (LTV bands). Col 0 is the FICO label.
        header = all_rows[0]
        ltv_cols = []  # (col_index, ltv_min, ltv_max)
        for i, h in enumerate(header[1:], 1):
            h_clean = str(h).strip().replace("≤", "").replace("<=", "").replace("%", "")
            try:
                ltv_max = float(h_clean)
                ltv_min = ltv_cols[-1][2] if ltv_cols else 0.0  # prev max
                ltv_cols.append((i, ltv_min, ltv_max))
            except ValueError:
                if h_clean:
                    unmapped.append({"col": i, "header": h, "reason": "not an LTV value"})

        for row_idx, row in enumerate(all_rows[1:], 2):
            score_band = (row[0] or "").strip() if row else ""
            if not score_band:
                continue
            score_min, score_max = self._parse_score_band(score_band)
            if score_min is None:
                unmapped.append({"row": row_idx, "band": score_band,
                                 "reason": "unrecognized FICO band"})
                continue

            for col_idx, ltv_min, ltv_max in ltv_cols:
                raw_val = row[col_idx].strip() if col_idx < len(row) else ""
                adj = self._parse_pct(raw_val)
                if adj is None:
                    if raw_val:
                        unmapped.append({"row": row_idx, "col": col_idx,
                                         "raw": raw_val, "reason": "not numeric"})
                    continue
                rows.append(LLPARow(
                    agency=agency, adjustment_type="credit_score_ltv",
                    credit_score_min=score_min, credit_score_max=score_max,
                    ltv_min=ltv_min, ltv_max=ltv_max,
                    property_type="single_family", loan_purpose="purchase",
                    occupancy_type="primary", adjustment_pct=adj,
                    description=f"FICO {score_band} / LTV ≤{ltv_max}%",
                    confidence=0.90, source_row=f"row {row_idx}, col {col_idx}"))

        if not rows:
            missing.append("No valid FICO×LTV adjustment rows parsed")
        return rows, unmapped, missing

    def _parse_two_col(self, csv_text: str, normalize, key: str) -> tuple:
        """Shared parser for the purpose/property/occupancy adjustment blocks
        (two columns: label, adjustment_pct)."""
        rows: list = []
        unmapped: list = []
        try:
            for i, row in enumerate(csv.reader(io.StringIO(csv_text))):
                if len(row) < 2 or not (row[0] or "").strip():
                    continue
                adj = self._parse_pct(row[1])
                if adj is None:
                    unmapped.append({"row": i, "raw": row, "reason": "adj not numeric"})
                    continue
                rows.append({key: normalize(row[0]), "adjustment_pct": adj,
                             "confidence": 0.85, "source_row": str(row)})
        except Exception as e:
            return [], [str(e)]
        return rows, unmapped

    def parse_purpose_adjustments(self, csv_text: str) -> tuple:
        return self._parse_two_col(csv_text, self._normalize_purpose, "loan_purpose")

    def parse_property_adjustments(self, csv_text: str) -> tuple:
        return self._parse_two_col(csv_text, self._normalize_property, "property_type")

    def parse_occupancy_adjustments(self, csv_text: str) -> tuple:
        return self._parse_two_col(csv_text, self._normalize_occupancy, "occupancy_type")

    # ── tenant base-rate sheet ──────────────────────────────────────
    def parse_rate_sheet_entry(self, csv_text: str) -> tuple:
        """Parse the lender base-rate sheet into rate_sheet_entry rows.

        Required cols match the EXISTING rate_sheet_upload endpoint exactly:
          product_id, credit_band, ltv_max, base_rate, llpa_adjustment, effective_date
        """
        rows: list = []
        unmapped: list = []
        missing: list = []
        REQUIRED = {"product_id", "credit_band", "ltv_max",
                    "base_rate", "llpa_adjustment", "effective_date"}

        try:
            # lstrip so a leading blank line is never read as the header row.
            reader = csv.DictReader(io.StringIO(csv_text.lstrip()))
            headers = {(h or "").strip() for h in (reader.fieldnames or [])}
            missing_cols = REQUIRED - headers
            if missing_cols:
                missing.append(f"Missing required columns: {sorted(missing_cols)}")
                return [], unmapped, missing

            for i, row in enumerate(reader):
                try:
                    rows.append(RateSheetRow(
                        product_id=(row["product_id"] or "").strip(),
                        credit_band=(row["credit_band"] or "").strip(),
                        ltv_max=float(row["ltv_max"]),
                        base_rate=float(row["base_rate"]),
                        llpa_adjustment=float(row["llpa_adjustment"] or "0"),
                        effective_date=(row["effective_date"] or "").strip(),
                        confidence=0.95, source_row=f"row {i + 2}"))
                except (ValueError, TypeError, KeyError) as e:
                    unmapped.append({"row": i + 2, "error": str(e), "raw": dict(row)})
        except Exception as e:
            return [], [], [f"CSV parse error: {e}"]
        return rows, unmapped, missing

    # ── main entry point ────────────────────────────────────────────
    def extract(self, file_bytes: bytes, filename: str = "",
                sheet_hints: dict = None) -> dict:
        """Parse a rate-sheet upload into a DRAFT proposal (writes nothing).

        `sheet_hints` = {'rate_sheet','grid','purpose','property','occupancy'},
        each value the CSV text for that section. If absent, the whole file is
        treated as a rate_sheet_entry CSV. RULE 11 throughout.
        """
        text = file_bytes.decode("utf-8-sig", errors="replace")
        hints = sheet_hints or {}

        rs_rows, rs_unmapped, rs_missing = self.parse_rate_sheet_entry(
            hints.get("rate_sheet", text))

        llpa_rows: list = []
        llpa_unmapped: list = []
        llpa_missing: list = []

        if "grid" in hints:
            gr, gu, gm = self.parse_fico_ltv_grid(hints["grid"])
            llpa_rows.extend(gr)
            llpa_unmapped.extend(gu)
            llpa_missing.extend(gm)
        if "purpose" in hints:
            pr, pu = self.parse_purpose_adjustments(hints["purpose"])
            llpa_rows.extend(LLPARow(
                agency="fannie", adjustment_type="loan_purpose",
                credit_score_min=None, credit_score_max=None,
                ltv_min=None, ltv_max=None, property_type="single_family",
                loan_purpose=r["loan_purpose"], occupancy_type="primary",
                adjustment_pct=r["adjustment_pct"],
                description=f"Purpose: {r['loan_purpose']}",
                confidence=r["confidence"], source_row=r["source_row"]) for r in pr)
            llpa_unmapped.extend(pu)
        if "property" in hints:
            pr2, pu2 = self.parse_property_adjustments(hints["property"])
            llpa_rows.extend(LLPARow(
                agency="fannie", adjustment_type="property_type",
                credit_score_min=None, credit_score_max=None,
                ltv_min=None, ltv_max=None, property_type=r["property_type"],
                loan_purpose="all", occupancy_type="primary",
                adjustment_pct=r["adjustment_pct"],
                description=f"Property: {r['property_type']}",
                confidence=r["confidence"], source_row=r["source_row"]) for r in pr2)
            llpa_unmapped.extend(pu2)
        if "occupancy" in hints:
            or2, ou2 = self.parse_occupancy_adjustments(hints["occupancy"])
            llpa_rows.extend(LLPARow(
                agency="fannie", adjustment_type="occupancy",
                credit_score_min=None, credit_score_max=None,
                ltv_min=None, ltv_max=None, property_type="single_family",
                loan_purpose="purchase", occupancy_type=r["occupancy_type"],
                adjustment_pct=r["adjustment_pct"],
                description=f"Occupancy: {r['occupancy_type']}",
                confidence=r["confidence"], source_row=r["source_row"]) for r in or2)
            llpa_unmapped.extend(ou2)

        all_missing = rs_missing + llpa_missing
        all_unmapped = rs_unmapped + llpa_unmapped
        confs = [r.confidence for r in llpa_rows] + [r.confidence for r in rs_rows]
        avg_conf = round(sum(confs) / len(confs), 2) if confs else 0.0

        return {
            "status": "draft",
            "rate_sheet_entry_rows": [vars(r) for r in rs_rows],
            "llpa_rows": [vars(r) for r in llpa_rows],
            "rs_row_count": len(rs_rows),
            "llpa_row_count": len(llpa_rows),
            "avg_confidence": avg_conf,
            "unmapped_items": all_unmapped,
            "next_steps": {
                "base_rates": ("POST /api/accord/rules/rate-sheet/upload with "
                               "rate_sheet_entry_rows serialized as CSV"),
                "llpa_grid": ("scripts/refresh_llpa_grid.py --stage-from-file with "
                              "llpa_rows, then --promote after governance review"),
            },
            "note": ("REVIEW REQUIRED — verify every extracted row before activation. "
                     "Use the existing rate_sheet_upload endpoint for base rates and "
                     "the refresh_llpa_grid promote path for the LLPA grid. This "
                     "extractor produces a draft proposal only and writes nothing."),
            "data_source": f"rate sheet CSV ({filename})",
            "missing_inputs": all_missing,
        }


__all__ = ["RateSheetExtractor", "LLPARow", "RateSheetRow"]
