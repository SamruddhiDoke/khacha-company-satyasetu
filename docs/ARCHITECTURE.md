# Architecture

A modular monolith: one FastAPI process (API + in-process background jobs), PostgreSQL, and an nginx container that serves the React build and proxies `/api`.

```
Browser ──► nginx :8080 ──► /            React SPA (static)
                       └──► /api/*       FastAPI backend :8000 (not published to the host)
                                           ├── PostgreSQL (conversations, jobs, claims, sources, evidence, events…)
                                           ├── Gemini API      (claim extraction, passage labelling, explanation, correction)
                                           ├── Tavily API      (search → candidate URLs)
                                           ├── Fact Check API  (optional)
                                           └── public web      (direct page fetch, SSRF-protected)
```

## Verification pipeline (`backend/app/pipeline/orchestrator.py`)

| Stage (SSE `stage`) | What actually happens | Can fail with |
|---|---|---|
| `received` | job loaded; input snapshot (message text + extracted attachment text) | - |
| `harm_check` | deterministic rules (`harm.py`): OTP/PIN, payment, personal data, suspicious links, medical action, impersonation, urgency, AI-instructions | - |
| `document_checks` | PDFs/images only (`forensics.py`): impossible dates, weekday mismatch, deadline before issue, free-mail contact, payment request, reference numbers (could not check), metadata | - |
| `extracting_content` | URLs in the message are fetched with the SSRF-safe fetcher; page text is added as context | blocked/failed noted, not fatal |
| `extracting_claims` | Gemini, structured JSON schema → claims with span, normalized form, entities, dates, numbers, attribution, type, checkable flag, queries | provider errors |
| `preparing_queries` | per-claim budget applied | - |
| `searching_sources` | Tavily basic search (1 credit each), social platforms excluded, provider's AI answer not requested; optional Fact Check API | quota/rate/provider |
| `fetching_sources` | ≤4 pages per claim, one per domain; direct fetch + text extraction (trafilatura / pypdf). If the site blocks us, Tavily's extracted page text is used and labelled `provider_extract`. Snippets are never evidence | per-source failure recorded |
| `evaluating_evidence` | top 3 passages per page (lexical ranking) → Gemini labels each passage supports / refutes / partially / not relevant, with a verbatim quote | provider errors |
| `checking_quotations` | every quote must occur (whitespace/quote-normalised, case-insensitive, ≥3 words) in **both** the passage and the stored page text, otherwise it is rejected and not counted | - |
| `computing_verdicts` | `verdicts.py` rules (below) | - |
| `preparing_explanation` | Gemini writes the explanation from the fixed verdicts and validated quotes only; URLs stripped, `[S#]` labels validated; on failure a deterministic template is used and labelled | - |

Everything is persisted in one transaction at the end. A provider failure ends the job as `failed` with a code (`provider_not_configured`, `quota_exhausted`, `rate_limited`, `timeout`, `invalid_model_output`, `content_blocked`, `provider_error`, `interrupted`, `internal`). There is no code path that produces a verdict without counted evidence.

### Verdict rules (`backend/app/pipeline/verdicts.py`)
A domain whose verified quotes fall on both the supporting and refuting side keeps only its majority side; on a tie it is dropped from both (self-contradictory source). Each domain counts once per stance with its tier weight (official 3, fact-checker 3, news 2, reference 2, other 1). A side is *credible* at weight ≥ 2.

| Claim verdict | Rule |
|---|---|
| not_checkable | opinion / prediction / question / instruction |
| insufficient_evidence | nothing counted, or no side credible |
| conflicting | supporting **and** refuting sides both credible |
| outdated | credible evidence flagged "describes a past state" |
| false | refuting side credible, supporting side not |
| misleading | supported/partly supported, but credible evidence flags missing context |
| partly_true | only partial support is credible |
| verified | supporting side credible, refuting side not |

Overall: identical verdicts across checkable claims → that verdict; otherwise **mixed** (with per-claim breakdown). Evidence strength is categorical (none / weak / moderate / strong); there are no percentage scores.

Tiers describe publisher type, not correctness. An official domain is weighted highly, but a credible contradiction from another tier still produces *conflicting*, not an automatic win.

### Prompt-injection defences
User text and web passages are wrapped in `<untrusted_*>` tags (closing tags inside content are neutralised), and system prompts state that the wrapped content is data. Most importantly, the model cannot decide verdicts. It can only label passages, and labels count only with quotes that are machine-verified against retrieved text.

## Live progress (SSE)
`GET /api/verifications/{id}/events` replays persisted events after `Last-Event-ID` (the browser sends it automatically on reconnect) and then streams live ones. Events are written to the DB before they are pushed, so a reconnecting client sees exactly what happened. On restart, any job still `queued`/`running` is marked `failed/interrupted` and can be retried.

## Data model
`sessions → conversations → messages → verification_jobs → {claims → evidence, sources, document_findings, corrections, verification_events}`; `attachments` (per session); `provider_usage` (per provider per day). All foreign keys cascade from the session, so deleting a conversation removes its jobs, claims, sources, evidence, events and corrections; attachment files are removed from disk. Partial unique index `uq_active_job_per_message` guarantees one active job per message.

## API
All JSON; errors are `{"code": "...", "message": "..."}`. Session is an HttpOnly cookie (`ss_session`) created on first request; all data is scoped to it. Full schema: `/api/openapi.json`. Frontend types are generated from it (`npm run gen:api`).

| Method & path | Purpose |
|---|---|
| `GET /api/health` | liveness |
| `GET /api/ready` | DB + migrations; reports provider configuration (503 if DB not ready) |
| `GET /api/capabilities[?probe=true]` | providers, input types, limits, data-use notice (`probe` checks model availability, no quota) |
| `GET /api/usage` | today's provider requests / tokens / credits and local limits |
| `GET/PUT /api/preferences` | language, theme |
| `GET/POST /api/conversations` | list (`?q=` search) / create |
| `GET/PATCH/DELETE /api/conversations/{id}` | read / rename / delete with all records |
| `GET/POST /api/conversations/{id}/messages` | list / send text (1-6000 chars) |
| `POST /api/conversations/{id}/attachments` | multipart `file` (+`caption`): image, PDF, audio; content-sniffed, ≤15 MB |
| `GET /api/attachments/{id}/file`, `/text` | original file / extracted text |
| `POST /api/messages/{id}/verifications` | `{language, retry}` → 202 new job, or 200 existing (duplicate-click safe) |
| `GET /api/verifications/{id}` | full report: claims, evidence, sources, findings, harm, explanation, events |
| `GET /api/verifications/{id}/events` | SSE progress |
| `POST/GET /api/verifications/{id}/corrections` | draft / list corrections (validated) |
| `GET /api/history`, `DELETE /api/history/{job_id}` | verification history |
