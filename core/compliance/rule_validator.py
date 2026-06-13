"""Rule-boundary validation suite.

Generates synthetic loan scenarios at each rule boundary and runs them through a
deterministic decision engine (``evaluate``) to prove the boundaries behave as
documented — answering "how do I KNOW 43.1% DTI actually gets blocked?".

The expected outcome for each case is specified independently of ``evaluate`` (it
encodes the documented rule), so an off-by-one in the engine (>= vs >) is caught.
``evaluate`` resolves the tenant's three layers (regulatory floors + agency
guidelines + customer overlay). For correct rules every case passes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# Regulatory / agency constants (from regulatory_rules + agency_guidelines).
FHA_MIN_3_5 = 580        # FHA min score, 3.5% down
FHA_ABS_MIN = 500        # FHA absolute min, 10% down
CONV_MIN = 620           # Fannie/Freddie conventional min
DU_DTI_MAX = 50          # Fannie DU max DTI
QM_DTI = 43              # QM safe-harbor DTI
FHA_DTI_AUS = 57         # FHA max DTI with AUS
CONV_LTV_MAX = 97        # Fannie 1-unit primary
FHA_LTV_MAX = 96.5
VA_LTV_MAX = 100
TX_CASHOUT_LTV = 80
NY_USURY = 16
STATES_WITH_RULES = {"TX", "NY", "CA", "FL", "IL", "PA", "OH", "GA", "NC", "VA"}

OUT_ALLOW, OUT_REVIEW, OUT_BLOCK, OUT_ALLOW_IF = "allow", "review", "block", "allow_if"


@dataclass
class TestCase:
    id: str
    category: str
    description: str
    input: dict
    expected: set  # acceptable outcomes
    expected_label: str


@dataclass
class TestResult:
    id: str
    category: str
    description: str
    input: dict
    expected: str
    actual: str
    passed: bool
    flags: list = field(default_factory=list)


def resolve(tenant_rules: dict, programs: list[str]) -> dict:
    """Resolve the tenant's effective thresholds (overlay over regulatory/agency)."""
    c = tenant_rules.get("credit", {})
    d = tenant_rules.get("dti", {})
    l = tenant_rules.get("ltv", {})
    fr = tenant_rules.get("fraud", {})
    inc = tenant_rules.get("income", {})
    res = tenant_rules.get("reserves", {})
    review_band = d.get("review_band", [36, d.get("back_max", 43)])
    inc_band = inc.get("review_band_pct", [10, inc.get("max_discrepancy_pct", 25)])
    return {
        "programs": programs,
        "credit_min": c.get("min_score", 640),
        "dti_max": d.get("back_max", 43),
        "dti_review_low": review_band[0],
        "ltv_max": l.get("max", 95),
        "ltv_no_mi": l.get("no_mi_threshold", 80),
        "watchlist": fr.get("watchlist_threshold", 0.20),
        "identity_min": fr.get("identity_min", 0.85),
        "income_max_gap": inc.get("max_discrepancy_pct", 25),
        "income_review_low": inc_band[0],
        "reserves_primary": res.get("primary", 2),
        "reserves_investment": res.get("investment", 6),
    }


