# scripts/catalogue/refresh_fannie_guidelines.py
"""
Fannie Mae Selling Guide Rule Downloader.

Downloads Fannie Mae Selling Guide sections,
extracts structured rules using Claude,
loads directly into agency_guidelines using
Type 2 SCD versioning.

TYPE 2 SCD:
  Each rule has valid_from / valid_to.
  valid_to = NULL means this is current.
  When a rule value changes:
    Old row: valid_to = yesterday (closed)
    New row: valid_from = today (current)
  When same value: no change (unchanged).
  Old versions never deleted — full history kept.

  Query current rules:
    WHERE valid_to IS NULL

  Query rules at a date:
    WHERE valid_from <= '2025-06-15'
    AND (valid_to IS NULL
         OR valid_to >= '2025-06-15')

Run:
  python scripts/catalogue/refresh_fannie_guidelines.py
  python scripts/catalogue/refresh_fannie_guidelines.py
      --section B3-4.3-04
  python scripts/catalogue/refresh_fannie_guidelines.py
      --show-history qualifying_factor_retirement
  python scripts/catalogue/refresh_fannie_guidelines.py
      --show-current
"""

import asyncio
import argparse
import json
import os
import re
from datetime import date, timedelta
from typing import Optional

import httpx
import anthropic
from dotenv import load_dotenv
load_dotenv()


SECTIONS = {
    'B3-4.3-04': {
        'url': 'https://selling-guide.fanniemae.com'
               '/sel/b3/4.3/04',
        'category': 'asset',
        'desc': 'Asset qualification factors',
    },
    'B3-5.3-07': {
        'url': 'https://selling-guide.fanniemae.com'
               '/sel/b3/5.3/07',
        'category': 'credit',
        'desc': 'Credit waiting periods',
    },
    'B3-6-05': {
        'url': 'https://selling-guide.fanniemae.com'
               '/sel/b3/6/05',
        'category': 'income',
        'desc': 'Student loan treatment',
    },
    'B3-3.1-08': {
        'url': 'https://selling-guide.fanniemae.com'
               '/sel/b3/3.1/08',
        'category': 'income',
        'desc': 'Rental income / vacancy factor',
    },
    'B3-3.4-01': {
        'url': 'https://selling-guide.fanniemae.com'
               '/sel/b3/3.4/01',
        'category': 'income',
        'desc': 'Self-employed income',
    },
    'B2-1.3-01': {
        'url': 'https://selling-guide.fanniemae.com'
               '/sel/b2/1.3/01',
        'category': 'property',
        'desc': 'Ineligible property types',
    },
    'B7-3-02': {
        'url': 'https://selling-guide.fanniemae.com'
               '/sel/b7/3/02',
        'category': 'property',
        'desc': 'Flood zone insurance',
    },
    'B3-3.1-01': {
        'url': 'https://selling-guide.fanniemae.com'
               '/sel/b3/3.1/01',
        'category': 'income',
        'desc': 'Income / DTI requirements',
    },
    'B4-2.1-01': {
        'url': 'https://selling-guide.fanniemae.com'
               '/sel/b4/2.1/01',
        'category': 'property',
        'desc': 'Condo warrantability',
    },
    'B4-1.1-01': {
        'url': 'https://selling-guide.fanniemae.com'
               '/sel/b4/1.1/01',
        'category': 'property',
        'desc': 'Appraisal and LTV',
    },
}


EXTRACTION_PROMPT = """
You are a mortgage underwriting expert.
Read this Fannie Mae Selling Guide section.
Extract ALL specific numeric thresholds,
percentages, time periods, lists, and
boolean eligibility rules.

Return ONLY a valid JSON array.
No preamble. No markdown. No explanation.

Each element:
{{
  "guideline_name": "snake_case_key",
  "guideline_value": <number|boolean|array>,
  "display_value": "human readable string",
  "description": "plain English explanation",
  "conditions": "any exceptions or empty string"
}}

Examples:
  "retirement accounts 60% of vested balance"
  -> guideline_name: qualifying_factor_retirement
  -> guideline_value: 0.60

  "4-year waiting period Chapter 7 bankruptcy"
  -> guideline_name: bankruptcy_ch7_waiting_years
  -> guideline_value: 4

  "25% vacancy factor for rental income"
  -> guideline_name: rental_vacancy_factor_pct
  -> guideline_value: 25

  "zones A, AE, AH, AO, V, VE require flood insurance"
  -> guideline_name: flood_zones_requiring_insurance
  -> guideline_value: ["A","AE","AH","AO","V","VE"]

  "crypto not eligible"
  -> guideline_name: qualifying_factor_crypto
  -> guideline_value: 0.0

  "minimum 2 months reserves"
  -> guideline_name: minimum_reserves_months
  -> guideline_value: 2

  "deposits exceeding 50% of qualifying income"
  -> guideline_name: large_deposit_threshold_pct
  -> guideline_value: 50

  "60-day seasoning requirement"
  -> guideline_name: seasoning_days_required
  -> guideline_value: 60

If nothing specific found -> return []

Citation: {citation}
Category: {category}

TEXT:
{text}
"""


