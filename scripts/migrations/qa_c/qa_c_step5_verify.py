"""QA-C Step 5 — cross-tenant API verification against the live ALB.
Confirms each tenant admin sees ONLY their tenant via /api/accord/*.
MUST pass before the flip is declared successful. Exit 0 only if all pass."""
import json, urllib.request, urllib.error

BASE = "http://accord-alb-588286075.us-east-1.elb.amazonaws.com"


def _req(method, path, token=None, data=None):
    body = json.dumps(data).encode() if data is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(BASE + path, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or "null")
    except urllib.error.HTTPError as e:
        return e.code, None


def login(email, pwd):
    st, d = _req("POST", "/api/accord/auth/login", data={"email": email, "password": pwd})
    if st != 200 or not d or not d.get("access_token"):
        return None, None, st
    return d["access_token"], (d.get("user") or {}).get("tenant_id"), st


def app_ids(token):
    st, d = _req("GET", "/api/accord/pipeline?limit=500&offset=0", token=token)
    apps = (d or {}).get("applications") or []
    return st, (d or {}).get("total"), [a["application_id"] for a in apps]


def main():
    R = []
    ts, tt_s, sst = login("admin@summit.com", "accord2026")
    tm, tt_m, mst = login("admin@meridian.com", "accord2026")
    R.append(("both logins succeed", ts is not None and tm is not None,
              {"summit_status": sst, "meridian_status": mst}))
    if ts is None or tm is None:
        return report(R)
    R.append(("tenant claims correct (summit / meridian)",
              tt_s == "summit" and tt_m == "meridian",
              {"summit_tenant": tt_s, "meridian_tenant": tt_m}))
    ss, stot, s_ids = app_ids(ts)
    ms, mtot, m_ids = app_ids(tm)
    s_set, m_set = set(s_ids), set(m_ids)
    R.append(("summit list non-empty (no RLS blackout)", len(s_set) > 0,
              {"status": ss, "total": stot, "returned": len(s_set)}))
    R.append(("meridian list non-empty (no RLS blackout)", len(m_set) > 0,
              {"status": ms, "total": mtot, "returned": len(m_set)}))
    overlap = s_set & m_set
    R.append(("summit / meridian app-id sets disjoint", len(overlap) == 0,
              {"overlap_count": len(overlap), "overlap_sample": list(overlap)[:5]}))
    if m_ids:
        st1, _ = _req("GET", "/api/accord/loans/" + m_ids[0], token=ts)
        R.append(("summit token CANNOT read a meridian loan (403/404)",
                  st1 in (403, 404), {"status": st1, "target": m_ids[0]}))
    if s_ids:
        st2, _ = _req("GET", "/api/accord/loans/" + s_ids[0], token=tm)
        R.append(("meridian token CANNOT read a summit loan (403/404)",
                  st2 in (403, 404), {"status": st2, "target": s_ids[0]}))
        st3, _ = _req("GET", "/api/accord/loans/" + s_ids[0], token=ts)
        R.append(("positive control: summit token CAN read its own loan (200)",
                  st3 == 200, {"status": st3}))
    return report(R)


def report(R):
    print("===== CROSS-TENANT API VERIFICATION =====")
    for name, ok, detail in R:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}\n      {detail}")
    allok = all(o for _, o, _ in R)
    print("\nOVERALL:", "ALL PASS" if allok else "FAIL")
    if not allok:
        raise SystemExit(1)


main()
