"""
RA-3C — add fact_nodes evidence columns to the 14 vw_*_context views.

Makes the SQL layer expose the same evidence the runtime ContextEnricher
(RA-3B) puts in the bundle. Each view is WRAPPED as:

    CREATE OR REPLACE VIEW v AS
    SELECT base.*, <evidence scalar subqueries on base.application_id>
    FROM ( <original view definition> ) base

base.* preserves every existing column in order (so CREATE OR REPLACE is
legal — only new columns are appended); the ev_* columns are correlated
scalar subqueries against fact_nodes WHERE superseded_by IS NULL (null-safe
for apps with no facts). No existing column is reordered or retyped.

Idempotent: a view that already has evidence_populated is skipped. Original
definitions are backed up to _view_defs_backup_ra3c.sql before any change so
the wrap is reversible.

  python scripts/migrations/add_evidence_columns_to_views.py
"""

import asyncio
import os
import pathlib
from dotenv import load_dotenv
load_dotenv()

# Per-fact-type evidence groups: prefix -> (fact_type)
GROUPS = {
    "ev_income":     ("qualifying_income",      "income"),
    "ev_credit":     ("governing_credit_score", "credit"),
    "ev_asset":      ("verified_assets",        "asset"),
    "ev_employment": ("employment_continuity",  "employment"),
}

# Which per-fact groups each view gets (every view also gets the ev_all
# aggregate). Mapped to the REAL 14 context views (no collateral view exists).
VIEW_GROUPS = {
    "vw_income_verification_context":     ["ev_income", "ev_employment"],
    "vw_credit_assessment_context":       ["ev_credit", "ev_employment"],
    "vw_asset_verification_context":      ["ev_asset"],
    "vw_product_eligibility_context":     ["ev_income", "ev_credit", "ev_asset", "ev_employment"],
    "vw_fraud_screening_context":         ["ev_income", "ev_employment"],
    "vw_compliance_check_context":        ["ev_income", "ev_credit"],
    "vw_dti_calculation_context":         ["ev_income", "ev_employment"],
    "vw_employment_reconciliation_context": ["ev_employment"],
    "vw_ltv_assessment_context":          ["ev_asset"],
    "vw_underwriting_decision_context":   ["ev_income", "ev_credit", "ev_asset", "ev_employment"],
    "vw_closing_readiness_context":       ["ev_asset"],
    "vw_approval_routing_context":        [],
    "vw_rate_pricing_context":            ["ev_credit"],
    "vw_title_assessment_context":        [],
}

BACKUP = pathlib.Path(
    "scripts/migrations/_view_defs_backup_ra3c.sql"
)


def _u():
    return os.environ["DATABASE_URL"].replace("+asyncpg", "").replace(
        "postgresql+psycopg2", "postgresql")


def _fact_cols(prefix: str, fact_type: str, label: str) -> list[str]:
    """5 correlated scalar columns for one fact type, keyed on base."""
    def sub(col):
        return (
            f"(SELECT fn.{col} FROM fact_nodes fn "
            f"WHERE fn.application_id = base.application_id "
            f"AND fn.fact_type = '{fact_type}' "
            f"AND fn.superseded_by IS NULL "
            f"ORDER BY fn.created_at DESC LIMIT 1)"
        )
    return [
        f"{sub('fact_value')} AS {prefix}_value",
        f"{sub('confidence')} AS {prefix}_confidence",
        f"{sub('resolution_method')} AS {prefix}_method",
        f"{sub('conflicts_found')} AS {prefix}_conflicts",
        f"{sub('conflict_ids')} AS {prefix}_conflict_ids",
    ]


def _agg_cols() -> list[str]:
    """3 aggregate evidence-health columns (all current facts for the app)."""
    base_where = (
        "FROM fact_nodes fn WHERE fn.application_id = base.application_id "
        "AND fn.superseded_by IS NULL"
    )
    return [
        f"(SELECT COUNT(*) > 0 {base_where}) AS evidence_populated",
        f"(SELECT BOOL_OR(fn.conflicts_found) {base_where}) AS evidence_any_conflicts",
        f"(SELECT MIN(fn.confidence) {base_where}) AS evidence_overall_confidence",
    ]


def _evidence_select(view: str) -> str:
    cols: list[str] = []
    for prefix in VIEW_GROUPS[view]:
        fact_type, label = GROUPS[prefix]
        cols += _fact_cols(prefix, fact_type, label)
    cols += _agg_cols()
    return ",\n    ".join(cols)


async def main():
    import asyncpg
    conn = await asyncpg.connect(_u())
    updated, skipped = [], []
    backup_lines = []
    try:
        for view in VIEW_GROUPS:
            # Already enriched?
            has_ev = await conn.fetchval(
                """SELECT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = $1 AND column_name = 'evidence_populated')""",
                view,
            )
            if has_ev:
                skipped.append(view)
                print(f"{view}: already has evidence columns, skipping")
                continue

            orig = await conn.fetchval(
                "SELECT pg_get_viewdef($1, true)", view
            )
            backup_lines.append(
                f"-- {view}\nCREATE OR REPLACE VIEW {view} AS\n{orig}\n"
            )
            inner = orig.rstrip().rstrip(";").rstrip()
            ev_select = _evidence_select(view)
            new_sql = (
                f"CREATE OR REPLACE VIEW {view} AS\n"
                f"SELECT base.*,\n    {ev_select}\n"
                f"FROM (\n{inner}\n) base"
            )
            await conn.execute(new_sql)
            updated.append(view)
            n_ev = len(VIEW_GROUPS[view]) * 5 + 3
            print(f"{view}: wrapped (+{n_ev} evidence columns)")

        if backup_lines:
            BACKUP.write_text(
                "-- RA-3C original view definitions (pre-evidence)\n"
                "-- restore by running these to revert the wrap.\n\n"
                + "\n".join(backup_lines),
                encoding="utf-8",
            )
            print(f"\nBacked up {len(backup_lines)} original defs -> {BACKUP}")

        print(f"\nUpdated: {len(updated)}  Skipped: {len(skipped)}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
