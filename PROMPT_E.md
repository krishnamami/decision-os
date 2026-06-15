# PROMPT E — Policy Studio Backend

Add all three to existing `api/accord/rules.py` and `frontend/src/pages/RulesSettings.tsx` without breaking existing logic. Deploy when all three work.

## Part 1 — Server-side floor enforcement on PUT /rules/overlay
Validate:
- `credit.min_score` ≥ 580 (FHA) — hard
- `credit.min_score` ≥ 620 (Fannie) — warn
- `dti.back_max` ≤ 57 — hard
- `dti.back_max` > 43 (QM) — warn
- `ltv.max` ≤ 97 — hard

Return 422 on errors, warnings object when `force=false`. Use existing `validate_overlay` helper if it exists, extend it if not.

## Part 2 — Shadow impact preview POST /rules/overlay/preview-impact
Compare proposed rules against active pipeline decisions using `context_snapshot`. Return `total_loans_affected`, `impact_by_decision` with sample loans, `recommendation`. Wire a "Preview Impact" button in RulesSettings before the submit button.

## Part 3 — Rate sheet upload POST /rate-sheet/upload
Accept CSV with columns `product_id, credit_band, ltv_max, base_rate, llpa_adjustment, effective_date`. Parse rows, upsert into `rate_schedule_period`. Log to `data_source_status`. Add a Rate Sheet tab to RulesSettings with file input, format guide, upload result, and last upload timestamp.
