# Privacy & security

## What is stored, where, for how long
| Data | Where | Retention |
|---|---|---|
| Messages, verification results, retrieved page text (≤120 KB per source, kept for quote auditing), corrections | local PostgreSQL volume `satyasetu-v2_pgdata` | deleted with the conversation, or automatically after `RETENTION_DAYS` (default 30) without activity |
| Uploaded files + extracted text | volume `satyasetu-v2_appdata` (`/data/uploads/<session>/`) | same; files are removed from disk on deletion |
| Provider usage counters | PostgreSQL | counts only, no content |
| API keys | `.env` → backend container environment only | never in DB, logs, API responses or the frontend |

Deleting a conversation in the UI removes all of its records (DB cascade + file removal). `docker compose down -v` deletes everything.

**Sent to third parties when you press Verify:** the message text (and extracted attachment text) to Gemini; generated search queries to Tavily; requests to public source URLs. On the Gemini **free tier**, Google may use submitted content to improve its products. Do not verify sensitive personal information.

## Controls implemented
- **SSRF:** http/https only, default ports, no credentials in URLs, block localhost/private/link-local/CGNAT/multicast/reserved/IPv6-ULA/IPv4-mapped addresses, `*.internal/.local`, cloud metadata; DNS resolved once and the connection pinned to the vetted IP (TLS still verifies the hostname); every redirect re-validated; size (3 MB), content-type and time limits. Tests: `tests/test_safe_fetch.py`.
- **Uploads:** type decided by magic bytes, not extension or client MIME; 15 MB cap; audio length cap; files served with `nosniff` and a `default-src 'none'` CSP; video and executables rejected.
- **Input limits:** 6,000 chars per message; 256 KB JSON bodies; per-session rate limit for starting checks (6/min).
- **Provider safety:** local per-minute and per-day quotas checked before each call; bounded retries (one transient retry, one structured-output repair); API key sent as a header (`x-goog-api-key`/`Authorization`), never in URLs; httpx request logging silenced.
- **Model output:** strict Pydantic validation of every response; invalid output fails the stage; verbatim-quote validation; verdicts computed by rules; explanation URLs stripped; corrections validated for verdict match, invented numbers, model-written links and hedging.
- **Prompt injection:** see ARCHITECTURE.md. Instructions inside forwarded text are flagged as a harm signal.
- **Rendering:** React escapes all text; no `dangerouslySetInnerHTML`; external links use `rel="noopener noreferrer nofollow"`; strict CSP and `X-Frame-Options: DENY` from nginx.
- **Sessions:** anonymous HttpOnly SameSite=Lax cookie; every query filtered by session (tested in `test_session_isolation`).
- **Network exposure:** only `127.0.0.1:8080` is published; backend and DB are reachable only inside the Docker network; containers run as non-root (backend).
- **Dependencies:** exact versions pinned in `requirements.txt` and `package-lock.json`; base images pinned by tag.

## Known gaps
- No authentication: this is a single-user local app. Do not expose it to a network.
- The harm detector is a heuristic (see EVALUATION.md); it will miss some scams and flag some benign messages.
- `robots.txt` is not consulted for direct fetches (only result URLs from a search provider are fetched, one request each).
