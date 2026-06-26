"""Unit tests for CF-D StateFilingReport (pure, no DB).

Synthetic hmda_lar-shaped loans + license dicts exercise the license-driven
aggregation, the no-licenses / NULL-state_code honest gaps, the per-state counts /
volume / denial-rate / product mix, and the geographic breakdown statuses.
RULE 11 + the not-submitted note asserted throughout.
"""
import unittest

from core.compliance.state_filing import StateFilingReport

TX_LIC = {"state": "TX", "license_number": "ML-12345", "license_type": "Mortgage Lender"}
NY_LIC = {"state": "NY", "license_number": "LMB-99", "license_type": "Mortgage Banker"}


def _loan(state, action, amt, county=None, lt="conventional"):
    return {"state_code": state, "county_code": county, "loan_type": lt,
            "action_taken": action, "loan_amount": amt}


class NoLicenseTests(unittest.TestCase):
    def test_no_licenses(self):
        out = StateFilingReport().generate([], licenses=[], period="2024", tenant_id="meridian")
        self.assertEqual(out["status"], "no_licensed_states")
        self.assertEqual(out["state_packets"], [])
        self.assertTrue(out["missing_inputs"])
        self.assertIn("Submission", out["submission_note"])


class NullStateCodeTests(unittest.TestCase):
    def test_null_state_codes_flag_geocoding(self):
        loans = [_loan(None, "1", 400000), _loan(None, "3", 300000)]
        out = StateFilingReport().generate(loans, [TX_LIC], period="2024",
                                           tenant_id="meridian", nmls_id="999999")
        self.assertEqual(out["status"], "generated")
        self.assertEqual(len(out["state_packets"]), 1)
        pkt = out["state_packets"][0]
        self.assertEqual(pkt["summary"]["total_applications"], 0)
        self.assertTrue(any("state_code is NULL" in m for m in pkt["missing_inputs"]))


class AggregationTests(unittest.TestCase):
    def setUp(self):
        self.loans = [
            _loan("TX", "1", 450000, county="48113"),
            _loan("TX", "3", 280000, county=None, lt="fha"),
            _loan("TX", "3", 320000, county="48113"),
            _loan("NY", "1", 500000, county="36061"),  # different state
        ]
        self.out = StateFilingReport().generate(self.loans, [TX_LIC], period="2024",
                                                tenant_id="t", institution_name="Bank", nmls_id="123")
        self.tx = self.out["state_packets"][0]

    def test_filters_to_state(self):
        # only the 3 TX loans, not the NY one
        self.assertEqual(self.tx["summary"]["total_applications"], 3)

    def test_counts_and_denial_rate(self):
        s = self.tx["summary"]
        self.assertEqual(s["total_originated"], 1)
        self.assertEqual(s["total_denied"], 2)
        self.assertEqual(s["denial_rate_pct"], 66.7)  # 2/3
        self.assertEqual(s["action_breakdown"]["denied"], 2)

    def test_total_volume(self):
        self.assertEqual(self.tx["summary"]["total_volume_usd"], 450000 + 280000 + 320000)

    def test_product_breakdown(self):
        bp = self.tx["by_product_type"]
        self.assertEqual(bp["conventional"]["count"], 2)
        self.assertEqual(bp["fha"]["count"], 1)
        self.assertEqual(bp["fha"]["volume"], 280000)

    def test_geographic_partial(self):
        # 2 of 3 have county -> partial
        self.assertEqual(self.tx["geographic"]["status"], "partial")
        self.assertEqual(self.tx["geographic"]["by_county"]["48113"], 2)
        self.assertEqual(self.tx["geographic"]["missing_geo"], 1)

    def test_filing_references_state_specific(self):
        self.assertIsNotNone(self.tx["filing_references"]["tx_sml"])
        self.assertIsNone(self.tx["filing_references"]["ny_dfs"])
        self.assertIn("MCR", self.tx["filing_references"]["nmls_mcr"])

    def test_originator_nmls_always_flagged(self):
        self.assertTrue(any("originator NMLS" in m for m in self.tx["missing_inputs"]))

    def test_rule11(self):
        self.assertIn("data_source", self.tx)
        self.assertIn("missing_inputs", self.out)


class MultiStateAndEdgeTests(unittest.TestCase):
    def test_one_packet_per_license(self):
        loans = [_loan("TX", "1", 400000, county="48113"), _loan("NY", "1", 500000, county="36061")]
        out = StateFilingReport().generate(loans, [TX_LIC, NY_LIC], tenant_id="t")
        self.assertEqual(len(out["state_packets"]), 2)
        states = {p["state"] for p in out["state_packets"]}
        self.assertEqual(states, {"TX", "NY"})

    def test_geo_complete_when_all_county(self):
        loans = [_loan("TX", "1", 400000, county="48113"), _loan("TX", "3", 300000, county="48201")]
        out = StateFilingReport().generate(loans, [TX_LIC], tenant_id="t")
        self.assertEqual(out["state_packets"][0]["geographic"]["status"], "complete")

    def test_action_string_mapping(self):
        loans = [_loan("TX", "block", 300000, county="48113"),
                 _loan("TX", "recommend", 400000, county="48113")]
        pkt = StateFilingReport().generate(loans, [TX_LIC], tenant_id="t")["state_packets"][0]
        self.assertEqual(pkt["summary"]["total_denied"], 1)       # 'block' -> denied
        self.assertEqual(pkt["summary"]["total_originated"], 1)   # 'recommend' -> originated

    def test_all_denied_100_pct(self):
        loans = [_loan("TX", "3", 300000, county="48113")]
        pkt = StateFilingReport().generate(loans, [TX_LIC], tenant_id="t")["state_packets"][0]
        self.assertEqual(pkt["summary"]["denial_rate_pct"], 100.0)


if __name__ == "__main__":
    unittest.main()
