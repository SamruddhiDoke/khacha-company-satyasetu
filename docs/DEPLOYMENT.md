# Deployment (free tiers)

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

## Data separation
The hosted database starts empty. Local conversations, uploads and evaluation records are never copied to it.
