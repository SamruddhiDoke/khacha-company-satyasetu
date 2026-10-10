# Evaluation & readiness

Status as of 2026-10-10. Nothing below claims verification quality that has not been measured.

## Live-provider validation: NOT YET RUN
No Gemini or Tavily key has been configured yet, so **no live verification has been executed**. Consequently:
- verdict accuracy, citation correctness against real pages, API latency and live failure rates are **unknown**;
- AT-03, AT-04, AT-05 and AT-11 have only been exercised with mocked providers;
- the 24-item labelled set in `eval/dataset.jsonl` has **not** been run.

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