def evaluate(s: dict, R: dict) -> tuple[str, list]:
    """The decision engine under test. Returns (outcome, flags)."""
    if s.get("ofac_match"):
        return OUT_BLOCK, ["OFAC"]

    if "watchlist_score" in s:
        ws = s["watchlist_score"]
        if ws >= R["watchlist"]:
            return OUT_BLOCK, (["watchlist", "SAR"] if ws >= 0.78 else ["watchlist"])
        return OUT_ALLOW, []

    if "identity_confidence" in s:
        ic = s["identity_confidence"]
        if ic < 0.60:
            return OUT_BLOCK, ["low_identity"]
        if ic < R["identity_min"]:
            return OUT_REVIEW, ["identity"]
        return OUT_ALLOW, []

    # DTI / LTV are checked before credit because DTI comp-factor + LTV+state
    # scenarios also carry a credit_score; the present rule key selects the test.
    if "dti" in s:
        d = s["dti"]
        if d < 0:
            return OUT_BLOCK, ["data_error"]
        if d > 100 or d > DU_DTI_MAX:
            return OUT_BLOCK, []
        if d > R["dti_max"]:
            if s.get("credit_score", 0) >= 720 and s.get("reserves_months", 0) >= 12:
                return OUT_ALLOW, ["compensating", "Non-QM"]
            if s.get("credit_score", 0) >= 720:
                return OUT_ALLOW_IF, ["compensating", "Non-QM"]
            return OUT_BLOCK, ["exceeds_dti"]
        if d >= R["dti_review_low"]:
            return OUT_REVIEW, (["QM"] if d <= QM_DTI else ["Non-QM"])
        return OUT_ALLOW, ["QM"]

    if "ltv" in s:
        l = s["ltv"]
        lt = s.get("loan_type", "conventional")
        if l < 0:
            return OUT_BLOCK, ["data_error"]
        if s.get("state") == "TX" and s.get("loan_purpose") == "cash_out" and l > TX_CASHOUT_LTV:
            return OUT_BLOCK, ["TX_cashout"]
        if lt == "va":
            return (OUT_ALLOW, ["VA"]) if l <= VA_LTV_MAX else (OUT_BLOCK, [])
        cap = FHA_LTV_MAX if lt == "fha" else CONV_LTV_MAX
        if l > cap or l > R["ltv_max"]:
            return OUT_BLOCK, []
        return (OUT_ALLOW, ["MI"]) if l > R["ltv_no_mi"] else (OUT_ALLOW, [])

    if "credit_score" in s:
        cs = s["credit_score"]
        lt = s.get("loan_type", "conventional")
        if cs is None:
            return OUT_BLOCK, ["no_score"]
        if lt == "fha":
            floor = FHA_ABS_MIN if s.get("down_payment_pct", 3.5) >= 10 else FHA_MIN_3_5
        else:
            floor = max(CONV_MIN, R["credit_min"])
        return (OUT_BLOCK, []) if cs < floor else (OUT_ALLOW, [])

    if "income_gap" in s:
        g = s["income_gap"]
        if g > R["income_max_gap"]:
            return OUT_BLOCK, []
        if g >= R["income_review_low"]:
            return OUT_REVIEW, []
        return OUT_ALLOW, []

    if "reserves_months" in s:
        req = R["reserves_investment"] if s.get("investment") else R["reserves_primary"]
        if s["reserves_months"] < req:
            return (OUT_BLOCK, []) if s.get("investment") else (OUT_REVIEW, [])
        return OUT_ALLOW, []

    if "rate" in s:
        return (OUT_BLOCK, ["usury"]) if (s.get("state") == "NY" and s["rate"] > NY_USURY) else (OUT_ALLOW, [])
    if "mlds" in s:
        return (OUT_BLOCK, ["disclosure"]) if (s.get("state") == "CA" and not s["mlds"]) else (OUT_ALLOW, [])

    return OUT_ALLOW, []


# ── Test-case generators (expected = documented behavior, set of outcomes) ──
def _c(idx, cat, desc, inp, expected, label):
    return TestCase(f"{cat}-{idx:03d}", cat, desc, inp, set(expected), label)


def _dti_expect(dti, R, credit=0, reserves=0):
    """Documented DTI outcome (independent of evaluate), adaptive to the tenant.

    < review-band-low → allow; in band, ≤ tenant max → review; over tenant max but
    ≤ DU 50 → comp-factor path (allow_if / allow with strong reserves) else block;
    > 50 or invalid → block."""
    if dti < 0 or dti > 100 or dti > DU_DTI_MAX:
        return {OUT_BLOCK}, "block"
    if dti > R["dti_max"]:
        if credit >= 720 and reserves >= 12:
            return {OUT_ALLOW}, "allow"
        if credit >= 720:
            return {OUT_ALLOW_IF, OUT_ALLOW}, "allow_if"
        return {OUT_BLOCK}, "block"
    if dti >= R["dti_review_low"]:
        return {OUT_REVIEW}, "review"
    return {OUT_ALLOW}, "allow"


def _dc(idx, cat, desc, inp, R):
    """A DTI-family case whose expectation is derived from the documented model."""
    exp, label = _dti_expect(inp["dti"], R, inp.get("credit_score", 0), inp.get("reserves_months", 0))
    return TestCase(f"{cat}-{idx:03d}", cat, desc, inp, exp, label)


