"""Wire state rules into vw_compliance_check_context + create vw_regulation_transparency.

Part 1: replace the hardcoded ``state_rules_passed = true`` default with real
evaluation against regulatory_rules WHERE state_code = the loan's property_state
(from URLA_1003). Adds ``applicable_state_rules`` (jsonb) and ``property_state``.

Part 2: create vw_regulation_transparency unioning federal + agency + state rules
for the admin transparency page.

Schema adaptations vs. the original spec (verified against the live DB):
  - entity_states.ltv is a PERCENT (e.g. 80.0), so the TX cash-out test is
    ``es.ltv > 80`` directly.
  - loan.loan_purpose uses 'refinance_cash_out' / 'heloc' (not 'cash_out' /
    'home_equity'), so the rules map onto those real values.

Idempotent (CREATE OR REPLACE VIEW). Safe to run multiple times.
"""
import asyncio
import os

from dotenv import load_dotenv

load_dotenv()


def _url() -> str:
    raw = os.environ["DATABASE_URL"]
    return raw.replace("+asyncpg", "").replace("postgresql+psycopg2", "postgresql")


COMPLIANCE_VIEW = """
CREATE OR REPLACE VIEW vw_compliance_check_context AS
SELECT
  es.application_id,
  es.tenant_id,
  (es.borrower ->> 'applicant_id') AS applicant_id,

  COALESCE(
    ((es.borrower -> 'compliance' ->> 'all_hmda_fields_complete'))::boolean,
    CASE WHEN es.completeness_pct >= 0.9 THEN true ELSE false END
  ) AS all_hmda_fields_complete,

  COALESCE(((es.borrower -> 'compliance' ->> 'no_fair_lending_flags'))::boolean, true)
    AS no_fair_lending_flags,

  -- STATE RULES — evaluated from regulatory_rules for this loan's property_state.
  COALESCE(
    ((es.borrower -> 'compliance' ->> 'state_rules_passed'))::boolean,
    CASE
      WHEN ps.property_state IS NULL THEN true
      WHEN NOT EXISTS (
        SELECT 1 FROM regulatory_rules rr
        WHERE rr.state_code = ps.property_state AND rr.is_active = true
      ) THEN true
      -- Cash-out LTV cap (e.g. TX §50(a)(6)): cash-out refi over the LTV cap → FAIL.
      WHEN EXISTS (
        SELECT 1 FROM regulatory_rules rr
        JOIN loan l ON l.application_id = es.application_id
        WHERE rr.state_code = ps.property_state AND rr.category = 'ltv' AND rr.is_active = true
          AND (rr.rule_value ->> 'loan_purpose') = 'cash_out'
          AND l.loan_purpose IN ('cash_out', 'refinance_cash_out')
          AND es.ltv > (rr.rule_value ->> 'value')::numeric
      ) THEN false
      -- Usury cap (e.g. NY §14-a): rate exceeds the state usury cap → FAIL.
      WHEN EXISTS (
        SELECT 1 FROM regulatory_rules rr
        JOIN loan l ON l.application_id = es.application_id
        WHERE rr.state_code = ps.property_state AND rr.category = 'rate' AND rr.is_active = true
          AND l.rate_exceeds_usury = true
      ) THEN false
      -- Home-equity cooling period (TX §50(a)(6)(M)): flag home-equity loans for
      -- the cooling-period workflow review → FAIL until acknowledged.
      WHEN EXISTS (
        SELECT 1 FROM regulatory_rules rr
        JOIN loan l ON l.application_id = es.application_id
        WHERE rr.state_code = ps.property_state
          AND rr.rule_name = 'Texas Home Equity Cooling Period' AND rr.is_active = true
          AND l.loan_purpose IN ('home_equity', 'heloc')
      ) THEN false
      ELSE true
    END
  ) AS state_rules_passed,

  COALESCE(((es.borrower -> 'compliance' ->> 'fair_lending_violation'))::boolean, false)
    AS fair_lending_violation,
  COALESCE(((es.borrower -> 'compliance' ->> 'missing_required_disclosures'))::boolean, false)
    AS missing_required_disclosures,
  COALESCE(((es.borrower -> 'compliance' ->> 'regulatory_ambiguity'))::boolean, false)
    AS regulatory_ambiguity,
  COALESCE(((es.borrower -> 'compliance' ->> 'mixed_jurisdiction'))::boolean, false)
    AS mixed_jurisdiction,
  COALESCE(((es.borrower -> 'compliance' ->> 'minor_data_gap'))::boolean, false)
    AS minor_data_gap,
  pa.program_id,
  ga.authority_name AS governing_authority,
  ga.loan_type_classification,
  es.status,
  es.completeness_pct,

  -- New columns (appended so CREATE OR REPLACE keeps existing column order):
  -- which state rules apply to this loan's property location, and the state.
  (
    SELECT jsonb_agg(jsonb_build_object(
      'rule_name', rr.rule_name,
      'citation', rr.citation,
      'state_code', rr.state_code,
      'category', rr.category,
      'display_value', rr.display_value,
      'description', rr.description
    ))
    FROM regulatory_rules rr
    WHERE rr.state_code = ps.property_state AND rr.is_active = true
  ) AS applicable_state_rules,

  ps.property_state

FROM entity_states es
LEFT JOIN LATERAL (
  SELECT di.extracted_fields ->> 'subject_property_state' AS property_state
  FROM document_index di
  WHERE di.application_id = es.application_id AND di.document_type = 'URLA_1003'
  LIMIT 1
) ps ON true
LEFT JOIN program_assignment pa ON pa.application_id::text = es.application_id::text
LEFT JOIN program pgm ON pgm.program_id::text = pa.program_id::text
LEFT JOIN governing_authority ga ON ga.governing_authority_id::text = pgm.governing_authority_id::text;
"""

