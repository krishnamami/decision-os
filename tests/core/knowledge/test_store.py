"""KnowledgeStore tests — Document/Claim CRUD + verify/reject lifecycle.

  python -m unittest tests.core.knowledge.test_store
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
    CLAIM_ENTITY_TYPE,
    DOCUMENT_ENTITY_TYPE,
    ClaimRecord,
    DocumentRecord,
    KnowledgeStore,
)


def _store() -> KnowledgeStore:
    backing = LendingContextStore(InMemoryHotCache(), InMemoryDurableStore())
    return KnowledgeStore(backing)


def _doc(
    *,
    document_id: str = "doc_test_w2",
    application_id: str = "app_test",
    applicant_id: str = "cust_test",
    doc_type: str = "w2",
    status: str = "verified",
) -> DocumentRecord:
    return DocumentRecord(
        document_id=document_id,
        application_id=application_id,
        applicant_id=applicant_id,
        doc_type=doc_type,
        status=status,
        source_system="test",
        uploaded_at=datetime(2026, 4, 1),
        ocr_confidence=0.9,
        page_count=1,
        mime_type="application/pdf",
    )


def _claim(
    *,
    claim_id: str = "claim_test",
    document_id: str = "doc_test_w2",
    application_id: str = "app_test",
    field_name: str = "verified_income",
    field_value=120000,
    status: str = "pending",
) -> ClaimRecord:
    return ClaimRecord(
        claim_id=claim_id,
        document_id=document_id,
        application_id=application_id,
        applicant_id="cust_test",
        field_name=field_name,
        field_value=field_value,
        extraction_method="llm_extract",
        extraction_confidence=0.92,
        status=status,
        extracted_at=datetime(2026, 4, 1),
    )


class DocumentCrudTests(unittest.IsolatedAsyncioTestCase):

    async def test_put_get_round_trip(self):
        store = _store()
        await store.put_document(_doc())
        got = await store.get_document("doc_test_w2")
        self.assertIsNotNone(got)
        self.assertEqual(got.doc_type, "w2")
        self.assertEqual(got.application_id, "app_test")

    async def test_get_unknown_returns_none(self):
        store = _store()
        self.assertIsNone(await store.get_document("ghost"))

    async def test_byte_identical_put_does_not_supersede(self):
        store = _store()
        backing = store._store._durable  # type: ignore[attr-defined]
        await store.put_document(_doc())
        records_before = len(backing._records)
        await store.put_document(_doc())  # same bytes
        self.assertEqual(len(backing._records), records_before)

    async def test_status_change_supersedes(self):
        store = _store()
        backing = store._store._durable  # type: ignore[attr-defined]
        await store.put_document(_doc(status="ocr_extracted"))
        records_before = len(backing._records)
        await store.put_document(_doc(status="verified"))
        # Different bytes (status field changed) → new versioned record.
        self.assertEqual(len(backing._records), records_before + 1)


class ClaimCrudTests(unittest.IsolatedAsyncioTestCase):

    async def test_put_get_round_trip(self):
        store = _store()
        await store.put_claim(_claim())
        got = await store.get_claim("claim_test")
        self.assertIsNotNone(got)
        self.assertEqual(got.field_name, "verified_income")
        self.assertEqual(got.field_value, 120000)
        self.assertEqual(got.status, "pending")

    async def test_is_verified_helper(self):
        c = _claim(status="verified")
        self.assertTrue(c.is_verified)
        c2 = _claim(status="pending")
        self.assertFalse(c2.is_verified)

    async def test_byte_identical_put_does_not_supersede(self):
        store = _store()
        backing = store._store._durable  # type: ignore[attr-defined]
        await store.put_claim(_claim())
        records_before = len(backing._records)
        await store.put_claim(_claim())
        self.assertEqual(len(backing._records), records_before)


class ClaimLifecycleTests(unittest.IsolatedAsyncioTestCase):

    async def test_verify_claim_flips_status(self):
        store = _store()
        await store.put_claim(_claim(status="pending"))
        updated = await store.verify_claim(
            "claim_test", reviewer_id="bgoud", reviewer_role="underwriter"
        )
        self.assertIsNotNone(updated)
        self.assertEqual(updated.status, "verified")
        self.assertIsNotNone(updated.verified_at)
        self.assertEqual(updated.verified_by, "underwriter:bgoud")
        # Persisted.
        again = await store.get_claim("claim_test")
        self.assertEqual(again.status, "verified")

    async def test_verify_claim_unknown_returns_none(self):
        store = _store()
        result = await store.verify_claim(
            "ghost", reviewer_id="x", reviewer_role="y"
        )
        self.assertIsNone(result)

    async def test_reject_claim_flips_status(self):
        store = _store()
        await store.put_claim(_claim(status="pending"))
        updated = await store.reject_claim(
            "claim_test",
            reviewer_id="bgoud",
            reviewer_role="underwriter",
            reason="OCR garbled the income field",
        )
        self.assertIsNotNone(updated)
        self.assertEqual(updated.status, "rejected")
        self.assertEqual(updated.verified_by, "underwriter:bgoud")
        again = await store.get_claim("claim_test")
        self.assertEqual(again.status, "rejected")


class ListTests(unittest.IsolatedAsyncioTestCase):

    async def test_list_documents_filters_by_app(self):
        store = _store()
        await store.put_document(_doc(document_id="d1", application_id="appA"))
        await store.put_document(_doc(document_id="d2", application_id="appB"))
        a = await store.list_documents("appA")
        b = await store.list_documents("appB")
        self.assertEqual(len(a), 1)
        self.assertEqual(a[0].document_id, "d1")
        self.assertEqual(len(b), 1)
        self.assertEqual(b[0].document_id, "d2")

    async def test_list_documents_filters_by_doc_type(self):
        store = _store()
        await store.put_document(_doc(document_id="d_w2", doc_type="w2"))
        await store.put_document(_doc(document_id="d_appraisal", doc_type="appraisal_report"))
        w2s = await store.list_documents("app_test", doc_type="w2")
        self.assertEqual(len(w2s), 1)
        self.assertEqual(w2s[0].doc_type, "w2")

    async def test_list_documents_filters_by_status(self):
        store = _store()
        await store.put_document(_doc(document_id="d_v", status="verified"))
        await store.put_document(_doc(document_id="d_p", status="ocr_extracted"))
        verified = await store.list_documents("app_test", status="verified")
        self.assertEqual(len(verified), 1)
        self.assertEqual(verified[0].document_id, "d_v")

    async def test_list_claims_filters_by_field_name(self):
        store = _store()
        await store.put_claim(_claim(claim_id="c_inc", field_name="verified_income"))
        await store.put_claim(_claim(claim_id="c_emp", field_name="employer"))
        income = await store.list_claims("app_test", field_name="verified_income")
        self.assertEqual(len(income), 1)
        self.assertEqual(income[0].claim_id, "c_inc")

    async def test_list_claims_filters_by_status(self):
        store = _store()
        await store.put_claim(_claim(claim_id="c1", status="verified"))
        await store.put_claim(_claim(claim_id="c2", status="pending"))
        verified = await store.list_claims("app_test", status="verified")
        self.assertEqual(len(verified), 1)
        self.assertEqual(verified[0].claim_id, "c1")

    async def test_list_claims_filters_by_document_id(self):
        store = _store()
        await store.put_claim(_claim(claim_id="c1", document_id="docA"))
        await store.put_claim(_claim(claim_id="c2", document_id="docB"))
        result = await store.list_claims("app_test", document_id="docA")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].claim_id, "c1")


if __name__ == "__main__":
    unittest.main()