def gen_credit(R):
    f = R["credit_min"]
    return [
        _c(1, "credit", f"Credit at tenant floor ({f})", {"credit_score": f, "loan_type": "conventional"}, [OUT_ALLOW], "allow"),
        _c(2, "credit", f"Credit just below tenant floor ({f - 1})", {"credit_score": f - 1, "loan_type": "conventional"}, [OUT_BLOCK], "block"),
        _c(3, "credit", f"Credit above tenant floor ({f + 1})", {"credit_score": f + 1, "loan_type": "conventional"}, [OUT_ALLOW], "allow"),
        _c(4, "credit", "Conventional below Fannie min (619)", {"credit_score": 619, "loan_type": "conventional"}, [OUT_BLOCK], "block"),
        _c(5, "credit", "Conventional at Fannie min (620)", {"credit_score": 620, "loan_type": "conventional"}, ([OUT_ALLOW] if f <= 620 else [OUT_BLOCK]), "allow" if f <= 620 else "block"),
        _c(6, "credit", "FHA below 3.5%-down min (579)", {"credit_score": 579, "loan_type": "fha"}, [OUT_BLOCK], "block"),
        _c(7, "credit", "FHA at 3.5%-down min (580)", {"credit_score": 580, "loan_type": "fha"}, [OUT_ALLOW], "allow"),
        _c(8, "credit", "FHA below absolute min (499, 10% down)", {"credit_score": 499, "loan_type": "fha", "down_payment_pct": 10}, [OUT_BLOCK], "block"),
        _c(9, "credit", "FHA at absolute min (500, 10% down)", {"credit_score": 500, "loan_type": "fha", "down_payment_pct": 10}, [OUT_ALLOW], "allow"),
        _c(10, "credit", "Credit zero", {"credit_score": 0, "loan_type": "conventional"}, [OUT_BLOCK], "block"),
        _c(11, "credit", "Credit 300 (floor of scale)", {"credit_score": 300, "loan_type": "conventional"}, [OUT_BLOCK], "block"),
        _c(12, "credit", "Credit 850 (max)", {"credit_score": 850, "loan_type": "conventional"}, [OUT_ALLOW], "allow"),
        _c(13, "credit", "Credit missing / null", {"credit_score": None, "loan_type": "conventional"}, [OUT_BLOCK], "block"),
        _c(14, "credit", "Credit 740 (excellent)", {"credit_score": 740, "loan_type": "conventional"}, [OUT_ALLOW], "allow"),
    ]


def gen_dti(R):
    rl, mx = R["dti_review_low"], R["dti_max"]
    return [
        _dc(1, "dti", "DTI zero", {"dti": 0, "credit_score": 700}, R),
        _dc(2, "dti", f"DTI below review band ({round(rl - 0.1, 1)}%)", {"dti": rl - 0.1, "credit_score": 700}, R),
        _dc(3, "dti", f"DTI at review-band start ({rl}%)", {"dti": rl, "credit_score": 700}, R),
        _dc(4, "dti", f"DTI just below tenant max ({round(mx - 0.1, 1)}%)", {"dti": mx - 0.1, "credit_score": 700}, R),
        _dc(5, "dti", f"DTI at tenant max ({mx}%)", {"dti": mx, "credit_score": 700}, R),
        _dc(6, "dti", f"DTI just over tenant max, no comp ({round(mx + 0.1, 1)}%)", {"dti": mx + 0.1, "credit_score": 650}, R),
        _dc(7, "dti", f"DTI over max with strong credit ({round(min(mx + 1, DU_DTI_MAX), 1)}%, 725)", {"dti": min(mx + 1, DU_DTI_MAX), "credit_score": 725}, R),
        _dc(8, "dti", "DTI 44% with comp factors (725, 12mo reserves)", {"dti": 44, "credit_score": 725, "reserves_months": 12}, R),
        _dc(9, "dti", "DTI at Fannie DU max, no comp (50%)", {"dti": 50, "credit_score": 650}, R),
        _dc(10, "dti", "DTI above Fannie DU max (50.1%)", {"dti": 50.1, "credit_score": 760}, R),
        _dc(11, "dti", "DTI extreme (100%)", {"dti": 100, "credit_score": 700}, R),
        _dc(12, "dti", "DTI negative (data error)", {"dti": -5, "credit_score": 700}, R),
        _dc(13, "dti", f"DTI mid review band ({round((rl + mx) / 2, 1)}%)", {"dti": round((rl + mx) / 2, 1), "credit_score": 700}, R),
        _dc(14, "dti", f"DTI clean pass ({max(0, rl - 6)}%)", {"dti": max(0, rl - 6), "credit_score": 700}, R),
        _dc(15, "dti", "DTI 47% strong file (760, 12mo)", {"dti": 47, "credit_score": 760, "reserves_months": 12}, R),
    ]