async def fetch_section(
    section_id: str,
    info: dict,
) -> Optional[str]:
    """Download and clean a Selling Guide section."""
    print(f'  Fetching {section_id}: {info["url"]}')
    try:
        async with httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            headers={
                'User-Agent': 'AccordRulesBot/1.0'
            }
        ) as client:
            r = await client.get(info['url'])
            r.raise_for_status()
            text = r.text
            # Strip scripts and styles
            text = re.sub(
                r'<script[^>]*>.*?</script>',
                '', text, flags=re.DOTALL
            )
            text = re.sub(
                r'<style[^>]*>.*?</style>',
                '', text, flags=re.DOTALL
            )
            # Strip HTML tags
            text = re.sub(r'<[^>]+>', ' ', text)
            # Normalize whitespace
            text = re.sub(
                r'\s+', ' ', text
            ).strip()
            print(f'  Got {len(text)} chars')
            return text[:8000]
    except Exception as e:
        print(f'  FETCH ERROR: {type(e).__name__}: {e!r}')
        return None


def extract_rules(
    text: str,
    section_id: str,
    info: dict,
) -> list:
    """Extract structured rules from section text."""
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        print('  No ANTHROPIC_API_KEY — skip')
        return []

    client = anthropic.Anthropic(api_key=api_key)
    prompt = EXTRACTION_PROMPT.format(
        citation=f'Fannie Mae {section_id}',
        category=info['category'],
        text=text,
    )

    try:
        resp = client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=2000,
            messages=[{
                'role': 'user',
                'content': prompt,
            }]
        )
        raw = resp.content[0].text.strip()
        # Strip markdown fences if present
        if '```' in raw:
            parts = raw.split('```')
            raw = parts[1]
            if raw.startswith('json'):
                raw = raw[4:]
        rules = json.loads(raw.strip())
        print(f'  Extracted {len(rules)} rules')
        return rules
    except Exception as e:
        print(f'  EXTRACTION ERROR: {e}')
        return []


async def type2_upsert(
    conn,
    agency: str,
    category: str,
    section_id: str,
    rule: dict,
    source_url: str,
    today: date,
) -> str:
    """
    Type 2 SCD upsert into agency_guidelines.

    LOGIC:
      Find current row (valid_to IS NULL).
      Same value → skip (unchanged).
      Different value:
        Close current: valid_to = yesterday
        Insert new: valid_from = today
      No current row:
        Insert new: valid_from = today

    Returns: inserted | versioned | unchanged | skipped
    """
    name  = (rule.get('guideline_name') or '').strip()
    value = rule.get('guideline_value')

    if not name or value is None:
        return 'skipped'

    gv = json.dumps({
        'type':  'threshold',
        'value': value,
    })

    # Find current version
    current = await conn.fetchrow('''
        SELECT version_id, guideline_value, valid_from
        FROM agency_guidelines
        WHERE agency = $1
        AND guideline_name = $2
        AND valid_to IS NULL
        AND is_active = true
        ORDER BY valid_from DESC
        LIMIT 1
    ''', agency, name)

    if current:
        # Parse existing value for comparison
        existing = current['guideline_value']
        if isinstance(existing, str):
            try:
                existing = json.loads(existing)
            except Exception:
                pass
        existing_val = (
            existing.get('value')
            if isinstance(existing, dict)
            else existing
        )

        # Same value — no change needed
        if str(existing_val) == str(value):
            return 'unchanged'

        # Different value — Type 2 close old version. Clamp the close date so
        # it can never precede the row's own valid_from (which would invert the
        # interval and break point-in-time queries). This happens when a value
        # changes on the same day the prior version started.
        close_date = max(today - timedelta(days=1), current['valid_from'])
        await conn.execute('''
            UPDATE agency_guidelines
            SET valid_to   = $1,
                updated_at = NOW()
            WHERE version_id = $2
        ''', close_date, current['version_id'])

    # Insert new current version
    await conn.execute('''
        INSERT INTO agency_guidelines (
            agency, category,
            guideline_name, guideline_value,
            display_value, description,
            conditions, citation, source_url,
            valid_from, valid_to,
            downloaded_at, source_revision,
            last_verified, verified_by,
            is_active
        ) VALUES (
            $1,$2,$3,$4,$5,$6,
            $7,$8,$9,
            $10, NULL,
            NOW(),$11,
            CURRENT_DATE,'fannie_refresh',
            true
        )
    ''',
        agency,
        category,
        name,
        gv,
        rule.get('display_value', str(value)),
        rule.get('description', ''),
        rule.get('conditions', ''),
        f'Fannie Mae {section_id}',
        source_url,
        today,
        section_id,
    )

    return 'versioned' if current else 'inserted'


