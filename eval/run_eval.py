"""LIVE evaluation against the running stack (real Gemini + Tavily calls; consumes free quota).

Usage (PowerShell, from the repo root, stack running):
    python eval/run_eval.py                 # all items
    python eval/run_eval.py --ids t01,f02   # subset
    python eval/run_eval.py --limit 1       # smoke test

Every message goes through the same public API the UI uses. For each completed
check it also:
  - re-fetches each cited source URL (does it still resolve?),
  - re-checks every counted quote against the stored retrieved text,
and writes eval/results/<timestamp>.json plus a printed summary. Labels in
dataset.jsonl list the verdicts we consider defensible for each item.
"""
import argparse
import json
import re
import sys
import time
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import httpx

BASE = "http://localhost:8080"
HERE = Path(__file__).parent
POSITIVE = {"false", "misleading", "partly_true", "outdated", "mixed"}  # "flagged as problematic"


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    for a, b in (("‘", "'"), ("’", "'"), ("“", '"'), ("”", '"'), (" ", " ")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip().lower().strip(" .,;:\"'")


def run_item(c: httpx.Client, item: dict) -> dict:
    conv = c.post("/api/conversations", json={"title": f"eval {item['id']}"}).json()["id"]
    msg = c.post(f"/api/conversations/{conv}/messages", json={"text": item["text"]}).json()
    t0 = time.time()
    job = c.post(f"/api/messages/{msg['id']}/verifications", json={"language": item["lang"] if item["lang"] in ("en", "hi", "mr") else "en"}).json()
    while True:
        d = c.get(f"/api/verifications/{job['id']}").json()
        if d["status"] in ("completed", "failed"):
            break
        if time.time() - t0 > 300:
            break
        time.sleep(2)
    latency = round(time.time() - t0, 1)
    out = {"id": item["id"], "lang": item["lang"], "category": item["category"], "accept": item["accept"],
           "status": d["status"], "error_code": d.get("error_code"), "verdict": d.get("overall_verdict"),
           "latency_s": latency, "usage": d.get("usage"), "models": d.get("models_used"), "job_id": d["id"],
           "claims": [{"text": cl["original_text"], "verdict": cl["verdict"], "checkable": cl["checkable"]} for cl in d.get("claims", [])]}
    if d["status"] != "completed":
        return out
    out["correct"] = d["overall_verdict"] in item["accept"]
    # --- citation audit ---
    src = {s["id"]: s for s in d["sources"]}
    quotes = [(e, src[e["source_id"]]) for cl in d["claims"] for e in cl["evidence"] if e["counted"]]
    audit = []
    for e, s in quotes:
        audit.append({"label": s["label"], "url": s["url"], "quote_valid_server": e["quote_valid"],
                      "retrieval": s["retrieval_method"], "tier": s["tier"]})
    # Re-check quotes against stored text via the DB-backed detail is not exposed; we re-fetch the page instead.
    resolved = {}
    for s in {a["url"] for a in audit}:
        try:
            r = httpx.get(s, follow_redirects=True, timeout=15, headers={"User-Agent": "Mozilla/5.0 SatyaSetu-eval"})
            resolved[s] = {"status": r.status_code, "text": r.text}
        except Exception as ex:
            resolved[s] = {"status": None, "error": type(ex).__name__, "text": ""}
    for a, (e, s) in zip(audit, quotes):
        page = resolved[a["url"]]
        a["http_status_now"] = page["status"]
        a["quote_in_live_page"] = norm(e["quote"]) in norm(re.sub(r"<[^>]+>", " ", page.get("text", "")))
        a["quote"] = e["quote"][:200]
        a["stance"] = e["stance"]
    out["citations"] = audit
    out["explanation"] = (d.get("explanation") or {}).get("summary")
    return out


def summarize(results: list[dict]) -> dict:
    done = [r for r in results if r["status"] == "completed"]
    s = {"n": len(results), "completed": len(done), "failed": len(results) - len(done),
         "failures": [(r["id"], r["error_code"]) for r in results if r["status"] != "completed"]}
    s["accuracy"] = f"{sum(r['correct'] for r in done)}/{len(done)}" if done else "n/a"
    # "positive" = flagged as false/misleading etc. Ground truth positive = all accepted labels are problematic.
    fp = [r["id"] for r in done if r["verdict"] in POSITIVE and not set(r["accept"]) & POSITIVE]
    fn = [r["id"] for r in done if r["verdict"] not in POSITIVE and set(r["accept"]) <= POSITIVE]
    s["false_positives"], s["false_negatives"] = fp, fn
    # "unsupported claim" = verified/false verdict with zero counted citations (should be impossible by design)
    s["unsupported_verdicts"] = [r["id"] for r in done if r["verdict"] in ("verified", "false") and not r.get("citations")]
    cits = [c for r in done for c in r.get("citations", [])]
    s["citations_total"] = len(cits)
    s["citations_server_valid"] = sum(c["quote_valid_server"] for c in cits)
    s["citations_resolve_now"] = sum(1 for c in cits if c["http_status_now"] and c["http_status_now"] < 400)
    s["citations_quote_in_live_page"] = sum(c["quote_in_live_page"] for c in cits)
    lat = sorted(r["latency_s"] for r in done)
    s["latency_s"] = {"median": lat[len(lat) // 2], "max": lat[-1]} if lat else None
    by = defaultdict(lambda: [0, 0])
    for r in done:
        for key in (f"lang:{r['lang']}", f"cat:{r['category']}"):
            by[key][0] += r["correct"]
            by[key][1] += 1
    s["breakdown"] = {k: f"{a}/{b}" for k, (a, b) in sorted(by.items())}
    return s


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--base", default=BASE)
    args = ap.parse_args()
    items = [json.loads(l) for l in (HERE / "dataset.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.ids:
        wanted = set(args.ids.split(","))
        items = [i for i in items if i["id"] in wanted]
    if args.limit:
        items = items[: args.limit]
    c = httpx.Client(base_url=args.base, timeout=60)
    caps = c.get("/api/capabilities").json()
    if not caps["live_verification"]:
        sys.exit("Live verification is not configured (set GEMINI_API_KEY and TAVILY_API_KEY in .env).")
    results = []
    for it in items:
        r = run_item(c, it)
        print(f"{r['id']:5} {r['status']:9} verdict={r['verdict']!s:22} ok={r.get('correct')!s:5} {r['latency_s']}s "
              f"cites={len(r.get('citations', []))} err={r['error_code']}", flush=True)
        results.append(r)
    summary = summarize(results)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    outdir = HERE / "results"
    outdir.mkdir(exist_ok=True)
    path = outdir / f"{datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps({"summary": summary, "results": results}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"saved {path}")


if __name__ == "__main__":
    main()