def gen_ltv(R):
    mx, nomi = R["ltv_max"], R["ltv_no_mi"]
    return [
        _c(1, "ltv", f"LTV below no-MI threshold ({round(nomi - 0.1, 1)}%)", {"ltv": nomi - 0.1, "loan_type": "conventional"}, [OUT_ALLOW], "allow"),
        _c(2, "ltv", f"LTV at no-MI threshold ({nomi}%)", {"ltv": nomi, "loan_type": "conventional"}, [OUT_ALLOW], "allow"),
        _c(3, "ltv", f"LTV above no-MI threshold ({round(nomi + 0.1, 1)}%, MI)", {"ltv": nomi + 0.1, "loan_type": "conventional"}, [OUT_ALLOW], "allow+MI"),
        _c(4, "ltv", f"LTV just below tenant max ({round(mx - 0.1, 1)}%)", {"ltv": mx - 0.1, "loan_type": "conventional"}, [OUT_ALLOW], "allow"),
        _c(5, "ltv", f"LTV at tenant max ({mx}%)", {"ltv": mx, "loan_type": "conventional"}, [OUT_ALLOW], "allow"),
        _c(6, "ltv", f"LTV above tenant max ({round(mx + 0.1, 1)}%)", {"ltv": mx + 0.1, "loan_type": "conventional"}, [OUT_BLOCK], "block"),
        _c(7, "ltv", "Conventional above Fannie max (97.1%)", {"ltv": 97.1, "loan_type": "conventional"}, [OUT_BLOCK], "block"),
        _c(8, "ltv", "FHA above tenant max (96.6%)", {"ltv": 96.6, "loan_type": "fha"}, [OUT_BLOCK], "block"),
        _c(9, "ltv", "VA 100% (full financing)", {"ltv": 100, "loan_type": "va"}, [OUT_ALLOW], "allow"),
        _c(10, "ltv", "VA above 100% (100.1%)", {"ltv": 100.1, "loan_type": "va"}, [OUT_BLOCK], "block"),
        _c(11, "ltv", "TX cash-out at 79.9% LTV", {"ltv": 79.9, "loan_type": "conventional", "state": "TX", "loan_purpose": "cash_out"}, [OUT_ALLOW], "allow"),
        _c(12, "ltv", "TX cash-out above 80% LTV (80.1%)", {"ltv": 80.1, "loan_type": "conventional", "state": "TX", "loan_purpose": "cash_out"}, [OUT_BLOCK], "block"),
        _c(13, "ltv", "LTV negative (data error)", {"ltv": -10, "loan_type": "conventional"}, [OUT_BLOCK], "block"),
        _c(14, "ltv", "LTV 60% (strong equity)", {"ltv": 60, "loan_type": "conventional"}, [OUT_ALLOW], "allow"),
    ]


