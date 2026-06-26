"""Unit tests for CF-B FairLendingSelfTest + PeerGroupMatcher (pure, no DB).

Synthetic joined rows (hmda_lar codes + entity_states bands) exercise the
peer-group matched 4/5 analysis, the not-provided handling per protected class,
the program wrapper (reuses CM-D), the privilege notice, and findings/remediation.
RULE 11: insufficient_data (never a fabricated finding) when groups are too small
or single/not-provided; honest disparity when the data shows it.
"""
import unittest

from core.compliance.fair_lending_self_test import (
    DTI_BANDS,
    FairLendingSelfTest,
    PeerGroupMatcher,
    _band,
)

# HMDA codes: race 3=Black, 5=White, 6=Not provided; sex 1=Male, 2=Female, 3=Not provided.
# action_taken: 1/2=approve, 3=deny.


def _row(race, action, score=700, dti=40, ltv=80, sex=1):
    return {"applicant_race": race, "applicant_sex": sex, "action_taken": action,
            "mid_credit_score": score, "dti_back": dti, "ltv": ltv}


class BandTests(unittest.TestCase):
    def test_contiguous_no_gap(self):
        # 36.5 must NOT fall through to 'unknown'
        self.assertEqual(_band(36.5, DTI_BANDS), "37-43%")
        self.assertEqual(_band(36.0, DTI_BANDS), "<=36%")
        self.assertEqual(_band(80.0, DTI_BANDS), ">50%")

    def test_none_unknown(self):
        self.assertEqual(_band(None, DTI_BANDS), "unknown")


class PeerGroupMatcherTests(unittest.TestCase):
    def setUp(self):
        self.m = PeerGroupMatcher(min_sample=5, four_fifths_ratio=0.80)

    def test_buckets_by_bands(self):
        rows = [_row(5, 1, score=750, dti=30, ltv=70), _row(3, 1, score=610, dti=55, ltv=99)]
        groups = self.m.build_peer_groups(rows)
        self.assertEqual(len(groups), 2)  # different credit/dti/ltv bands

    def test_disparate_impact_within_peer(self):
        # same band; White all approved, Black mostly denied -> disparate impact
        rows = ([_row(5, 1) for _ in range(5)]      # White approved
                + [_row(3, 3) for _ in range(4)] + [_row(3, 1)])  # Black 80% denied
        out = self.m.analyze_peer_group(("700-739", "37-43%", "<=80%"), rows, "race")
        self.assertEqual(out["status"], "disparate_impact")
        self.assertTrue(out["has_disparate_impact"])

    def test_clean_when_equal(self):
        rows = [_row(5, 1) for _ in range(4)] + [_row(3, 1) for _ in range(4)]
        out = self.m.analyze_peer_group(("700-739", "37-43%", "<=80%"), rows, "race")
        self.assertEqual(out["status"], "clean")
        self.assertFalse(out["has_disparate_impact"])

    def test_small_sample_insufficient(self):
        out = self.m.analyze_peer_group(("700-739", "37-43%", "<=80%"),
                                        [_row(5, 1), _row(3, 3)], "race")
        self.assertEqual(out["status"], "insufficient_data")
        self.assertIn("sample_too_small", out["reason"])

    def test_single_group_insufficient(self):
        rows = [_row(5, 1) for _ in range(6)]  # all White
        out = self.m.analyze_peer_group(("700-739", "37-43%", "<=80%"), rows, "race")
        self.assertEqual(out["status"], "insufficient_data")

    def test_all_not_provided_insufficient_race(self):
        rows = [_row(6, 1) for _ in range(6)]  # race 6 = not provided
        out = self.m.analyze_peer_group(("700-739", "37-43%", "<=80%"), rows, "race")
        self.assertEqual(out["status"], "insufficient_data")

    def test_sex_not_provided_code_3_excluded(self):
        # sex=3 is NOT-PROVIDED for sex (the spec's hardcoded race codes would have
        # treated it as a real group); confirm it's excluded -> insufficient
        rows = [_row(5, 1, sex=3) for _ in range(6)]
        out = self.m.analyze_peer_group(("700-739", "37-43%", "<=80%"), rows, "sex")
        self.assertEqual(out["status"], "insufficient_data")

    def test_rule11(self):
        out = self.m.analyze_peer_group(("700-739", "37-43%", "<=80%"), [_row(5, 1)], "race")
        self.assertIn("data_source", out)
        self.assertIn("missing_inputs", out)


class FairLendingSelfTestTests(unittest.TestCase):
    def setUp(self):
        self.t = FairLendingSelfTest()

    def _run(self, hmda, joined):
        return self.t.run(hmda_rows=hmda, joined_rows=joined, period_start="2024-01-01",
                          period_end="2024-12-31", tenant_id="t", now_iso="2026-06-26T00:00:00Z")

    def test_meridian_like_clean_no_fabrication(self):
        # 16 rows, all race=6 / sex=3 not-provided -> 0 findings, clean
        hmda = [_row(6, [3, 3, 1][i % 3], sex=3) for i in range(16)]
        out = self._run(hmda, hmda)
        self.assertEqual(out["findings_count"], 0)
        self.assertEqual(out["overall_status"], "clean")
        self.assertFalse(out["peer_group_analysis"]["by_race"]["has_disparate_impact"])

    def test_disparity_produces_finding_and_remediation(self):
        joined = ([_row(5, 1) for _ in range(5)]
                  + [_row(3, 3) for _ in range(4)] + [_row(3, 1)])
        out = self._run(joined, joined)
        self.assertGreaterEqual(out["findings_count"], 1)
        self.assertEqual(out["overall_status"], "findings_requiring_remediation")
        self.assertEqual(len(out["remediation_recommendations"]), out["findings_count"])
        self.assertTrue(any(f["type"] == "peer_group_disparate_impact" for f in out["findings"]))

    def test_privilege_notice_always_present(self):
        out = self._run([], [])
        self.assertIn("PRIVILEGED SELF-TEST", out["privilege_notice"])
        self.assertIn("202.15", out["ecoa_citation"])

    def test_program_metadata(self):
        out = self._run([_row(5, 1)], [_row(5, 1)])
        self.assertEqual(len(out["test_id"]), 8)
        self.assertIn("peer-group", out["methodology"])
        self.assertIn("never use", out["note"].lower())
        self.assertIn("aggregate_analysis", out)  # reused CM-D

    def test_reuses_cm_d_aggregate(self):
        out = self._run([_row(5, 1)], [_row(5, 1)])
        # CM-D's run_full_monitor shape is present
        self.assertIn("monitor_status", out["aggregate_analysis"])

    def test_rule11_provenance(self):
        out = self._run([_row(5, 1)], [_row(5, 1)])
        self.assertIn("data_source", out)
        self.assertIn("missing_inputs", out)


if __name__ == "__main__":
    unittest.main()
