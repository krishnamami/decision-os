# Demo Recording Notes (PROMPT H)

Gotchas verified against the live deployment — read before recording.

## Where to record
- **`accordlend.com` is not live yet** (PROMPT G: nameservers not set at the
  registrar, cert still PENDING). Record against the live ALB URL instead:
  `http://accord-alb-588286075.us-east-1.elb.amazonaws.com`
  (same app, every feature works). Swap every `https://accordlend.com/...` in
  the guide for that host.

## Demo loan: APP-SC30-004 (Wayne Hart · $505K · fraud review)
- 12 decisions evaluated; fraud 0.82 → BSA referral; email `wayne@email.com`;
  loan# `LN-SC30-4`; TX property (state rules evaluated).
- **Rain-check badge:** APP-SC30-004 is NOT pinned by default. To make the
  Scene-3/Scene-6 "🔒 Pipeline protection / protected" badge appear, run:
  ```
  python scripts/demo_pin_sc30.py          # pin to v1 (protected vs current v3)
  python scripts/demo_pin_sc30.py --unpin  # restore afterwards
  ```
  (Currently PINNED for the demo — remember to `--unpin` when done.)
- **Citations (Scene 4):** LTV decision → `Selling Guide B2-1.2-01`; Fraud
  decision → `31 CFR Part 501` + `31 CFR 1020.320` (the OFAC/BSA cites are the
  2nd/3rd entries in the fraud decision's governed_by list).

## Scene 7 — Policy Studio "Preview Impact"
- **Use the CREDIT floor, not DTI.** Changing **credit floor 640 → 700 shows 5
  loans affected** (compelling). Changing **DTI → 40% shows 0 loans affected**
  (Summit's active book is already under 40%). 
- Floor enforcement still demos well: set credit `500` → hard error
  ("below FHA minimum of 580", since Summit runs FHA).

## Landing video (after recording)
- `VideoSection.tsx` auto-detects the video: if `frontend/public/accord_demo.mp4`
  exists it renders the `<video>` player; otherwise it shows the placeholder
  (no 404). The stale pre-rebuild video was removed, so the landing currently
  shows the placeholder.
- To go live: drop the recorded `accord_demo.mp4` (and a thumbnail
  `accord_demo_poster.jpg`) into `frontend/public/`, then `bash deploy/deploy.sh`.