TRANSPARENCY_VIEW = """
CREATE OR REPLACE VIEW vw_regulation_transparency AS
SELECT 'federal'::text AS layer, NULL::text AS state_code, rr.authority AS source,
       rr.rule_name, rr.display_value, rr.description, rr.citation, rr.effective_date,
       rr.updated_at AS last_refreshed, 'Accord compliance team'::text AS verified_by,
       rr.is_active, rr.category, rr.rule_id::text AS regulation_id
FROM regulatory_rules rr WHERE rr.state_code IS NULL
UNION ALL
SELECT 'agency'::text, NULL::text, ag.agency, ag.guideline_name, ag.display_value,
       ag.description, ag.citation, ag.effective_date, ag.updated_at, ag.verified_by,
       ag.is_active, ag.category, ag.guideline_id::text
FROM agency_guidelines ag
UNION ALL
SELECT 'state'::text, rr.state_code, rr.authority, rr.rule_name, rr.display_value,
       rr.description, rr.citation, rr.effective_date, rr.updated_at,
       'Accord compliance team'::text, rr.is_active, rr.category, rr.rule_id::text
FROM regulatory_rules rr WHERE rr.state_code IS NOT NULL;
"""


async def main() -> None:
    import asyncpg  # type: ignore

    conn = await asyncpg.connect(_url())
    try:
        await conn.execute(COMPLIANCE_VIEW)
        print("vw_compliance_check_context recreated with state rules")
        await conn.execute(TRANSPARENCY_VIEW)
        print("vw_regulation_transparency created")

        sample = await conn.fetchrow(
            "SELECT application_id, state_rules_passed, property_state, "
            "applicable_state_rules FROM vw_compliance_check_context "
            "WHERE property_state = 'TX' LIMIT 1"
        )
        if sample:
            print(f"TX sample: passed={sample['state_rules_passed']}, "
                  f"state={sample['property_state']}, "
                  f"rules={'set' if sample['applicable_state_rules'] else 'none'}")

        counts = await conn.fetch(
            "SELECT state_rules_passed, COUNT(*) c FROM vw_compliance_check_context "
            "GROUP BY state_rules_passed ORDER BY state_rules_passed"
        )
        for r in counts:
            print(f"  state_rules_passed={r['state_rules_passed']}: {r['c']} loans")

        tcounts = await conn.fetch(
            "SELECT layer, COUNT(*) c FROM vw_regulation_transparency GROUP BY layer ORDER BY layer"
        )
        print("transparency view:", {r["layer"]: r["c"] for r in tcounts})
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