def gen_fraud(R):
    wt, im = R["watchlist"], R["identity_min"]
    return [
        _c(1, "fraud", "Watchlist score zero (no match)", {"watchlist_score": 0.0}, [OUT_ALLOW], "allow"),
        _c(2, "fraud", f"Watchlist just below threshold ({round(wt - 0.01, 2)})", {"watchlist_score": round(wt - 0.01, 2)}, [OUT_ALLOW], "allow"),
        _c(3, "fraud", f"Watchlist at threshold ({wt})", {"watchlist_score": wt}, [OUT_BLOCK], "block"),
        _c(4, "fraud", f"Watchlist above threshold ({round(wt + 0.01, 2)})", {"watchlist_score": round(wt + 0.01, 2)}, [OUT_BLOCK], "block"),
        _c(5, "fraud", "Watchlist 0.78 (SAR flag)", {"watchlist_score": 0.78}, [OUT_BLOCK], "block+SAR"),
        _c(6, "fraud", "Watchlist 1.00 (certain match)", {"watchlist_score": 1.0}, [OUT_BLOCK], "block+SAR"),
        _c(7, "fraud", f"Identity just below confidence ({round(im - 0.01, 2)})", {"identity_confidence": round(im - 0.01, 2)}, [OUT_REVIEW], "review"),
        _c(8, "fraud", f"Identity at confidence ({im})", {"identity_confidence": im}, [OUT_ALLOW], "allow"),
        _c(9, "fraud", "Identity very low (0.50)", {"identity_confidence": 0.50}, [OUT_BLOCK], "block"),
        _c(10, "fraud", "OFAC match (always blocks)", {"ofac_match": True}, [OUT_BLOCK], "block"),
        _c(11, "fraud", "OFAC clear", {"watchlist_score": 0.0}, [OUT_ALLOW], "allow"),
    ]


def gen_income(R):
    mg, rl = R["income_max_gap"], R["income_review_low"]
    return [
        _c(1, "income", "Income gap 0% (perfect match)", {"income_gap": 0}, [OUT_ALLOW], "allow"),
        _c(2, "income", f"Income gap below review band ({rl - 1}%)", {"income_gap": rl - 1}, [OUT_ALLOW], "allow"),
        _c(3, "income", f"Income gap at review band start ({rl}%)", {"income_gap": rl}, [OUT_REVIEW], "review"),
        _c(4, "income", f"Income gap just below max ({mg - 1}%)", {"income_gap": mg - 1}, [OUT_REVIEW], "review"),
        _c(5, "income", f"Income gap at max ({mg}%)", {"income_gap": mg}, [OUT_REVIEW], "review"),
        _c(6, "income", f"Income gap above max ({mg + 1}%)", {"income_gap": mg + 1}, [OUT_BLOCK], "block"),
        _c(7, "income", "Income gap 50% (severe)", {"income_gap": 50}, [OUT_BLOCK], "block"),
        _c(8, "income", f"Income gap clean ({max(0, rl - 5)}%)", {"income_gap": max(0, rl - 5)}, [OUT_ALLOW], "allow"),
        _c(9, "income", f"Income gap mid review band ({round((rl + mg) / 2)}%)", {"income_gap": round((rl + mg) / 2)}, ([OUT_REVIEW] if round((rl + mg) / 2) <= mg else [OUT_BLOCK]), "review"),
        _c(10, "income", f"Income gap blocked ({mg + 12}%)", {"income_gap": mg + 12}, [OUT_BLOCK], "block"),
    ]


def gen_reserves(R):
    p, i = R["reserves_primary"], R["reserves_investment"]
    return [
        _c(1, "reserves", f"Primary below requirement ({p - 1}mo)", {"reserves_months": p - 1, "investment": False}, [OUT_REVIEW], "review"),
        _c(2, "reserves", f"Primary at requirement ({p}mo)", {"reserves_months": p, "investment": False}, [OUT_ALLOW], "allow"),
        _c(3, "reserves", f"Primary above requirement ({p + 1}mo)", {"reserves_months": p + 1, "investment": False}, [OUT_ALLOW], "allow"),
        _c(4, "reserves", "Primary zero reserves", {"reserves_months": 0, "investment": False}, ([OUT_REVIEW] if p > 0 else [OUT_ALLOW]), "review" if p > 0 else "allow"),
        _c(5, "reserves", f"Investment below requirement ({i - 1}mo)", {"reserves_months": i - 1, "investment": True}, [OUT_BLOCK], "block"),
        _c(6, "reserves", f"Investment at requirement ({i}mo)", {"reserves_months": i, "investment": True}, [OUT_ALLOW], "allow"),
        _c(7, "reserves", f"Investment above requirement ({i + 1}mo)", {"reserves_months": i + 1, "investment": True}, [OUT_ALLOW], "allow"),
        _c(8, "reserves", "Investment zero reserves", {"reserves_months": 0, "investment": True}, [OUT_BLOCK], "block"),
    ]


