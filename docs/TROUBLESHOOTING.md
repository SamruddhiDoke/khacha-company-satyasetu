# Troubleshooting (Windows PowerShell)

| Symptom | Fix |
|---|---|
| `docker compose` errors with "cannot connect to the Docker daemon" | Start Docker Desktop and wait until it says *Engine running*. |
| `ports are not available ... 8080` | Something else uses 8080. Change `"127.0.0.1:8080:80"` in `docker-compose.yml` to e.g. `"127.0.0.1:8090:80"` and open that port. |
| Page loads but shows "Cannot reach the SatyaSetu server" | `docker compose ps` - backend must be `healthy`. Logs: `docker compose logs backend --tail 100`. |
| Yellow "Live verification isn't configured" bar | Add `GEMINI_API_KEY` and `TAVILY_API_KEY` to `.env`, then `docker compose up -d`. |
| Check fails with *quota exhausted* | Free-tier daily quota (Google's or the local `GEMINI_MAX_REQUESTS_PER_DAY` / `TAVILY_MAX_SEARCHES_PER_DAY`) is used up. See Settings → Usage today. Quotas reset at 00:00 UTC (Gemini resets on Google's schedule). |
| Check fails with *rate limited* | Wait a minute and press Retry. Lower concurrency by verifying one message at a time. |
| Check fails with "No configured Gemini model is available to this API key" | Open `http://localhost:8080/api/capabilities?probe=true`; set `GEMINI_MODEL` in `.env` to a model your key can use (see https://ai.google.dev/gemini-api/docs/models). |
| Check fails with *interrupted* | The backend restarted mid-check. Press Retry. |
| Verdict is *Insufficient evidence* often | Expected for local/obscure claims: the app abstains rather than guessing. Many news sites block direct fetches; those pages fall back to the search provider's extracted text when available. |
| Audio upload slow the first time | The Whisper model (~145 MB) downloads once into the `appdata` volume. |
| Image text is wrong | OCR confidence is shown under the image; low-contrast or handwritten text OCRs poorly. Add a caption with the text. |
| Migrations | Applied automatically on backend start (`alembic upgrade head`). Manual: `docker compose exec backend alembic upgrade head`. |
| Reset everything | `docker compose down -v` (deletes all conversations, uploads and usage counters). |
| Port 8000 already in use | Not a problem: the backend is not published to the host. |
| Another project named `satyasetu` | This stack uses the Compose project name `satyasetu-v2` so it never touches the earlier project's volumes. |
