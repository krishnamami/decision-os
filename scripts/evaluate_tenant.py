"""Universal tenant evaluation script for Decision OS.

Reads entity_states from RDS for any tenant, runs the full production
decision pipeline (PersonaRunner._process_one), writes decision_outputs,
and prints a summary.

Usage:
  python scripts/evaluate_tenant.py --tenant capital_loans
  python scripts/evaluate_tenant.py --tenant meridian
  python scripts/evaluate_tenant.py --tenant heartland
  python scripts/evaluate_tenant.py --tenant capital_loans --seq
  python scripts/evaluate_tenant.py --tenant capital_loans --concurrency=8
  python scripts/evaluate_tenant.py --tenant capital_loans --dry-run
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

DEFAULT_CONCURRENCY = 4
PER_SCENARIO_TIMEOUT = int(os.getenv("SCENARIO_TIMEOUT", "30"))


def _parse_args() -> tuple[str, int, bool, bool]:
    tenant = None
    concurrency = DEFAULT_CONCURRENCY
    dry_run = "--dry-run" in sys.argv

    for a in sys.argv[1:]:
        if a.startswith("--tenant="):
            tenant = a.split("=", 1)[1]
        elif a == "--tenant" and sys.argv.index(a) + 1 < len(sys.argv):
            tenant = sys.argv[sys.argv.index(a) + 1]
        elif a.startswith("--concurrency="):
            try:
                concurrency = max(1, int(a.split("=", 1)[1]))
            except ValueError:
                pass
        elif a == "--seq":
            concurrency = 1

    if not tenant:
        print("ERROR: --tenant is required")
        print("Usage: python scripts/evaluate_tenant.py --tenant <tenant_id>")
        sys.exit(1)

    return tenant, concurrency, dry_run, "--direct" in sys.argv, "--clean" in sys.argv


async def main():
    from core.cron.runner import WAVES
    from core.scenarios.runner import ScenarioRunner

    tenant, concurrency, dry_run, direct, clean = _parse_args()

    print(f"\n{'='*60}")
    print(f"  Decision OS — Tenant Evaluation")
    print(f"  Tenant:      {tenant}")
    print(f"  Concurrency: {concurrency}")
    print(f"  Timeout:     {PER_SCENARIO_TIMEOUT}s per decision")
    print(f"  Dry run:     {dry_run}")
    print(f"{'='*60}\n")

    url = os.environ["DATABASE_URL"].replace("+asyncpg", "").replace(
        "postgresql+psycopg2", "postgresql")

    sr = await ScenarioRunner(
        url, tenant,
        concurrency=concurrency,
        timeout=PER_SCENARIO_TIMEOUT,
    ).setup()

    try:
        app_ids = await sr.app_ids()

        if not app_ids:
            print(f"ERROR: No applications found for tenant '{tenant}'")
            print("Check that entity_states are loaded for this tenant.")
            return

        wave_count = sum(len(w) for w in WAVES)
        # Clean mode: delete all existing decisions before re-running
        if clean:
            import asyncpg as _apg
            _db_url = os.environ.get("DATABASE_URL", "").replace("+asyncpg", "").replace("postgresql+psycopg2", "postgresql")
            _clean_conn = await _apg.connect(_db_url)
            try:
                deleted = await _clean_conn.execute(
                    "DELETE FROM decision_outputs WHERE tenant_id=$1", tenant
                )
                print(f"Cleaned all decisions for {tenant}: {deleted}")
            finally:
                await _clean_conn.close()
        # Remove pure duplicates before re-running
        await sr.conn.execute("""
            DELETE FROM decision_outputs d
            WHERE tenant_id = $1
            AND EXISTS (
                SELECT 1 FROM decision_outputs d2
                WHERE d2.application_id = d.application_id
                AND d2.decision_id = d.decision_id
                AND d2.tenant_id = d.tenant_id
                AND d2.outcome = d.outcome
                AND d2.context_snapshot = d.context_snapshot
                AND d2.version > d.version
            )
        """, tenant)
        print(f'Removed pure duplicates for {tenant}')
        print(f"Found {len(app_ids)} applications")
        print(f"Running {wave_count} decision types per application")
        print(f"Total decisions to evaluate: {len(app_ids) * wave_count}\n")

        if dry_run:
            print("DRY RUN — listing applications only:")
            for app_id in app_ids:
                print(f"  {app_id}")
            return

        # Run evaluation
        errors = []
        def _on_error(r, n):
            errors.append(r)
            print(f"  ! {r[0]}/{r[1]}: {r[2]}")

        print("Evaluating...")
        await sr.execute(app_ids, on_error=_on_error)

        # Summary
        import asyncpg
        conn = await asyncpg.connect(url)
        try:
            total_decisions = await conn.fetchval(
                "SELECT COUNT(*) FROM decision_outputs WHERE tenant_id=$1", tenant)

            outcome_rows = await conn.fetch("""
                SELECT outcome, COUNT(*) as cnt
                FROM decision_outputs
                WHERE tenant_id=$1
                GROUP BY outcome
                ORDER BY cnt DESC
            """, tenant)

            decision_rows = await conn.fetch("""
                SELECT decision_id, outcome, COUNT(*) as cnt
                FROM decision_outputs
                WHERE tenant_id=$1
                GROUP BY decision_id, outcome
                ORDER BY decision_id, outcome
            """, tenant)

            app_rows = await conn.fetch("""
                SELECT es.los_id, es.status,
                       COUNT(d.id) as decision_count,
                       STRING_AGG(d.outcome, ', ' ORDER BY d.decision_id) as outcomes
                FROM entity_states es
                LEFT JOIN decision_outputs d
                  ON d.application_id = es.application_id
                  AND d.tenant_id = es.tenant_id
                WHERE es.tenant_id=$1
                GROUP BY es.los_id, es.status
                ORDER BY es.los_id
            """, tenant)

        finally:
            await conn.close()

        print(f"\n{'='*60}")
        print(f"  RESULTS — {tenant}")
        print(f"{'='*60}")
        print(f"\nTotal decision_outputs written: {total_decisions}")
        print(f"Errors: {len(errors)}")

        print(f"\n--- Outcome distribution ---")
        for row in outcome_rows:
            print(f"  {row['outcome']:<20} {row['cnt']:>4}")

        print(f"\n--- Per decision type ---")
        for row in decision_rows:
            print(f"  {row['decision_id']:<35} {row['outcome']:<15} {row['cnt']:>4}")

        print(f"\n--- Per application ---")
        for row in app_rows:
            print(f"  {row['los_id']:<12} {row['status']:<30} decisions={row['decision_count']}")

        if errors:
            print(f"\n--- Errors ---")
            for e in errors:
                print(f"  {e[0]}/{e[1]}: {e[2]}")

        print(f"\n{'='*60}\n")

    finally:
        await sr.close()


asyncio.run(main())