def gen_conditional(R):
    mx = R["dti_max"]
    over1 = min(mx + 1, DU_DTI_MAX + 2)
    return [
        _dc(1, "conditional", f"DTI {over1}% + credit 725 (compensating)", {"dti": over1, "credit_score": 725}, R),
        _dc(2, "conditional", f"DTI {over1}% + credit 650 (no comp)", {"dti": over1, "credit_score": 650}, R),
        _dc(3, "conditional", f"DTI {over1}% + credit 725 + 12mo reserves (strong)", {"dti": over1, "credit_score": 725, "reserves_months": 12}, R),
        _dc(4, "conditional", "DTI 48% + credit 760 + 12mo (strong comp)", {"dti": 48, "credit_score": 760, "reserves_months": 12}, R),
        _dc(5, "conditional", "DTI 52% even with strong file (>DU max)", {"dti": 52, "credit_score": 780, "reserves_months": 12}, R),
        _dc(6, "conditional", f"DTI {min(mx + 2, 49)}% + credit 700 (insufficient comp)", {"dti": min(mx + 2, 49), "credit_score": 700}, R),
        _dc(7, "conditional", f"DTI {round(mx + 0.5, 1)}% + credit 730 (borderline comp)", {"dti": mx + 0.5, "credit_score": 730}, R),
        _dc(8, "conditional", "DTI 49% + credit 720 + 12mo", {"dti": 49, "credit_score": 720, "reserves_months": 12}, R),
        _dc(9, "conditional", f"DTI {min(mx + 3, 49)}% + credit 715 (under comp bar)", {"dti": min(mx + 3, 49), "credit_score": 715}, R),
        _dc(10, "conditional", f"DTI {over1}% + credit 800 (comp)", {"dti": over1, "credit_score": 800}, R),
    ]


def gen_regulatory_floor(R):
    return [
        _c(1, "regulatory_floor", "Conventional 610 holds at Fannie 620", {"credit_score": 610, "loan_type": "conventional"}, [OUT_BLOCK], "block"),
        _c(2, "regulatory_floor", "Conventional 620 passes regulatory floor", {"credit_score": 620, "loan_type": "conventional"}, [OUT_BLOCK if R["credit_min"] > 620 else OUT_ALLOW], "block" if R["credit_min"] > 620 else "allow"),
        _c(3, "regulatory_floor", "FHA 570 holds at FHA 580", {"credit_score": 570, "loan_type": "fha"}, [OUT_BLOCK], "block"),
        _c(4, "regulatory_floor", "FHA 490 holds at absolute 500 (10% down)", {"credit_score": 490, "loan_type": "fha", "down_payment_pct": 10}, [OUT_BLOCK], "block"),
        _c(5, "regulatory_floor", "OFAC cannot be disabled — match blocks", {"ofac_match": True}, [OUT_BLOCK], "block"),
        _dc(6, "regulatory_floor", "DTI 50% at Fannie DU ceiling (no comp)", {"dti": 50, "credit_score": 650}, R),
        _dc(7, "regulatory_floor", "DTI 51% above all agency ceilings", {"dti": 51, "credit_score": 780}, R),
        _c(8, "regulatory_floor", "Conventional 600 holds at 620", {"credit_score": 600, "loan_type": "conventional"}, [OUT_BLOCK], "block"),
    ]


def gen_state(R):
    return [
        _c(1, "state_rules", "TX cash-out refi at 81% LTV", {"ltv": 81, "loan_type": "conventional", "state": "TX", "loan_purpose": "cash_out"}, [OUT_BLOCK], "block"),
        _c(2, "state_rules", "TX cash-out refi at 79% LTV", {"ltv": 79, "loan_type": "conventional", "state": "TX", "loan_purpose": "cash_out"}, [OUT_ALLOW], "allow"),
        _c(3, "state_rules", "NY rate 17% (above usury cap 16%)", {"rate": 17, "state": "NY"}, [OUT_BLOCK], "block"),
        _c(4, "state_rules", "NY rate 15% (under usury cap)", {"rate": 15, "state": "NY"}, [OUT_ALLOW], "allow"),
        _c(5, "state_rules", "NY rate 16% (at usury cap)", {"rate": 16, "state": "NY"}, [OUT_ALLOW], "allow"),
        _c(6, "state_rules", "CA without MLDS disclosure", {"mlds": False, "state": "CA"}, [OUT_BLOCK], "block"),
        _c(7, "state_rules", "CA with MLDS disclosure", {"mlds": True, "state": "CA"}, [OUT_ALLOW], "allow"),
        _c(8, "state_rules", "TX cash-out at exactly 80% LTV", {"ltv": 80, "loan_type": "conventional", "state": "TX", "loan_purpose": "cash_out"}, [OUT_ALLOW], "allow"),
    ]


