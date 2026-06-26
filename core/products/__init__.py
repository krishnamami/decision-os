"""core/products — program recommendation (EX2-B).

ProgramRecommender evaluates a borrower profile against a product matrix and returns
eligible programs + near-miss programs with actionable gap analysis. Sync, DB-less,
read-only — not wired into any persona (so 16/16 is unaffected by construction).
"""
from __future__ import annotations

from core.products.program_recommender import (
    NEAR_MISS_DTI_PCT,
    NEAR_MISS_LTV_PCT,
    NEAR_MISS_SCORE_PTS,
    PRODUCT_MATRIX,
    ProgramRecommender,
)

__all__ = [
    "ProgramRecommender",
    "PRODUCT_MATRIX",
    "NEAR_MISS_SCORE_PTS",
    "NEAR_MISS_DTI_PCT",
    "NEAR_MISS_LTV_PCT",
]
