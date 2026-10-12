# Deployment (free tiers)

**Live demo:** https://satyasetu-hack.vercel.app (Vercel production alias, public; previews stay behind Vercel Authentication)
**Backend:** https://satyasetu-api.onrender.com (`/api/health`, `/api/ready`)

Quota protection for the public demo (backend, database-backed so restarts and cleared cookies don't reset it):
30 fact-checks per hour across all visitors, 15 per visitor session per day, 6 uploads per minute per session,
plus the provider budgets (Gemini 200 requests/day, Tavily 40 searches/day and 900/month).

```
Browser ──HTTPS──► Vercel (static React build)
                     └─ /api/* rewrite (same origin, first-party cookie, no CORS)
                          ──HTTPS──► Render web service (Docker, FastAPI)  ──TLS──► Neon Postgres
                                                                 └──► Gemini, Tavily, public web pages
```

The browser only ever talks to the Vercel domain. Vercel proxies `/api/*` to the backend (`frontend/vercel.json`), so the session cookie stays first-party, Server-Sent Events work through the proxy (the backend sends a keep-alive every 15 s, within Vercel's 120 s proxy limit), and no CORS configuration is needed or enabled. API keys exist only in the Render service environment.

| Piece | Host / plan | Notes |
|---|---|---|
| Frontend | Vercel Hobby (free, non-commercial) | `frontend/vercel.json`: Vite build, SPA fallback, CSP, `/api` rewrite |
| Backend | Render free web service, Docker, region Singapore | `render.yaml`. Sleeps after 15 min idle (~1 min wake-up); ephemeral disk (uploads lost on restart); audio disabled (Whisper needs more memory than the free instance) |
| Database | Neon free | No expiry; scales to zero after 5 min (small first-query delay). Render's free Postgres was not used because it is deleted after 30 days |

## Environment variables (names only)

| Variable | Service | Secret | Set where |
|---|---|---|---|
| `DATABASE_URL` | Render | yes | Render dashboard (Neon connection string, `sslmode=require` accepted) |
| `GEMINI_API_KEY` | Render | yes | Render dashboard |
| `TAVILY_API_KEY` | Render | yes | Render dashboard |
| `COOKIE_SECURE`, `DATA_DIR`, `GEMINI_MODEL`, `GEMINI_FALLBACK_MODEL`, `GEMINI_THINKING_LEVEL`, `TAVILY_MAX_SEARCHES_PER_DAY`, `TAVILY_MAX_SEARCHES_PER_MONTH`, `WHISPER_ENABLED`, `MAX_CONCURRENT_CHECKS` | Render | no | `render.yaml` |
| (backend URL) | Vercel | no | `frontend/vercel.json` rewrite destination |

The frontend needs no environment variables: it calls relative `/api` URLs.

## Redeploying after code changes

- Backend: `git push` to `main`. Render rebuilds automatically when files under `backend/` change (`autoDeployTrigger: commit`, `buildFilter`). Migrations run on start (`alembic upgrade head`).
- Frontend: from `frontend/`, `vercel deploy` (preview) then `vercel deploy --prod`. If the Vercel project is connected to the GitHub repo, pushes deploy automatically (preview for branches, production for `main`).

## Cold starts (Render Free) and the 2026-10-12 incident

Render's free instance sleeps after 15 min without traffic. Measured: while it wakes, the Vercel `/api` proxy
answers **immediately with an HTML 502 page** (0.5 s), and the backend becomes healthy again after ~45-60 s.
Before `496da87` the frontend treated that 502 as a final error ("server unavailable") and never retried, so the
site looked broken until a manual reload after the backend had woken.

Now (frontend `496da87`, `f2033ab`):
- any non-JSON `/api` response is treated as "server not ready", never as data;
- requests are retried with backoff for up to ~150 s; writes are resent only when the response proves the
  request never reached the app (so no duplicate messages); the backend also de-duplicates Verify clicks;
- a "Waking up the server" banner is shown while a request is slow (>4 s) or being retried;
- if the live progress stream (SSE) fails, the job is polled until it finishes (bounded), plus a 30 s watchdog.

Expect the first visit after an idle period to take about a minute. No keep-alive pinging is used.

## Data separation
The hosted database starts empty. Local conversations, uploads and evaluation records are never copied to it.
