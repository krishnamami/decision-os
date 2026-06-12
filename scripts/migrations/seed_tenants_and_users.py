"""Seed 5 tenants + users, distribute 200 curated loans, seed sample workbench data.

  python scripts/migrations/seed_tenants_and_users.py

Decisions baked in (user-confirmed, Session 23):
  * Roles EXTENDED — users_role_check widened to add processor/senior_uw/closer.
  * Loan-type quotas DROPPED — the dataset is ~97% conforming (only 5 jumbo /
    5 non_qm / 10 government exist), so the curated 50s vary by lifecycle
    status + stage and spread the few rare-type loans; no loan data is mutated.
  * Remainder STAYS under `demo` — the 4 named tenants each take 50 curated
    loans off demo; the ~8,696 rest keep tenant_id='demo' so the live AWS
    showcase (admin@demo.com) keeps working. `legacy` is created but empty.

Idempotent: re-running first returns the 4 named tenants' loans to demo and
drops their seed users/artifacts, then re-selects deterministically.
"""

import asyncio
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from core.auth.security import hash_password  # noqa: E402

PASSWORD = "accord2026"

# (tenant_id, name, plan, products, description)
TENANTS = [
    ("summit", "Summit Home Loans", "enterprise",
     ["pipeline", "analytics", "simulation", "audit"], "Mid-size retail lender, conventional + FHA focus"),
    ("pacific", "Pacific Coast Mortgage", "business",
     ["pipeline", "analytics", "simulation"], "West coast, higher amounts, jumbo + non-QM"),
    ("heartland", "Heartland Federal Credit Union", "growth",
     ["pipeline", "analytics"], "Credit union, smaller loans, community lending"),
    ("atlas", "Atlas Capital Partners", "enterprise",
     ["pipeline", "analytics", "simulation", "audit"], "Commercial-adjacent, jumbo specialist"),
    ("legacy", "Legacy Portfolio Services", "starter",
     ["pipeline"], "Holds remainder bulk data for simulation testing"),
]
NAMED = ["summit", "pacific", "heartland", "atlas"]
ALL5 = NAMED + ["legacy"]

# 7 non-admin slots in order — (email-local, role, title). Admin built separately.
ROLE_SLOTS = [
    ("manager", "manager", "Manager"),
    ("processor1", "processor", "Processor"),
    ("processor2", "processor", "Processor 2"),
    ("underwriter", "underwriter", "Underwriter"),
    ("senioruw", "senior_uw", "Senior UW"),
    ("closer", "closer", "Closer"),
    ("compliance", "compliance", "Compliance"),
]
NAMES = {
    "summit": ["Sarah", "Mike", "Lisa", "James", "Karen", "Tom", "Amy"],
    "pacific": ["Kenji", "Maria", "David", "Priya", "Alan", "Yuki", "Nina"],
    "heartland": ["Bob", "Linda", "Steve", "Diane", "Ray", "Pat", "Carol"],
    "atlas": ["Victoria", "Marcus", "Elena", "Wei", "Robert", "Sophia", "Chris"],
}

# lifecycle status mix per tenant (sums to 50)
MIX = {
    "summit":    {"active": 15, "pending_borrower": 10, "decided": 18, "halted": 5, "funded": 2},
    "pacific":   {"active": 12, "pending_borrower": 8,  "decided": 22, "halted": 5, "funded": 3},
    "heartland": {"active": 18, "pending_borrower": 7,  "decided": 20, "halted": 3, "funded": 2},
    "atlas":     {"active": 10, "pending_borrower": 8,  "decided": 25, "halted": 4, "funded": 3},
}
STAGES = ["verify", "underwrite", "eligibility", "decide", "close"]

NEW_ROLES = ["admin", "manager", "processor", "underwriter", "senior_uw", "closer", "compliance", "viewer"]


