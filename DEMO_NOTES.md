# Demo Recording Notes

> Record against the live ALB URL — `accordlend.com` is not live yet (DNS/SSL
> pending the registrar nameserver change). Same app, every feature works:
> `http://accord-alb-588286075.us-east-1.elb.amazonaws.com`

## Scene 7 — Policy Studio

USE: Change credit floor 640 → 700
Shows: "5 loans affected" in Preview Impact panel

DO NOT USE: Change DTI 43 → 40
Shows: "0 loans affected" (not compelling)

Floor enforcement demo:
→ Type credit score: 500
→ Shows hard error: "Cannot go below FHA minimum of 580"
→ This demonstrates the agency floor protection

## Rain check badge

APP-SC30-004 is pinned to rule v1 (current is v3).
Badge shows: "Pipeline protection — evaluated under Rule v1.
Rules updated since lock — this loan is protected."

(Pin/restore helper: `python scripts/demo_pin_sc30.py` / `--unpin`)

## To undo pin after recording

UPDATE entity_states
SET pinned_rule_version = NULL, pinned_at = NULL, rate_locked = false
WHERE application_id = 'APP-SC30-004';
