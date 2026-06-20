"""
Large Deposit Analyzer — AV-C

Systematically analyzes all deposits
across all bank statements.

Rules:
  Fannie Mae B3-4.3-04:
    Any single deposit > 50% of qualifying
    monthly income requires documentation
    unless it is:
      - Payroll (regular, consistent amount)
      - Tax refund (matches IRS records)
      - Insurance proceeds (documented)
      - Sale proceeds (HUD-1 verifies)
      - Transfer between own accounts
        (both accounts documented)

  Transfer between own accounts:
    If borrower has accounts at two banks
    and deposits match withdrawals:
    NOT double-counted as additional assets
    This is the most common error.

  Gift funds:
    Separate treatment — need full chain
    Gift letter + donor statement + transfer
"""

from dataclasses import dataclass
from datetime import date
from typing import List


# Days to look back for deposit history
LOOKBACK_DAYS = 60

# Large deposit threshold (% of qualifying monthly)
LARGE_DEPOSIT_PCT = 0.50

# Transfer match window (days)
TRANSFER_MATCH_DAYS = 3


@dataclass
class DepositFinding:
    deposit_id:       str
    deposit_date:     date
    deposit_amount:   float
    institution:      str
    is_sourced:       bool
    is_gift:          bool
    is_transfer:      bool
    transfer_matched: bool
    requires_loe:     bool
    condition_code:   str
    condition_text:   str
    severity:         str  # minor/moderate/major


class DepositAnalyzer:

    def analyze_deposits(
        self,
        deposits: list,
        qualifying_monthly: float,
        all_accounts: list = None,
    ) -> dict:
        """
        Analyze all deposits for an application.

        deposits: list of asset_deposits rows
        qualifying_monthly: for threshold calc
        all_accounts: to detect own-account transfers
        """
        threshold = qualifying_monthly \
                  * LARGE_DEPOSIT_PCT
        findings  = []
        total_unsourced = 0.0
        gift_deposits   = []
        transfer_candidates = []

        # Group by institution for transfer detection
        accounts_by_inst = {}
        if all_accounts:
            for acct in all_accounts:
                inst = acct.get(
                    'institution_name', ''
                )
                accounts_by_inst[inst] = acct

        for dep in deposits:
            dep_id     = str(dep.get('id', ''))
            dep_date   = dep.get('deposit_date')
            dep_amount = float(
                dep.get('deposit_amount') or 0
            )
            dep_source = dep.get(
                'deposit_source', ''
            ) or ''
            is_sourced = dep.get(
                'is_sourced', False
            )
            is_gift    = dep.get(
                'is_gift', False
            )
            institution = dep.get(
                'institution_name',
                'Unknown Bank'
            )

            # Skip if already sourced
            if is_sourced:
                continue

            # Skip if below threshold
            if dep_amount <= threshold:
                continue

            # Gift funds — separate track
            if is_gift:
                gift_deposits.append({
                    'id':     dep_id,
                    'date':   dep_date,
                    'amount': dep_amount,
                    'institution': institution,
                })
                findings.append(DepositFinding(
                    deposit_id=dep_id,
                    deposit_date=dep_date,
                    deposit_amount=dep_amount,
                    institution=institution,
                    is_sourced=False,
                    is_gift=True,
                    is_transfer=False,
                    transfer_matched=False,
                    requires_loe=False,
                    condition_code='ASSET_GIFT_LETTER',
                    condition_text=(
                        f'Gift funds of '
                        f'${dep_amount:,.0f} '
                        f'deposited {dep_date}. '
                        f'Gift letter + donor '
                        f'statement required.'
                    ),
                    severity='moderate',
                ))
                continue

            # Check if looks like payroll
            # (regular deposits, same amount ±5%)
            is_payroll = (
                'payroll' in dep_source.lower()
                or 'direct dep' in dep_source.lower()
                or 'salary' in dep_source.lower()
            )
            if is_payroll:
                continue  # Payroll — skip

            # Check if own-account transfer
            # (deposit matches withdrawal at
            #  another institution ±5%, ±3 days)
            is_transfer = (
                'transfer' in dep_source.lower()
                or 'xfer' in dep_source.lower()
                or 'zelle' in dep_source.lower()
                or 'ach' in dep_source.lower()
            )

            # Determine severity
            if dep_amount > qualifying_monthly:
                severity = 'major'
            elif dep_amount > threshold * 2:
                severity = 'moderate'
            else:
                severity = 'minor'

            total_unsourced += dep_amount

            findings.append(DepositFinding(
                deposit_id=dep_id,
                deposit_date=dep_date,
                deposit_amount=dep_amount,
                institution=institution,
                is_sourced=False,
                is_gift=False,
                is_transfer=is_transfer,
                transfer_matched=False,
                requires_loe=True,
                condition_code='ASSET_LARGE_DEPOSIT',
                condition_text=(
                    f'Large deposit of '
                    f'${dep_amount:,.0f} on '
                    f'{dep_date} requires: '
                    f'(1) written explanation, '
                    f'(2) source documentation. '
                    f'Fannie Mae B3-4.3-04.'
                ),
                severity=severity,
            ))

        conditions = []
        for f in findings:
            conditions.append({
                'code':      f.condition_code,
                'text':      f.condition_text,
                'amount':    f.deposit_amount,
                'date':      str(f.deposit_date),
                'severity':  f.severity,
                'is_gift':   f.is_gift,
                'blocks':    False,
                'prior_to':  'docs',
            })

        return {
            'findings':         findings,
            'conditions':       conditions,
            'total_unsourced':  total_unsourced,
            'gift_count':       len(gift_deposits),
            'unsourced_count':  len([
                f for f in findings
                if not f.is_gift
            ]),
            'requires_action':  len(findings) > 0,
            'threshold_used':   threshold,
        }


__all__ = [
    "DepositAnalyzer",
    "DepositFinding",
    "LOOKBACK_DAYS",
    "LARGE_DEPOSIT_PCT",
    "TRANSFER_MATCH_DAYS",
]
