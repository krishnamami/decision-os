"""core/model_risk — SR 11-7 model risk management.

MR-A: model card generator + validation framework (model_card.py).
MR-B: inventory + ongoing monitoring (inventory.py / drift.py).

The 14 decision personas are the "models". Card fields wave/upstream/risk_tier/mode
are DERIVED from the authoritative runtime config (WAVE_CONFIG + DECISION_DEFAULTS,
mirrored here as pure constants) so they never drift from the engine; the registry
holds only the qualitative content. Pure + DB-free + read-only -> 16/16 by construction.
"""
