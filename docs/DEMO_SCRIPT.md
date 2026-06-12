# Accord — Demo Recording Script

A 2-minute walkthrough that takes a viewer from the landing page to a finished,
audited decision. Everything below runs against the **live ALB** with the real
seeded data — no mockups.

> **Live URL:** http://accord-alb-588286075.us-east-1.elb.amazonaws.com

---

## Setup

| | |
|---|---|
| **Login** | `processor1@summit.com` / `accord2026` |
| **Browser** | Chrome, full screen, **1920×1080** |
| **Recorder** | [Loom](https://www.loom.com) (free) or OBS |
| **Tabs** | Close all other tabs; hide the bookmarks bar |
| **Data** | Run `python scripts/demo_data_check.py` first — wait for **✅ Demo data ready** |

**Demo helpers (admin login):** sign in as `admin@summit.com` and open
`/demo` for a control panel of bookmarkable moments. Each link jumps straight
to the real page with a subtle **DEMO** watermark on. Use these to rehearse or
to jump between takes:

| Moment | URL |
|---|---|
| Mike's queue | `/demo/queue` |
| Fraud-blocked loan | `/demo/loan/APP-SC02-004` |
| MiroFish debate | `/demo/debate` |
| Policy simulator | `/demo/simulate` |
| Portfolio health check | `/demo/swarm` |
| Audit trail | `/demo/audit` |

Toggle the watermark off from the pill in the bottom-right corner (`exit`)
before recording the *clean* take if you don't want it on camera.

---

## Recording script (2 minutes)

### `[0:00 – 0:10]` Landing page
- **Action:** Open the ALB URL (not logged in).
- **Show:** Hero animation plays; scroll slowly past the stats.
- **Say:** *"This is Accord — AI-powered lending decisions."*

### `[0:10 – 0:25]` Login → My Queue
- **Action:** Click **Log in**, enter the credentials, submit.
- **Show:** My Queue loads with a greeting and 3 loans.
- **Say:** *"When Mike logs in, he sees his queue — just the loans that need HIS
  attention right now."*

### `[0:25 – 0:45]` Fraud-blocked loan
- **Action:** Click the fraud-blocked loan (Mark Singh).
- **Show:** Summary card → **"Why it's blocked"** → **"Everything else passed."**
- **Say:** *"The AI found a watchlist match at 78% confidence. Notice it tells
  Mike exactly what's wrong AND what's fine. The credit and income are clean —
  it's an identity question."*

### `[0:45 – 1:00]` Take action
- **Action:** Click **Refer to BSA officer**.
- **Show:** Confirmation page with **"What happens next."**
- **Say:** *"One click. The loan goes to compliance. Mike gets notified when they
  review it. Full audit trail."*

### `[1:00 – 1:20]` MiroFish debate
- **Action:** Navigate to **Simulation → Debate**, select a loan, show the
  pre-run results.
- **Show:** Consensus card, vote bar, insights, full debate rounds.
- **Say:** *"MiroFish: 12 AI agents debate a loan in 3 rounds. They share
  findings, change positions, reach consensus. Insights that no single review
  would catch."*

### `[1:20 – 1:35]` Policy simulator
- **Action:** Open the **DTI** dropdown → select **36%** → show pre-run results.
- **Show:** *"3 loans affected, $1.5M impact"* + affected-loan detail.
- **Say:** *"What if we tighten DTI? The simulator shows exactly who's affected,
  why, and what alternatives exist — BEFORE you change the policy."*

### `[1:35 – 1:50]` Portfolio health check
- **Action:** Show the pre-run health-check results.
- **Show:** Severity-grouped findings.
- **Say:** *"The health check scans all 8,896 loans. It found 46% have income
  gaps — a systematic problem that no individual file review would catch."*

### `[1:50 – 2:00]` Closing
- **Action:** Show the audit trail briefly, then return to the landing page.
- **Say:** *"Every decision documented. Every action traced. Accord. Every
  decision, in accord."*

---

## Tips
- Pause **1–2 seconds** between clicks — give the viewer time to read.
- Don't rush the screens.
- Consistent, calm voice; record in a quiet room.
- Do **2–3 takes** and pick the best.
- Trim dead air in Loom's editor.

---

## Note on roles
The narration walks through **Simulation** (debate / policy simulator / health
check). Those products require an underwriting role — `processor` only has the
pipeline. For a single continuous take, record as a role with Simulation access
(e.g. `senioruw@summit.com` / `accord2026`, or impersonate from an admin via
**View as**), or split the recording: the queue + loan + action beats as Mike,
the Simulation beats as a senior underwriter.
