# Evaluation & readiness

Status as of 2026-10-10. Nothing below claims verification quality that has not been measured.

## Live-provider validation: run 1 (2026-10-10), PARTIAL
Report: `eval/results/20261010-153644.json` (kept locally, not committed). Real Gemini + Tavily, through the public API.

| Metric | Measured |
|---|---|
| Completed | 20 / 24 (all English). 4 failed: hi01, hi02, mr01, mr02 - `rate_limited` by SatyaSetu's own 8/min limiter (cause and fix below) |
| Verdict accuracy (accepted labels) | 19 / 20. Miss: t03 "RBI established in 1935" -> conflicting (cause and fix below) |
| False positives / false negatives | 0 / 0 on the 20 completed |
| Verified/false verdicts without counted citations | 0 |
| Counted quotations | 94; 94 valid per server; 94 re-confirmed against the page text stored in Postgres |
| Quotes found on the live page when re-fetched afterwards | 54 / 94 (33 re-fetches blocked by HTTP 403, 5 network errors, 2 loaded but quote not found - not yet investigated) |
| Retrieval | 58 direct, 36 search-provider extract (site blocked direct fetch) |
| Latency | median 42.7 s, max 99.3 s (i02, slowed by the rate limiter) |
| Models | t01-t04 `gemini-3.8-flash`; f01 onwards `gemini-3.5-flash-lite` (primary free daily quota exhausted after ~20 requests) |

**Not measured:** Hindi and Marathi (all 4 failed), correction drafting with live models, quality of `gemini-3.8-flash` beyond 4 items. 20 items of well-known claims is far too small for statistical claims.

**Separate first live check (via the real UI):** "The Statue of Unity in Gujarat, which depicts Sardar Vallabhbhai Patel, is 182 metres tall." -> verified, strong, 32 s, 3 Gemini calls (5,903 tokens), 1 Tavily credit, 10 counted quotes from Wikipedia, Britannica, gujarattourism.com and theunitytourism.com. The very first attempt failed with `timeout`: `gemini-3.8-flash` at its default thinking level took ~75 s per call; fixed by `GEMINI_THINKING_LEVEL=low` (~3 s).

### Fixes after run 1 (regression-tested, not yet re-validated live)
1. **Exhausted model kept being retried.** Every call tried the quota-exhausted primary first (50 wasted requests, each using a rate-limit slot), which tripped the local 8/min limiter. Now an exhausted model is skipped until Google's reset (midnight Pacific, per Google's docs; `GEMINI_QUOTA_RESET_TZ`), the refused request's slot is released, and SatyaSetu's own daily budget no longer marks a model exhausted.
2. **Self-contradictory source counted on both sides (t03).** Wikipedia's RBI article says "established in 1934" in one sentence and "1 April 1935" in its infobox; it was counted as both support and refutation, producing *conflicting*. Now a domain with quotes on both sides keeps only its majority side; a tie drops it from both. Excluded quotes are stored with the reason and shown as "not counted".
3. **Academic domains treated as official.** `.ac.in`/`.edu` lecture-note PDFs were weighted as official. They are now "other" unless explicitly listed (e.g. `nta.ac.in`).

Run it once keys are set (it uses roughly 70-100 Gemini calls and 40-80 Tavily credits for the full set, so raise `TAVILY_MAX_SEARCHES_PER_DAY` first or run in parts):
```powershell
docker compose run --rm -v ${PWD}/eval:/eval backend python /eval/run_eval.py --base http://frontend
```
It reports accuracy against the accepted verdicts, false positives and negatives, unsupported verdicts, citation checks (server quote check, URL resolves now, quote present on the live page), latency, failures, and a breakdown by language and category.

## What has been tested (automated, all passing)