async def show_history(
    conn, guideline_name: str
):
    """Show full Type 2 history for a rule."""
    rows = await conn.fetch('''
        SELECT agency, guideline_name,
               guideline_value,
               valid_from, valid_to,
               version_id, downloaded_at,
               source_revision, citation
        FROM agency_guidelines
        WHERE guideline_name = $1
        ORDER BY agency, valid_from ASC
    ''', guideline_name)

    if not rows:
        print(f'No history for: {guideline_name}')
        return

    print(f'\nType 2 history: {guideline_name}')
    for r in rows:
        gv = r['guideline_value']
        if isinstance(gv, str):
            try: gv = json.loads(gv)
            except Exception: pass
        val = (
            gv.get('value')
            if isinstance(gv, dict)
            else gv
        )
        is_current = r['valid_to'] is None
        print(
            f'  [{r["agency"]}] '
            f'value={val} '
            f'valid={r["valid_from"]} -> '
            f'{r["valid_to"] or "present"} '
            f'{"<- CURRENT" if is_current else ""}'
        )
        print(
            f'    version_id: {r["version_id"]}'
        )
        print(
            f'    citation: {r["citation"]}'
        )
        print(
            f'    downloaded: {r["downloaded_at"]}'
        )


async def show_current(conn):
    """Show all current rules."""
    rows = await conn.fetch('''
        SELECT agency, category,
               guideline_name, guideline_value,
               valid_from, citation
        FROM agency_guidelines
        WHERE valid_to IS NULL
        AND is_active = true
        ORDER BY agency, category, guideline_name
    ''')
    total = len(rows)
    print(f'\nCurrent rules: {total}')
    cat = None
    for r in rows:
        key = f'{r["agency"]}/{r["category"]}'
        if key != cat:
            cat = key
            print(f'\n  [{cat}]')
        gv = r['guideline_value']
        if isinstance(gv, str):
            try: gv = json.loads(gv)
            except Exception: pass
        val = (
            gv.get('value')
            if isinstance(gv, dict)
            else gv
        )
        print(
            f'    {r["guideline_name"]}: {val} '
            f'(from {r["valid_from"]})'
        )


async def main():
    parser = argparse.ArgumentParser(
        description='Refresh Fannie Mae guidelines'
    )
    parser.add_argument(
        '--section', default=None,
        help='Single section e.g. B3-4.3-04'
    )
    parser.add_argument(
        '--show-history', default=None,
        metavar='RULE_NAME',
        help='Show version history for a rule'
    )
    parser.add_argument(
        '--show-current',
        action='store_true',
        help='Show all current rules'
    )
    args = parser.parse_args()

    import asyncpg
    url = os.environ['DATABASE_URL']\
        .replace('+asyncpg', '')\
        .replace('postgresql+psycopg2', 'postgresql')
    conn = await asyncpg.connect(url)

    try:
        # Apply migration first (idempotent)
        print('Applying versioning migration...')
        sql = open(
            'scripts/migrations/'
            'add_guideline_versioning.sql'
        ).read()
        await conn.execute(sql)
        print('Migration applied.')

        # Show commands
        if args.show_history:
            await show_history(
                conn, args.show_history
            )
            return

        if args.show_current:
            await show_current(conn)
            return

        # Download + extract + load.
        # Source "today" from the DB (CURRENT_DATE) rather than the local
        # process clock, so valid_from/valid_to stay consistent with the
        # migration's server-side defaults and the INSERT's CURRENT_DATE — a
        # local-vs-UTC skew would otherwise close a row with valid_to BEFORE
        # its valid_from and break point-in-time queries.
        today = await conn.fetchval('SELECT CURRENT_DATE')
        sections = (
            {
                args.section:
                SECTIONS[args.section]
            }
            if args.section
               and args.section in SECTIONS
            else SECTIONS
        )

        stats = {
            'inserted':  0,
            'versioned': 0,
            'unchanged': 0,
            'skipped':   0,
        }

        for sid, info in sections.items():
            print(
                f'\n── {sid}: '
                f'{info["desc"]} ──'
            )

            text = await fetch_section(sid, info)
            if not text:
                print('  Cannot fetch. Skipping.')
                continue

            rules = extract_rules(text, sid, info)
            if not rules:
                print('  No rules extracted.')
                continue

            for rule in rules:
                status = await type2_upsert(
                    conn, 'fannie',
                    info['category'],
                    sid, rule,
                    info['url'],
                    today,
                )
                stats[status] = (
                    stats.get(status, 0) + 1
                )
                n = rule.get('guideline_name')
                v = rule.get('guideline_value')
                print(f'  [{status}] {n} = {v}')

        # Summary
        print(f'\n── Summary ──')
        for k, v in stats.items():
            if v:
                print(f'  {k}: {v}')

        # Show final state
        await show_current(conn)

    finally:
        await conn.close()


if __name__ == '__main__':
    asyncio.run(main())
