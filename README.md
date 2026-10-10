# SatyaSetu

**Verify. Understand. Correct.** A local, chat-style app for checking forwarded messages against evidence.

Paste any message into the chat, send it, and press **Verify** on that message. The backend:

1. splits the message into individual claims,
2. searches the web for credible sources,
3. fetches the actual pages,
4. has a language model label passages with verbatim quotes,
5. **rejects any quote not found in the retrieved page**,
6. applies fixed, tested verdict rules,
7. explains the result in English, Hindi or Marathi.

From the report you can draft a respectful correction or download an evidence card.

There are no prepared answers, demo providers or canned verdicts. If the AI or search provider is missing, out of quota or failing, the check fails visibly and says why. It never shows a made-up result.

> SatyaSetu is an independent assistant, not affiliated with WhatsApp, any government body or any fact-checking organisation. Its verdicts can be wrong; always read the cited sources.

---

## Quick start (Windows PowerShell)

Requirements: **Docker Desktop** (running). Nothing else is needed on the host.

```powershell
cd C:\Users\Siddesh\Desktop\AIDLhack
Copy-Item .env.example .env        # first time only, then add your keys (see below)
docker compose up -d --build
Start-Process http://localhost:8080
```

| What | Where |
|---|---|
| App | http://localhost:8080 (bound to localhost only) |
| API (through the same origin) | http://localhost:8080/api/... |
| Health / readiness | http://localhost:8080/api/health, http://localhost:8080/api/ready |
| OpenAPI spec | http://localhost:8080/api/openapi.json (summary in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#api)) |

Stop: `docker compose down`. Stop and **delete all data**: `docker compose down -v`.

The first audio upload downloads the Whisper `base` model (~145 MB) into the `appdata` volume.

## Enabling live verification (free tiers)

The app starts and works without keys. Chat, history, uploads, OCR, document checks and safety warnings all work. Verification then fails with *"Live verification needs API keys"*. To enable it:

1. **Gemini API key**: https://aistudio.google.com/apikey → *Create API key*. Use a project **without billing enabled** to stay on the free tier.
2. **Tavily API key**: https://app.tavily.com → sign up (free plan: 1,000 credits/month; one basic search = 1 credit).
3. Edit `.env`:
   ```
   GEMINI_API_KEY=your-key
   TAVILY_API_KEY=tvly-your-key
   ```
4. `docker compose up -d` (recreates the backend with the new environment).
5. Settings → Providers should show both as configured. `GET /api/capabilities?probe=true` checks that the configured Gemini models are available to your key. It uses a metadata call that costs no generation quota.

Optional: `FACTCHECK_API_KEY`, a Google Cloud API key with the *Fact Check Tools API* enabled (free). It adds published fact-check articles as candidate sources.

### Data-use trade-off (read before enabling)
On the Gemini API **free tier**, Google states that submitted content **may be used to improve its products** and may be reviewed by humans. The paid tier does not do this. Tavily receives the search queries. So:
- do not verify messages containing OTPs, passwords, ID numbers, account numbers or other sensitive personal data;
- the backend sends only the message text and fetched public web passages; it never sends your session, other conversations or keys.

### Cost controls
Requests are refused locally **before** these limits are reached (all configurable in `.env`):

| Limit | Default |
|---|---|
| Gemini requests | 8/min, 200/day |
| Tavily searches | 40/day, 900/month |
| Per check | ≤4 claims, ≤2 searches per claim, ≤6 searches total, 180 s timeout |
| Typical check | 3–6 Gemini calls, 1–6 Tavily credits |

Today's usage is shown in Settings and at `GET /api/usage`. No paid API is ever called by default. Billing is never enabled by this app.

## Running the tests

```powershell
# Backend: 87 tests (unit + API/DB/SSE integration with mocked providers), against a separate test database
docker compose run --rm backend python -m pytest -q

# Frontend unit tests
cd frontend; npm ci; npm test

# End-to-end UI tests against the running stack (desktop 1280, tablet 768, mobile 360)
npx playwright install chromium   # first time
npx playwright test

# LIVE evaluation (real Gemini + Tavily calls; ~70 searches for the full set - raise TAVILY_MAX_SEARCHES_PER_DAY first)
docker compose run --rm -v ${PWD}/eval:/eval backend python /eval/run_eval.py --base http://frontend --limit 1
```

Mocked-provider tests prove the plumbing and the rules, **not** verification quality. See [docs/EVALUATION.md](docs/EVALUATION.md) for what has and has not been validated live.

## Repository layout

```
backend/            FastAPI app
  app/api/          HTTP routes (chat, verification + SSE, system)
  app/pipeline/     claim extraction → search → fetch → evaluation → quote check → verdict rules → explanation
  app/providers/    Gemini, Tavily, Google Fact Check adapters (+ errors, quotas)
  app/core/         SSRF-safe fetcher, events, jobs, sessions, rate limits, usage
  app/ingest/       OCR (Tesseract), PDF, audio (faster-whisper)
  alembic/          migrations
  tests/            pytest (mock providers live ONLY here, in tests/fakes.py)
frontend/           React + TypeScript + Vite + Tailwind, served by nginx
  src/api/          generated OpenAPI types + typed client
  e2e/              Playwright tests against the real stack
eval/               labelled live-evaluation set + runner
docs/               architecture, API, evaluation, privacy/security, troubleshooting
```

More: [Architecture & API](docs/ARCHITECTURE.md) · [Evaluation & readiness](docs/EVALUATION.md) · [Privacy & security](docs/SECURITY.md) · [Troubleshooting](docs/TROUBLESHOOTING.md)
