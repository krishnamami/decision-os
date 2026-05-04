"""MetadataRetriever tests — doc_type matrix filter, verified_only, multi-claim.

  python -m unittest tests.core.knowledge.test_retriever
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.context_store import (  # noqa: E402
    InMemoryDurableStore,
    InMemoryHotCache,
    LendingContextStore,
)
from core.knowledge import (  # noqa: E402
    ClaimRecord,
    DocumentRecord,
    KnowledgeStore,
    MetadataRetriever,
)


# Inline doc_type matrix for tests so we don't depend on the live
# knowledge_base.json file. Real path uses the loader; here we pass
# the matrix in directly.
TEST_MATRIX: dict = {
    "w2": {
        "feeds_decisions": ["income_verification"],
        "claims": ["verified_income", "employer"],
    },
    "appraisal_report": {
        "feeds_decisions": ["ltv_assessment"],
        "claims": ["appraised_value"],
    },
    "drivers_license": {
        "feeds_decisions": ["fraud_screening"],
        "claims": ["full_name", "date_of_birth"],
    },
}


def _retriever_pair() -> tuple[KnowledgeStore, MetadataRetriever]:
    backing = LendingContextStore(InMemoryHotCache(), InMemoryDurableStore())
    store = KnowledgeStore(backing)
    retriever = MetadataRetriever(store, doc_type_matrix=TEST_MATRIX)
    return store, retriever


def _doc(
    *, document_id: str, doc_type: str, application_id: str = "app_test"
) -> DocumentRecord:
    return DocumentRecord(
        document_id=document_id,
        application_id=application_id,
        applicant_id="cust_test",
        doc_type=doc_type,
        status="verified",
        uploaded_at=datetime(2026, 4, 1),
    )


def _claim(
    *,
    claim_id: str,
    document_id: str,
    field_name: str,
    field_value=120000,
    status: str = "verified",
    extracted_at: datetime | None = None,
    application_id: str = "app_test",
) -> ClaimRecord:
    return ClaimRecord(
        claim_id=claim_id,
        document_id=document_id,
        application_id=application_id,
        applicant_id="cust_test",
        field_name=field_name,
        field_value=field_value,
        status=status,
        extracted_at=extracted_at or datetime(2026, 4, 1),
        extraction_method="llm_extract",
        extraction_confidence=0.9,
    )


class DocTypeMatrixFilterTests(unittest.IsolatedAsyncioTestCase):

    async def test_income_verification_sees_w2_claims(self):
        store, retriever = _retriever_pair()
        await store.put_document(_doc(document_id="d_w2", doc_type="w2"))
        await store.put_claim(_claim(
            claim_id="c_income",
            document_id="d_w2",
            field_name="verified_income",
            field_value=124500,
        ))
        result = await retriever.retrieve("income_verification", "app_test")
        self.assertEqual(result.claims_by_field.get("verified_income"), 124500)

    async def test_fraud_screening_does_not_see_w2(self):
        store, retriever = _retriever_pair()
        await store.put_document(_doc(document_id="d_w2", doc_type="w2"))
        await store.put_claim(_claim(
            claim_id="c_inc",
            document_id="d_w2",
            field_name="verified_income",
        ))
        result = await retriever.retrieve("fraud_screening", "app_test")
        self.assertNotIn("verified_income", result.claims_by_field)

    async def test_ltv_sees_appraisal_not_w2(self):
        store, retriever = _retriever_pair()
        await store.put_document(_doc(document_id="d_w2", doc_type="w2"))
        await store.put_document(_doc(
            document_id="d_appraisal", doc_type="appraisal_report"
        ))
        await store.put_claim(_claim(
            claim_id="c_inc", document_id="d_w2", field_name="verified_income"
        ))
        await store.put_claim(_claim(
            claim_id="c_appraised",
            document_id="d_appraisal",
            field_name="appraised_value",
            field_value=525000,
        ))
        result = await retriever.retrieve("ltv_assessment", "app_test")
        self.assertEqual(result.claims_by_field.get("appraised_value"), 525000)
        self.assertNotIn("verified_income", result.claims_by_field)

    async def test_lead_scoring_has_zero_doc_types_consulted(self):
        # lead_scoring isn't in any feeds_decisions list in TEST_MATRIX.
        store, retriever = _retriever_pair()
        result = await retriever.retrieve("lead_scoring", "app_test")
        self.assertEqual(result.retrieval_metadata.get("doc_types_consulted"), 0)
        self.assertEqual(result.claims_by_field, {})


class VerifiedOnlyTests(unittest.IsolatedAsyncioTestCase):

    async def test_verified_only_default_excludes_pending(self):
        store, retriever = _retriever_pair()
        await store.put_document(_doc(document_id="d_w2", doc_type="w2"))
        await store.put_claim(_claim(
            claim_id="c_pending",
            document_id="d_w2",
            field_name="verified_income",
            field_value=120000,
            status="pending",
        ))
        result = await retriever.retrieve("income_verification", "app_test")
        self.assertNotIn("verified_income", result.claims_by_field)

    async def test_verified_only_false_includes_pending(self):
        store, retriever = _retriever_pair()
        await store.put_document(_doc(document_id="d_w2", doc_type="w2"))
        await store.put_claim(_claim(
            claim_id="c_pending",
            document_id="d_w2",
            field_name="verified_income",
            field_value=120000,
            status="pending",
        ))
        result = await retriever.retrieve(
            "income_verification", "app_test", verified_only=False
        )
        self.assertEqual(result.claims_by_field.get("verified_income"), 120000)


class MultiClaimCollapseTests(unittest.IsolatedAsyncioTestCase):

    async def test_latest_extracted_at_wins_when_multiple_for_same_field(self):
        # Two W-2s (e.g. two employers, two years) — both have a
        # verified_income claim. The retriever's claims_by_field collapses
        # to the latest by extracted_at.
        store, retriever = _retriever_pair()
        await store.put_document(_doc(document_id="d_w2_2024", doc_type="w2"))
        await store.put_document(_doc(document_id="d_w2_2023", doc_type="w2"))
        await store.put_claim(_claim(
            claim_id="c_2023",
            document_id="d_w2_2023",
            field_name="verified_income",
            field_value=110000,
            extracted_at=datetime(2024, 4, 1),
        ))
        await store.put_claim(_claim(
            claim_id="c_2024",
            document_id="d_w2_2024",
            field_name="verified_income",
            field_value=124500,
            extracted_at=datetime(2025, 4, 1),
        ))
        result = await retriever.retrieve("income_verification", "app_test")
        self.assertEqual(result.claims_by_field.get("verified_income"), 124500)

    async def test_claim_records_carry_full_provenance(self):
        store, retriever = _retriever_pair()
        await store.put_document(_doc(document_id="d_w2", doc_type="w2"))
        await store.put_claim(_claim(
            claim_id="c_inc",
            document_id="d_w2",
            field_name="verified_income",
        ))
        result = await retriever.retrieve("income_verification", "app_test")
        self.assertGreater(len(result.claim_records), 0)
        c = result.claim_records[0]
        self.assertEqual(c.field_name, "verified_income")
        self.assertEqual(c.document_id, "d_w2")
        self.assertEqual(c.status, "verified")


class CrossApplicationIsolationTests(unittest.IsolatedAsyncioTestCase):

    async def test_other_apps_claims_not_returned(self):
        # The retriever filters by application_id; another app's W-2
        # claim must not leak into ours.
        store, retriever = _retriever_pair()
        await store.put_document(_doc(
            document_id="d_w2_a", doc_type="w2", application_id="appA"
        ))
        await store.put_document(_doc(
            document_id="d_w2_b", doc_type="w2", application_id="appB"
        ))
        await store.put_claim(_claim(
            claim_id="c_a",
            document_id="d_w2_a",
            application_id="appA",
            field_name="verified_income",
            field_value=80000,
        ))
        await store.put_claim(_claim(
            claim_id="c_b",
            document_id="d_w2_b",
            application_id="appB",
            field_name="verified_income",
            field_value=200000,
        ))
        a_result = await retriever.retrieve("income_verification", "appA")
        b_result = await retriever.retrieve("income_verification", "appB")
        self.assertEqual(a_result.claims_by_field.get("verified_income"), 80000)
        self.assertEqual(b_result.claims_by_field.get("verified_income"), 200000)


class RetrievalMetadataTests(unittest.IsolatedAsyncioTestCase):

    async def test_metadata_reports_source_and_counts(self):
        store, retriever = _retriever_pair()
        await store.put_document(_doc(document_id="d_w2", doc_type="w2"))
        await store.put_claim(_claim(
            claim_id="c_inc",
            document_id="d_w2",
            field_name="verified_income",
        ))
        result = await retriever.retrieve("income_verification", "app_test")
        meta = result.retrieval_metadata
        self.assertEqual(meta.get("source"), "metadata")
        self.assertGreater(meta.get("doc_types_consulted", 0), 0)
        self.assertEqual(meta.get("documents_matched"), 1)
        self.assertEqual(meta.get("claims_returned"), 1)
        self.assertTrue(meta.get("verified_only"))


if __name__ == "__main__":
    unittest.main()
