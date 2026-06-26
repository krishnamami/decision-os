"""PL-E — Platform Studio product-matrix CSV extractor (the EXTRACT stage).

Turns a lender's product matrix CSV into `products`-table-shaped rows
(product_id, product_name, loan_type, loan_purpose, min_credit_score, max_dti,
max_ltv, max_loan_amount, is_active). Stdlib `csv` only — NO openpyxl/pandas
(a lender exports their spreadsheet as CSV — same data). Pure + sync + DB-less.
RULE 11: every row carries `confidence` + `source_row` + `warnings`, and
`extract()` returns `data_source` + `missing_inputs`; unrecognized columns +
unparseable rows surface in `unmapped_items`, never silently dropped.

Produces a DRAFT PROPOSAL ONLY — it writes nothing. Review + activation use the
sibling `POST /api/accord/onboarding/products/upload` endpoint (upsert into the
`products` table). Three-stage posture: EXTRACT → REVIEW → ACTIVATE (PL-C/D/E).
Decision-path-safe: product_eligibility uses its inline _PRODUCTS matrix, not the
`products` table, so 16/16 holds by construction.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from typing import Optional

# Column-name synonyms — messy lender headers normalized to the target columns.
COLUMN_SYNONYMS = {
    "product_id": ["product_id", "id", "product code", "code"],
    "product_name": ["product_name", "product", "name", "product name", "description"],
    "loan_type": ["loan_type", "loan type", "type", "program type"],
    "loan_purpose": ["loan_purpose", "purpose", "loan purpose"],
    "min_credit_score": ["min_credit_score", "min score", "minimum score", "min fico",
                         "minimum fico", "credit score min", "fico min", "min credit"],
    "max_dti": ["max_dti", "max dti", "maximum dti", "dti max", "dti limit", "dti cap",
                "max debt", "debt ratio", "max debt ratio"],
    "max_ltv": ["max_ltv", "max ltv", "maximum ltv", "ltv max", "ltv limit",
                "max loan to value"],
    "max_loan_amount": ["max_loan_amount", "max loan", "maximum loan", "loan max",
                        "loan limit", "max loan amount", "loan amount max"],
    "is_active": ["is_active", "offered", "active", "available", "offer", "approved",
                  "status"],
}

LOAN_TYPE_MAP = {
    "conv": "conventional",
    "conventional": "conventional",
    "fha": "fha",
    "va": "va",
    "usda": "usda",
    "jumbo": "jumbo",
    "non_qm": "non_qm",
    "nonqm": "non_qm",
    "heloc": "heloc",
}

LOAN_PURPOSE_MAP = {
    "purchase": "purchase",
    "purch": "purchase",
    "cash": "cash_out_refi",
    "cashout": "cash_out_refi",
    "rate": "rate_term_refi",
    "refi": "rate_term_refi",
    "all": "all",
}

_TRUTHY = ("yes", "y", "true", "1", "offered", "active", "approved", "x")


@dataclass
class ProductRow:
    product_id: str
    product_name: str
    loan_type: str
    loan_purpose: str
    min_credit_score: Optional[int]
    max_dti: Optional[float]
    max_ltv: Optional[float]
    max_loan_amount: Optional[int]
    is_active: bool
    confidence: float
    source_row: int
    warnings: list


class ProductMatrixExtractor:
    """Parse a lender product-matrix CSV into `products`-shaped draft rows.

    Stdlib only. Pure + sync + DB-less. RULE 11. Draft proposal only.
    """

    def _normalize_header(self, header: str) -> Optional[str]:
        h = str(header).lower().strip()
        for field, synonyms in COLUMN_SYNONYMS.items():
            if h in synonyms:
                return field
        return None

    def _normalize_loan_type(self, val: str) -> str:
        v = str(val).lower().strip()
        for k, norm in LOAN_TYPE_MAP.items():
            if k in v:
                return norm
        return v or "conventional"

    def _normalize_loan_purpose(self, val: str) -> str:
        v = str(val).lower().strip()
        # cash-out keys before "refi" — "refi" is a substring of "cash out refi".
        for k, norm in LOAN_PURPOSE_MAP.items():
            if k in v:
                return norm
        return "all"

    def _parse_bool(self, val: str) -> bool:
        return str(val).lower().strip() in _TRUTHY

    def _parse_amount(self, val: str) -> Optional[int]:
        if not val:
            return None
        try:
            return int(float(str(val).replace("$", "").replace(",", "").strip()))
        except ValueError:
            return None

    def _parse_pct(self, val: str) -> Optional[float]:
        if not val:
            return None
        try:
            return float(str(val).replace("%", "").strip())
        except ValueError:
            return None

    def _derive_product_id(self, name: str, loan_type: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "_", str(name).lower().strip()).strip("_")[:20]
        return f"{slug}_{loan_type[:4]}" if slug else f"{loan_type}_product"

    def parse(self, csv_text: str, tenant_id: str = "") -> tuple:
        rows: list = []
        unmapped: list = []
        missing: list = []

        try:
            all_rows = [r for r in csv.reader(io.StringIO(csv_text))
                        if any((c or "").strip() for c in r)]
        except Exception as e:
            return [], [], [f"CSV parse error: {e}"]

        if not all_rows:
            return [], [], ["Empty CSV — no rows found"]

        # Find the header row (first of the first 5 rows with >= 2 known columns).
        header_row_idx = 0
        field_map: dict = {}
        for idx, row in enumerate(all_rows[:5]):
            candidate = {}
            for col_i, cell in enumerate(row):
                norm = self._normalize_header(cell)
                if norm and norm not in candidate:
                    candidate[norm] = col_i
            if len(candidate) >= 2:
                field_map = candidate
                header_row_idx = idx
                break

        if not field_map:
            return [], [], ["No recognized column headers found. Expected e.g. "
                            "product_name, min_credit_score, max_dti, max_ltv, offered"]

        if "product_name" not in field_map:
            missing.append("Required column not found: product_name")

        # Flag unrecognized columns (never silently ignored).
        for col_i, cell in enumerate(all_rows[header_row_idx]):
            if cell.strip() and self._normalize_header(cell) is None:
                unmapped.append({"column": col_i, "header": cell,
                                 "reason": "unrecognized column — not in COLUMN_SYNONYMS"})

        for row_idx, row in enumerate(all_rows[header_row_idx + 1:], header_row_idx + 2):
            def get(field):
                col = field_map.get(field)
                return row[col].strip() if col is not None and col < len(row) else ""

            name = get("product_name")
            if not name:
                unmapped.append({"row": row_idx, "reason": "empty product_name"})
                continue

            loan_type = self._normalize_loan_type(get("loan_type"))
            loan_purpose = self._normalize_loan_purpose(get("loan_purpose"))
            min_score = self._parse_amount(get("min_credit_score"))
            max_dti = self._parse_pct(get("max_dti"))
            max_ltv = self._parse_pct(get("max_ltv"))
            max_loan = self._parse_amount(get("max_loan_amount"))
            is_active = self._parse_bool(get("is_active")) if "is_active" in field_map else True
            product_id = get("product_id") or self._derive_product_id(name, loan_type)

            warnings = []
            if min_score is None:
                warnings.append("min_credit_score not found — activation will need it or an agency floor")
            if max_dti is None:
                warnings.append("max_dti not found")
            if max_ltv is None:
                warnings.append("max_ltv not found")
            confidence = 0.95 if not warnings else (0.80 if len(warnings) == 1 else 0.65)

            rows.append(ProductRow(
                product_id=product_id, product_name=name, loan_type=loan_type,
                loan_purpose=loan_purpose, min_credit_score=min_score, max_dti=max_dti,
                max_ltv=max_ltv, max_loan_amount=max_loan, is_active=is_active,
                confidence=confidence, source_row=row_idx, warnings=warnings))

        if not rows:
            missing.append("No valid product rows parsed from CSV")
        return rows, unmapped, missing

    def extract(self, file_bytes: bytes, filename: str = "", tenant_id: str = "") -> dict:
        text = file_bytes.decode("utf-8-sig", errors="replace")
        rows, unmapped, missing = self.parse(text, tenant_id)

        confs = [r.confidence for r in rows]
        avg_conf = round(sum(confs) / len(confs), 2) if confs else 0.0
        product_rows = [vars(r) for r in rows]

        return {
            "status": "draft",
            "product_rows": product_rows,
            "row_count": len(rows),
            "avg_confidence": avg_conf,
            "unmapped_items": unmapped,
            "next_steps": {
                "activate": ("POST /api/accord/onboarding/products/upload with the "
                             "reviewed product_rows serialized as CSV (upserts into "
                             "the tenant's products table)"),
            },
            "note": ("REVIEW REQUIRED — verify every extracted product before activation. "
                     "The products table is tenant-scoped. The decision path uses the "
                     "product_eligibility persona's inline _PRODUCTS (not this table yet). "
                     "This extractor produces a draft proposal only and writes nothing."),
            "data_source": f"product matrix CSV ({filename})",
            "missing_inputs": missing,
        }


__all__ = ["ProductMatrixExtractor", "ProductRow", "COLUMN_SYNONYMS",
           "LOAN_TYPE_MAP", "LOAN_PURPOSE_MAP"]