async def main() -> None:
    import asyncpg

    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not set")
    pw_hash = hash_password(PASSWORD)
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            # 0. Widen the role CHECK constraint to allow the new ops roles.
            await conn.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check")
            roles_sql = ", ".join(f"'{r}'" for r in NEW_ROLES)
            await conn.execute(f"ALTER TABLE users ADD CONSTRAINT users_role_check CHECK (role IN ({roles_sql}))")

            # 1. Reset (idempotent): drop named-tenant artifacts, return loans to demo.
            for tbl in ("loan_notes", "attention_requests", "loan_conditions", "communications", "notifications", "loan_assignments"):
                await conn.execute(f"DELETE FROM {tbl} WHERE tenant_id = ANY($1::text[])", ALL5)
            await conn.execute(
                "UPDATE entity_states SET tenant_id='demo', assigned_to=NULL, loan_status='active', current_stage='verify' "
                "WHERE tenant_id = ANY($1::text[])", NAMED)
            await conn.execute("UPDATE decision_outputs SET tenant_id='demo' WHERE tenant_id = ANY($1::text[])", NAMED)
            await conn.execute("DELETE FROM users WHERE tenant_id = ANY($1::text[])", ALL5)

            # 2. Tenants (upsert).
            for tid, name, plan, products, _desc in TENANTS:
                await conn.execute(
                    "INSERT INTO tenants (tenant_id, name, plan, products) VALUES ($1,$2,$3,$4::jsonb) "
                    "ON CONFLICT (tenant_id) DO UPDATE SET name=EXCLUDED.name, plan=EXCLUDED.plan, products=EXCLUDED.products",
                    tid, name, plan, json.dumps(products))

            # 3. Users — 8 per named tenant + legacy admin only. users[tid][slot] = user_id.
            users: dict[str, dict[str, str]] = {}
            for tid, name, *_ in TENANTS:
                users[tid] = {}
                disp = name.split()[0]  # "Summit", "Pacific", ...
                admin_id = await conn.fetchval(
                    "INSERT INTO users (tenant_id,email,password_hash,name,role) VALUES ($1,$2,$3,$4,'admin') RETURNING user_id",
                    tid, f"admin@{tid}.com", pw_hash, f"{disp} Admin")
                users[tid]["admin"] = admin_id
                if tid == "legacy":
                    continue
                for (local, role, title), first in zip(ROLE_SLOTS, NAMES[tid]):
                    uid = await conn.fetchval(
                        "INSERT INTO users (tenant_id,email,password_hash,name,role) VALUES ($1,$2,$3,$4,$5) RETURNING user_id",
                        tid, f"{local}@{tid}.com", pw_hash, f"{first} {title}", role)
                    users[tid][local] = uid

            # 4. Select 200 curated loans from demo: scenario + rare-type first, then fill.
            rows = await conn.fetch(
                "SELECT application_id AS app, loan_terms->>'loan_type' AS lt, "
                "COALESCE((borrower->'identity'->>'fraud_score')::float, 0) AS fraud "
                "FROM entity_states WHERE tenant_id='demo'")
            def rank(r):
                scenario = 0 if str(r["app"]).startswith("APP-SC") else 1
                rare = 0 if r["lt"] in ("non_qm", "jumbo", "government", "other") else 1
                return (scenario, rare, r["app"])
            pool = sorted(rows, key=rank)[:200]
            # Round-robin so scenario/rare edge cases spread across the 4 tenants.
            buckets: dict[str, list] = {t: [] for t in NAMED}
            for i, r in enumerate(pool):
                buckets[NAMED[i % 4]].append(r)

            summit_cat: dict[str, list[str]] = {}

            # 5. Per tenant: move loans, set lifecycle, assign to users.
            for tid in NAMED:
                loans = sorted(buckets[tid], key=lambda r: -r["fraud"])  # halted = highest fraud
                m = MIX[tid]
                order = (["halted"] * m["halted"] + ["active"] * m["active"]
                         + ["pending_borrower"] * m["pending_borrower"]
                         + ["decided"] * m["decided"] + ["funded"] * m["funded"])
                u = users[tid]
                active_i = 0
                cats: dict[str, list[str]] = {k: [] for k in ("active", "pending_borrower", "decided", "halted", "funded")}
                for i, (r, status) in enumerate(zip(loans, order)):
                    app = r["app"]
                    days_ago = {"active": i % 6, "halted": 1 + i % 4, "pending_borrower": 2 + i % 6,
                                "decided": 5 + i % 10, "funded": 7 + i % 8}[status]
                    if status == "active":
                        stage = STAGES[active_i % len(STAGES)]
                        if stage == "verify":
                            assignee = u["processor2"] if active_i % 2 else u["processor1"]
                        elif stage in ("underwrite", "eligibility"):
                            assignee = u["underwriter"]
                        elif stage == "decide":
                            assignee = u["senioruw"]
                        else:
                            assignee = u["closer"]
                        active_i += 1
                    elif status == "halted":
                        stage, assignee = "verify", u["processor2"]
                    elif status == "pending_borrower":
                        stage, assignee = "verify", u["processor1"]
                    elif status == "decided":
                        stage, assignee = "decide", u["senioruw"]
                    else:  # funded
                        stage, assignee = "close", u["closer"]

                    await conn.execute(
                        "UPDATE entity_states SET tenant_id=$1, assigned_to=$2, current_stage=$3, loan_status=$4 WHERE application_id=$5",
                        tid, assignee, stage, status, app)
                    await conn.execute("UPDATE decision_outputs SET tenant_id=$1 WHERE application_id=$2", tid, app)
                    asg_status = status if status in ("active", "pending_borrower", "decided", "funded") else "active"
                    await conn.execute(
                        "INSERT INTO loan_assignments (application_id, tenant_id, assigned_to, assigned_by, stage, status, assigned_at) "
                        "VALUES ($1,$2,$3,$4,$5,$6, NOW() - make_interval(days => $7))",
                        app, tid, assignee, u["admin"], stage, asg_status, days_ago)
                    cats[status].append(app)
                if tid == "summit":
                    summit_cat = cats

            # 6. Sample workbench data for Summit.
            u = users["summit"]
            active = summit_cat["active"]
            decided = summit_cat["decided"]
            pending = summit_cat["pending_borrower"]
            today = date.today()

            notes = [
                (active[0], u["processor1"], "Called borrower — bonus not on W2, employer letter coming Friday", "general"),
                (active[1], u["underwriter"], "Verified employment by phone with HR, job title matches", "general"),
                (active[2], u["processor2"], "Assets sourced; large deposit explained by tax refund (documented)", "general"),
                (decided[0], u["senioruw"], "Cleared to underwriting — credit + income reconciled", "handoff"),
            ]
            for app, uid, note, nt in notes:
                await conn.execute(
                    "INSERT INTO loan_notes (application_id, tenant_id, user_id, note, note_type) VALUES ($1,'summit',$2,$3,$4)",
                    app, uid, note, nt)

            attn = [
                (active[3], u["underwriter"], u["processor1"], "Re-verify employer phone — number on file is disconnected", "urgent"),
                (decided[1], u["closer"], u["underwriter"], "Need updated payoff statement before we can schedule closing", "normal"),
            ]
            for app, frm, to, msg, pri in attn:
                await conn.execute(
                    "INSERT INTO attention_requests (application_id, tenant_id, from_user_id, to_user_id, message, priority, status) "
                    "VALUES ($1,'summit',$2,$3,$4,$5,'open')", app, frm, to, msg, pri)

            conds = [
                (decided[0], "Updated W2 (most recent year)", "ptd", "outstanding"),
                (decided[1], "Flood certification", "ptc", "in_progress"),
                (decided[2], "Title insurance commitment", "ptc", "satisfied"),
                (decided[3], "Homeowner's insurance binder", "ptc", "outstanding"),
                (decided[4], "Final VOE within 10 days of closing", "ptf", "outstanding"),
                (decided[5], "Signed 4506-C", "ptd", "satisfied"),
            ]
            for app, text, ctype, st in conds:
                satisfied_by = u["processor1"] if st == "satisfied" else None
                satisfied_at = datetime.now() if st == "satisfied" else None
                await conn.execute(
                    "INSERT INTO loan_conditions (application_id, tenant_id, condition_text, condition_type, assigned_to, created_by, due_date, status, satisfied_by, satisfied_at) "
                    "VALUES ($1,'summit',$2,$3,$4,$5,$6,$7,$8,$9)",
                    app, text, ctype, u["processor1"], u["underwriter"], today + timedelta(days=10), st, satisfied_by, satisfied_at)

            comms = [
                (pending[0], "david.park@email.com", "Document request — W2", "Please upload your most recent W2.", ["W2 (2025)"]),
                (pending[1], "maria.santos@email.com", "Document request — bank statements", "Please upload 2 months of bank statements.", ["Bank statement (last 60 days)"]),
                (pending[2], "james.lee@email.com", "Document request — paystubs", "Please upload your two most recent paystubs.", ["Paystub", "Paystub (prior)"]),
            ]
            for app, email, subj, body, items in comms:
                await conn.execute(
                    "INSERT INTO communications (application_id, tenant_id, type, direction, from_user_id, recipient_email, subject, body, items_requested, status, due_date) "
                    "VALUES ($1,'summit','doc_request','outbound',$2,$3,$4,$5,$6::jsonb,'simulated',$7)",
                    app, u["processor1"], email, subj, body, json.dumps(items), today + timedelta(days=7))

            notifs = [
                (u["processor1"], "borrower_responded", "David Park responded to your document request", pending[0]),
                (u["underwriter"], "loan_assigned", "New loan assigned: Maria Santos $310K", active[4]),
                (u["processor1"], "attention_request", "Sarah Manager flagged a loan for re-verification", active[3]),
                (u["closer"], "decision_made", "Loan approved — ready for closing prep", decided[0]),
                (u["senioruw"], "rate_lock_warning", "Rate lock expires in 3 days on a pending file", decided[1]),
                (u["admin"], "escalation", "Compliance flagged a TRID timing issue", active[0]),
            ]
            for uid, ntype, title, app in notifs:
                await conn.execute(
                    "INSERT INTO notifications (tenant_id, user_id, type, title, application_id) VALUES ('summit',$1,$2,$3,$4)",
                    uid, ntype, title, app)

        # 7. Verify (outside the txn).
        print("Seed applied.\n")
        print("Tenants + users + loans:")
        for tid, name, plan, *_ in TENANTS:
            nu = await conn.fetchval("SELECT count(*) FROM users WHERE tenant_id=$1", tid)
            nl = await conn.fetchval("SELECT count(*) FROM entity_states WHERE tenant_id=$1", tid)
            print(f"  {tid:10s} {plan:11s} users={nu}  loans={nl}")
        demo_loans = await conn.fetchval("SELECT count(*) FROM entity_states WHERE tenant_id='demo'")
        print(f"  {'demo':10s} {'(remainder)':11s} loans={demo_loans}")
        print("\nSummit loan_status mix:",
              {r['loan_status']: r['count'] for r in await conn.fetch(
                  "SELECT loan_status, count(*) FROM entity_states WHERE tenant_id='summit' GROUP BY 1 ORDER BY 1")})
        print("Summit sample data:",
              {t: await conn.fetchval(f"SELECT count(*) FROM {t} WHERE tenant_id='summit'")
               for t in ("loan_assignments", "loan_notes", "attention_requests", "loan_conditions", "communications", "notifications")})
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
