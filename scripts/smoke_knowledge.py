"""STREAM E v0 smoke — Knowledge Context Layer.

Boots a Platform with seeded mock Documents + Claims, runs the
happy_path scenario, and asserts:

  1. Documents and Claims land in the durable store via run_scenario.
  2. KnowledgeStore.list_* finds them.
  3. MetadataRetriever filters claims by the doc_type → decisions
     matrix in knowledge_base.json — fraud_screening sees no W-2
     claims; income_verification sees verified_income from the W-2;
     ltv_assessment sees appraised_value from the appraisal.
  4. ContextBuilder.build attaches retrieved claims to bundle.claims
     (NOT bundle.objects — knowledge takes a separate path).
  5. Document and Claim ObjectTypes do NOT appear in bundle.objects
     (they're served via the retriever, not the resolver).
  6. Pending claims (contamination scenario W-2) don't leak — only
     verified claims appear in bundle.claims by default.

Run:
  python -X utf8 scripts/smoke_knowledge.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api.deps import build_default_platform  # noqa: E402
from core.policy_engine import seed_policies_from_yaml  # noqa: E402
from domains.lending.personas import register_with_platform  # noqa: E402
from domains.lending.seed_events.runner import run_scenario  # noqa: E402


def _ok(label: str, cond: bool) -> int:
    print(f"  [{'OK' if cond else 'MISS'}] {label}")
    return 0 if cond else 1


async def main() -> int:
    print("=" * 70)
    print("Knowledge Context Layer smoke (STREAM E v0)")
    print("=" * 70)

    failures = 0

    # ── Phase 1: happy_path docs + claims hydrate via run_scenario ────
    print("\n[1] happy_path — verified W-2 + appraisal docs + 3 claims")
    p = build_default_platform()
    register_with_platform(p)
    await seed_policies_from_yaml(p.spec, p.policy_store)
    await run_scenario(p, "happy_path")

    docs = await p.knowledge_store.list_documents("app_happy")
    claims = await p.knowledge_store.list_claims("app_happy")
    failures += _ok("happy_path has 2 documents", len(docs) == 2)
    failures += _ok("happy_path has 3 claims", len(claims) == 3)
    failures += _ok(
        "all happy_path claims are verified",
        all(c.is_verified for c in claims),
    )

    # ── Phase 2: Retriever filters by doc_type matrix ─────────────────
    print("\n[2] MetadataRetriever filters by doc_type → decisions matrix")

    # income_verification → reads w2 → expects verified_income claim
    iv = await p.retriever.retrieve("income_verification", "app_happy")
    failures += _ok(
        "income_verification: verified_income claim present",
        iv.claims_by_field.get("verified_income") == 124500,
    )
    failures += _ok(
        "income_verification: employer claim present",
        iv.claims_by_field.get("employer") == "Acme Engineering Co.",
    )

    # ltv_assessment → reads appraisal → expects appraised_value claim
    ltv = await p.retriever.retrieve("ltv_assessment", "app_happy")
    failures += _ok(
        "ltv_assessment: appraised_value claim present",
        ltv.claims_by_field.get("appraised_value") == 525000,
    )
    failures += _ok(
        "ltv_assessment: NO verified_income leaked from W-2",
        "verified_income" not in ltv.claims_by_field,
    )

    # fraud_screening → does NOT read W-2 or appraisal → empty claims
    fs = await p.retriever.retrieve("fraud_screening", "app_happy")
    failures += _ok(
        "fraud_screening: no W-2 / appraisal claims leak",
        len(fs.claims_by_field) == 0,
    )

    # lead_scoring → consumes no docs at all per the matrix
    ls = await p.retriever.retrieve("lead_scoring", "app_happy")
    failures += _ok(
        "lead_scoring: 0 doc_types_consulted",
        ls.retrieval_metadata.get("doc_types_consulted") == 0,
    )

    # ── Phase 3: ContextBuilder attaches claims to bundle.claims ──────
    print("\n[3] ContextBuilder.build attaches claims to bundle.claims")
    bundle = await p.builder.build(
        "app_happy", "income_verification", p.entity_resolver
    )
    failures += _ok(
        "bundle.claims['verified_income'] present",
        bundle.claims.get("verified_income") == 124500,
    )
    failures += _ok(
        "bundle.claim_records non-empty",
        len(bundle.claim_records) >= 2,
    )
    failures += _ok(
        "bundle.documents non-empty",
        len(bundle.documents) >= 1,
    )

    # ── Phase 4: Document + Claim NOT in bundle.objects ───────────────
    print("\n[4] Document + Claim ObjectTypes excluded from bundle.objects")
    failures += _ok(
        "bundle.objects has NO Document key",
        "Document" not in bundle.objects,
    )
    failures += _ok(
        "bundle.objects has NO Claim key",
        "Claim" not in bundle.objects,
    )
    failures += _ok(
        "bundle.objects still has Applicant",
        "Applicant" in bundle.objects,
    )

    # ── Phase 5: Pending claims don't leak ────────────────────────────
    print("\n[5] contamination — pending W-2 claim must NOT appear in bundle")
    p2 = build_default_platform()
    register_with_platform(p2)
    await seed_policies_from_yaml(p2.spec, p2.policy_store)
    await run_scenario(p2, "contamination")

    contam_claims = await p2.knowledge_store.list_claims("app_contam")
    failures += _ok(
        "contamination has 1 claim seeded",
        len(contam_claims) == 1,
    )
    failures += _ok(
        "that claim is in pending state",
        contam_claims[0].status == "pending" if contam_claims else False,
    )

    iv2 = await p2.retriever.retrieve("income_verification", "app_contam")
    failures += _ok(
        "verified_only=True (default) → pending claim NOT returned",
        "verified_income" not in iv2.claims_by_field,
    )

    iv2_all = await p2.retriever.retrieve(
        "income_verification", "app_contam", verified_only=False
    )
    failures += _ok(
        "verified_only=False → pending claim IS returned",
        "verified_income" in iv2_all.claims_by_field,
    )

    # ── Phase 6: verify_claim flips status, claim then appears ────────
    print("\n[6] verify_claim flips pending → verified")
    target = contam_claims[0]
    updated = await p2.knowledge_store.verify_claim(
        target.claim_id, reviewer_id="bgoud", reviewer_role="underwriter"
    )
    failures += _ok(
        "verify_claim returns updated record",
        updated is not None and updated.is_verified,
    )

    iv3 = await p2.retriever.retrieve("income_verification", "app_contam")
    failures += _ok(
        "post-verify: claim now appears in bundle (verified_only=True)",
        iv3.claims_by_field.get("verified_income") == 180000,
    )

    print("\n" + "=" * 70)
    if failures:
        print(f"Knowledge smoke FAILED with {failures} miss(es)")
        return 1
    print("Knowledge smoke OK")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
