"""Canonical document storage (RA-P0-A).

S3 object storage aligned to the MISMO mortgage-document folder hierarchy. Two
pieces:

  s3_keys   — pure key builders (no I/O): the single source of truth for where
              every document type lives under s3://{bucket}/{tenant}/{app}/...
  s3_client — a thin async boto3 wrapper that degrades gracefully when AWS is not
              configured (no credentials -> every op is a no-op returning
              False/None), so local dev and the extraction pipeline never depend
              on S3. Same pattern as pdfplumber standing in for Textract.
"""
from core.storage.s3_client import S3Client, s3
from core.storage.s3_keys import (
    aus_du_key,
    aus_lp_key,
    dmn_export_key,
    doc_processed_key,
    doc_raw_key,
    hmda_export_key,
    mismo_parsed_key,
    mismo_raw_key,
    platform_onboarding_key,
)

__all__ = [
    "S3Client", "s3",
    "doc_raw_key", "doc_processed_key", "mismo_raw_key", "mismo_parsed_key",
    "aus_du_key", "aus_lp_key", "platform_onboarding_key", "hmda_export_key",
    "dmn_export_key",
]
