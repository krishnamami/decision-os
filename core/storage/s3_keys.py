"""Canonical S3 key builder (RA-P0-A) — MISMO-aligned document hierarchy.

The single source of truth for where every document type lives. Keys are tenant-
isolated (every key starts with {tenant_id}/) and discoverable (doc_type / system
in the path, never opaque UUIDs), so an operator can browse the bucket by hand.

  s3://{bucket}/
    {tenant_id}/
      {application_id}/
        uploads/
          raw/{doc_type}/{filename}     original files as uploaded
          processed/{doc_type}.json     extracted fields per doc
        mismo/
          raw/{version}.xml             MISMO XML as received from the LOS
          parsed/canonical.json         canonical fields extracted
        aus/
          du/{casefile_id}.json         DU response files
          lp/{key_number}.json          LP response files
      platform/onboarding/{filename}    Platform Studio uploads (tenant-level)
      exports/
        hmda/{year}/{month}/lar.csv     HMDA LAR exports (tenant-level)
        dmn/{version}/rules.xml         DMN rule export (MI-F future)

No I/O here — pure string building. Each path segment is stripped of stray
slashes so a key never contains a double slash or a leading slash.
"""
from __future__ import annotations


def _seg(value: object) -> str:
    """Normalize one path segment: stringify, strip surrounding whitespace and
    slashes. Guarantees the assembled key has no leading/double slashes even if a
    caller passes a value like '/W2_CURRENT/' or 'a/b'."""
    return str(value).strip().strip("/")


def _key(*segments: object) -> str:
    """Join non-empty, slash-stripped segments with single slashes."""
    return "/".join(s for s in (_seg(x) for x in segments) if s)


def doc_raw_key(tenant_id: str, app_id: str, doc_type: str, filename: str) -> str:
    return _key(tenant_id, app_id, "uploads/raw", doc_type, filename)


def doc_processed_key(tenant_id: str, app_id: str, doc_type: str) -> str:
    return _key(tenant_id, app_id, "uploads/processed", f"{_seg(doc_type)}.json")


def mismo_raw_key(tenant_id: str, app_id: str, version: str = "3x") -> str:
    return _key(tenant_id, app_id, "mismo/raw", f"{_seg(version)}.xml")


def mismo_parsed_key(tenant_id: str, app_id: str) -> str:
    return _key(tenant_id, app_id, "mismo/parsed", "canonical.json")


def aus_du_key(tenant_id: str, app_id: str, casefile_id: str) -> str:
    return _key(tenant_id, app_id, "aus/du", f"{_seg(casefile_id)}.json")


def aus_lp_key(tenant_id: str, app_id: str, key_number: str) -> str:
    return _key(tenant_id, app_id, "aus/lp", f"{_seg(key_number)}.json")


def platform_onboarding_key(tenant_id: str, filename: str) -> str:
    return _key(tenant_id, "platform/onboarding", filename)


def hmda_export_key(tenant_id: str, year: int, month: int) -> str:
    return _key(tenant_id, "exports/hmda", str(int(year)), f"{int(month):02d}", "lar.csv")


def dmn_export_key(tenant_id: str, version: str) -> str:
    return _key(tenant_id, "exports/dmn", version, "rules.xml")


__all__ = [
    "doc_raw_key", "doc_processed_key", "mismo_raw_key", "mismo_parsed_key",
    "aus_du_key", "aus_lp_key", "platform_onboarding_key", "hmda_export_key",
    "dmn_export_key",
]
