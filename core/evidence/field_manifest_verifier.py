"""EV-H — FieldManifestVerifier (read-only, RULE 11).

Walks the FIELD_MANIFEST contract against one entity_states row and reports, per
field: present / missing / assumed, plus a per-decision completeness rollup and a
silent-default warning when an absent field WILL be assumed by a consumer.

Status semantics (honest, per-app):
  present  — the field has a real value in entity_states.
  assumed  — the field is NULL *and* a consumer silently defaults it (manifests now;
             e.g. SC03's NULL dti_back -> rate_pricing assumes 0.36).
  missing  — the field is NULL and no consumer defaults it (a true gap).

Separately, `fields_with_silent_default_risk` lists the fields that COULD be assumed
if absent (a static property), so the workbench sees the latent RULE 11 risk even
when the field is currently present.

Advisory only — no writes, no decision/persona changes (16/16 holds by construction).
"""
from __future__ import annotations

import json

from core.evidence.field_manifest import (
    FIELD_MANIFEST,
    FIELDS_WITH_SILENT_DEFAULTS,
    ManifestField,
)


def _j(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return {}
    return v if v is not None else {}


def _empty(v) -> bool:
    return v is None or v == "" or v == {} or v == []


class FieldManifestVerifier:
    """Read-only. Pure given an entity_states row (dict)."""

    def _read(self, mf: ManifestField, entity_row: dict):
        if mf.json_path:
            cur = _j(entity_row.get(mf.json_path[0]))
            for key in mf.json_path[1:]:
                cur = cur.get(key) if isinstance(cur, dict) else None
            return cur
        return entity_row.get(mf.entity_column)

    def verify_field(self, mf: ManifestField, entity_row: dict) -> dict:
        value = self._read(mf, entity_row)
        present = not _empty(value)
        if present:
            status = "present"
        elif mf.silent_default:
            status = "assumed"
        else:
            status = "missing"
        location = (".".join(mf.json_path) if mf.json_path
                    else f"entity_states.{mf.entity_column}")
        return {
            "field_name": mf.field_name,
            "status": status,
            "value": value if present else None,
            "required": mf.required,
            "consumers": list(mf.consumers),
            "required_for": list(mf.required_for),
            "silent_default": mf.silent_default,
            "source_doc_type": mf.source_doc_type,
            "extracted_key": mf.extracted_key,
            "note": mf.note,
            "broken_hop": None if present else (
                f"{mf.source_doc_type}.{mf.extracted_key} -> "
                f"golden_record.{mf.golden_record_key} -> {location}"),
            "data_source": location,
            "missing_inputs": [] if present else [
                f"{mf.field_name} is NULL in {location} "
                f"(source: {mf.source_doc_type}.{mf.extracted_key})"
                + (f" — {mf.silent_default}" if mf.silent_default else "")],
        }

    def verify_all(self, entity_row: dict) -> dict:
        entity_row = dict(entity_row or {})
        results = [self.verify_field(mf, entity_row) for mf in FIELD_MANIFEST]

        present = [r for r in results if r["status"] == "present"]
        missing = [r for r in results if r["status"] == "missing"]
        assumed = [r for r in results if r["status"] == "assumed"]

        # per-decision completeness
        decision_completeness: dict = {}
        all_decisions = sorted({d for mf in FIELD_MANIFEST for d in mf.required_for})
        by_name = {r["field_name"]: r for r in results}
        for decision in all_decisions:
            needed = [mf.field_name for mf in FIELD_MANIFEST if decision in mf.required_for]
            gaps = [by_name[n] for n in needed if by_name[n]["status"] in ("missing", "assumed")]
            decision_completeness[decision] = {
                "complete": len(gaps) == 0,
                "total_fields": len(needed),
                "gaps": len(gaps),
                "gap_fields": [g["field_name"] for g in gaps],
                "ran_on_assumed": any(g["status"] == "assumed" for g in gaps),
            }

        all_missing_inputs = [m for r in results for m in r.get("missing_inputs", [])]
        return {
            "total_fields": len(results),
            "present_count": len(present),
            "missing_count": len(missing),
            "assumed_count": len(assumed),
            "completeness_pct": round(len(present) / len(results) * 100, 1) if results else 0.0,
            "has_gaps": bool(missing or assumed),
            "present_fields": [r["field_name"] for r in present],
            "missing_fields": [r["field_name"] for r in missing],
            "assumed_fields": [r["field_name"] for r in assumed],
            # static latent risk — fields a consumer WOULD assume if they were absent
            "fields_with_silent_default_risk": [f.field_name for f in FIELDS_WITH_SILENT_DEFAULTS],
            "results": results,
            "decision_completeness": decision_completeness,
            "silent_default_warning": (
                f"{len(assumed)} field(s) are NULL and will be silently defaulted by a "
                f"consumer: {[r['field_name'] for r in assumed]}. The affected decision(s) "
                f"ran on ASSUMED, not actual, data (RULE 11 violation in the consumer)."
            ) if assumed else None,
            "data_source": "entity_states (manifest columns + JSONB paths)",
            "missing_inputs": all_missing_inputs,
        }


__all__ = ["FieldManifestVerifier"]