| Suite | Count | What it proves | What it does **not** prove |
|---|---|---|---|
| Backend pytest | 91 | Verdict rules for every category; quote validation; SSRF blocking (18 URL classes, DNS rebinding, redirect to metadata IP, size/type limits, IP pinning); Gemini/Tavily adapters against mocked HTTP (schema, auth header, retries, quota fallback, blocked content); the full API→DB→job→SSE flow with mocked providers: arbitrary text, insufficient evidence, empty search, conflicting evidence, mixed claims, paraphrased-quote rejection, missing credentials, malformed model output, timeout + retry, duplicate clicks, concurrent isolation, SSE replay/resume, session isolation, prompt injection, blocked URL, correction validation, history/delete cascade, restart interruption | That the real models label passages well, or that real search finds good sources |
| Frontend vitest | 6 | Message states (Verify / progress / failed / result), stale-job guard, event merge, labels | |
| Playwright e2e (real stack, no keys) | 12 (4 tests × 1280/768/360 px) | AT-01 arbitrary text sent and displayed; AT-02 Verify POSTs that message's ID and the server's job input equals the typed text; Shift+Enter, ordering, sending during a check; AT-15 honest failure UI and safety warnings without keys; AT-13 no horizontal overflow, drawer on mobile | Live verification UI with real results |
| Manual media check (real stack) | - | PNG OCR (confidence 92/100 on a clean synthetic image); PDF text layer and document checks; WAV transcription path; `.exe` rejected (415) | OCR on real WhatsApp screenshots; transcription accuracy on real speech (only a no-speech tone was tested) |

## Harm-signal heuristic: measured, small, not reliable
| Set | n | TP | FP | FN | Note |
|---|---|---|---|---|---|
| Tuning set (`test_harm_eval.py`) | 40 | 31 | 0 | 0 | **Used to tune the rules**, so this is optimistic. Five labels were corrected after review to match the written category definitions (impersonation = invokes an official body while requesting money/details/clicks; KYC update request = personal info). |
| Held-out set (`test_harm_heldout.py`) | 24 | 12 | 3 | 3 | Written after tuning and not used to tune. Misses: "reply with the 6 digit code" (OTP phrased as "code"), "UAN + bank details" (labelled personal info, detected as payment). Two FPs are arguably definitional (PM scheme + link → impersonation). |

These are synthetic, tiny sets. They are regression guards, not evidence of real-world reliability.

## Acceptance tests

| ID | Status |
|---|---|
| AT-01 Arbitrary text | **Pass** (Playwright, real stack) |
| AT-02 Real backend connection | **Pass** (Playwright inspects the POST and the server's stored input) |
| AT-03 Real pipeline | Mock-verified only; **live: not run** |
| AT-04 Evidence traceability | Enforced by code + tested with mocks; **live: not run** |
| AT-05 Unseen claims | Pipeline accepts any text (tested); live quality **not run** |
| AT-06 Insufficient evidence | **Pass** (mock) |
| AT-07 Conflicting evidence | **Pass** (mock) |
| AT-08 Mixed claims | **Pass** (mock) |
| AT-09 Progress / errors / retry | **Pass** (mock + real SSE through nginx) |
| AT-10 Message isolation | **Pass** (mock, concurrent) |
| AT-11 Correction workflow | Validation tested (mock); copy/download UI not yet e2e-tested with a completed job (needs keys) |
| AT-12 Persistence across restart | **Pass** (manual: `docker compose restart`, same session's history and conversations intact); retention cleanup runs on startup and every 6 h |
| AT-13 Responsive UI | **Pass** at 360/768/1280 (no overflow, drawer works); report panel at 360 px not yet exercised with live data |
| AT-14 No hidden demo behaviour | **Pass** (`test_no_demo_paths.py`: AST scan, verdict-assignment scan, registry check) |
| AT-15 Missing credentials | **Pass** (API + UI) |

## Known limitations
- Retrieval quality depends on Tavily's index; many Indian news sites block direct fetches (the provider's extracted text is then used and labelled).
- Lexical passage selection can miss the relevant paragraph on long pages, which leads to more *insufficient evidence* results.
- Hindi/Marathi claims are searched mostly with English queries generated by the model.
- Source tiers come from a hand-maintained domain list; unknown reputable sites count as "other" (weight 1).
- No recheck/watch feature; no video support.
- Document forensics cannot look up reference numbers in any official registry (always "could not check").
