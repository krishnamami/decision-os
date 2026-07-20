
async def load_fraud_rules(conn, tenant_id: str) -> dict:
    """Load fraud scoring thresholds from tenant overlay_rules."""
    row = await conn.fetchrow("""
        SELECT overlay_value FROM overlay_rules
        WHERE tenant_id = $1 AND rule_type = 'fraud_score_threshold'
        AND is_active = true
        LIMIT 1
    """, tenant_id)
    threshold = float(row['overlay_value']) if row else 0.70
    return {
        "fraud_score_threshold": threshold,
        "watchlist_auto_block": True,
        "synthetic_identity_auto_block": True,
    }