def gen_interactions(R):
    rl, mx = R["dti_review_low"], R["dti_max"]
    return [
        _c(1, "interactions", "LTV 81% triggers MI requirement", {"ltv": 81, "loan_type": "conventional"}, [OUT_ALLOW], "allow+MI"),
        _c(2, "interactions", "LTV 80% no MI required", {"ltv": 80, "loan_type": "conventional"}, [OUT_ALLOW], "allow"),
        _dc(3, "interactions", "High credit (760) + DTI 49 + 12mo reserves (comp)", {"dti": 49, "credit_score": 760, "reserves_months": 12}, R),
        _dc(4, "interactions", f"Mid credit (660) + DTI at review-band start ({rl}%)", {"dti": rl, "credit_score": 660}, R),
        _c(5, "interactions", "LTV 98% conventional (above Fannie max)", {"ltv": 98, "loan_type": "conventional"}, [OUT_BLOCK], "block"),
        _dc(6, "interactions", f"DTI {round(min(mx + 1, DU_DTI_MAX), 1)} + credit 725 compensating path", {"dti": min(mx + 1, DU_DTI_MAX), "credit_score": 725}, R),
        _c(7, "interactions", "LTV 85 + MI required", {"ltv": 85, "loan_type": "conventional"}, [OUT_ALLOW], "allow+MI"),
        _dc(8, "interactions", "DTI 30 + credit 800 (clean)", {"dti": 30, "credit_score": 800}, R),
        _dc(9, "interactions", "DTI 50 + credit 700 (no comp, blocked)", {"dti": 50, "credit_score": 700}, R),
        _dc(10, "interactions", f"DTI just under tenant max ({round(mx - 1, 1)}%)", {"dti": mx - 1, "credit_score": 700}, R),
    ]


class RuleValidator:
    def __init__(self, tenant_id, tenant_rules, programs, rule_version=None):
        self.tenant_id = tenant_id
        self.rule_version = rule_version
        self.R = resolve(tenant_rules, programs)

    def generate_test_cases(self):
        R = self.R
        cases = []
        for g in (gen_credit, gen_dti, gen_ltv, gen_fraud, gen_income, gen_reserves,
                  gen_conditional, gen_regulatory_floor, gen_state, gen_interactions):
            cases.extend(g(R))
        return cases

    def _warnings(self):
        w = []
        if self.R["dti_max"] > QM_DTI:
            w.append({"id": "dti-qm-001", "severity": "warning",
                      "description": f"Tenant DTI max ({self.R['dti_max']}%) exceeds QM safe harbor (43%). "
                                     f"Loans 43.1-{self.R['dti_max']}% will be flagged as Non-QM."})
        missing_states = 50 - len(STATES_WITH_RULES)
        w.append({"id": "state-cov-001", "severity": "info",
                  "description": f"No state-specific rules configured for {missing_states} states."})
        return w

    def run_all(self):
        cases = self.generate_test_cases()
        results = []
        cat_totals = {}
        for case in cases:
            actual, flags = evaluate(case.input, self.R)
            passed = actual in case.expected
            results.append(TestResult(case.id, case.category, case.description, case.input,
                                      case.expected_label, actual, passed, flags))
            ct = cat_totals.setdefault(case.category, {"total": 0, "passed": 0, "failed": 0})
            ct["total"] += 1
            ct["passed" if passed else "failed"] += 1
        total = len(results)
        passed = sum(1 for r in results if r.passed)
        return {
            "tenant_id": self.tenant_id,
            "rule_version": self.rule_version,
            "total_tests": total,
            "passed": passed,
            "failed": total - passed,
            "categories": cat_totals,
            "warnings": self._warnings(),
            "tests": [{
                "id": r.id, "category": r.category, "description": r.description, "input": r.input,
                "expected": r.expected, "actual": r.actual, "passed": r.passed, "flags": r.flags,
            } for r in results],
        }
