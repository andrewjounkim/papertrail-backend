# Prompt log

AI tools used on this project:
- **Claude Code** (Sonnet 5) — pair-programmed the entire backend and frontend in this session.
- **Anthropic Claude API** (model set via `ANTHROPIC_MODEL`, default `claude-sonnet-5`) — the in-app LLM that powers `/api/explain`, `/api/what-next`, and query generation for `/api/trend`.

This log is updated after each build step with the key prompts/decisions that shaped the code, plus the exact system prompts sent to the in-app LLM.

---

## Initial project brief (summarized)

Build PaperTrail, a research paper reading companion, for a class assignment (HW4) due today. Two repos: a Flask backend on Render, a static HTML/CSS/JS frontend on GitHub Pages. The backend normalizes a PMID/URL/DOI, fetches metadata + abstract from PubMed E-utilities and citation stats from iCite, and uses an LLM (grounded only in retrieved data, never invented) to: (1) explain the paper at three reading levels, (2) summarize how later citing papers built on/challenged it, and (3) generate a PubMed query to chart the field's yearly publication trend. Hard requirements: no secrets committed (env vars + `.env`/`.gitignore` from the first commit), CORS restricted to the GitHub Pages origin + localhost, JSON error responses with correct status codes and timeouts on every outbound call, loading states and friendly errors on the frontend, and a "wake up the sleeping Render backend" health check. Build order: backend skeleton → `/api/paper` → `/api/explain` → `/api/what-next` → `/api/trend` → frontend wired locally → README + this log → deploy instructions.

Follow-up decisions from the user: use the **Anthropic Claude API** (not OpenAI); develop the frontend locally first and add it to a repo (new repo vs. portfolio page — TBD) once it's working end-to-end.

---

## Step 1: Backend skeleton

Prompt: "Backend skeleton: /health, .gitignore, .env.example, requirements.txt. Run locally."

- `app.py` created with Flask app, `flask-cors` restricted via an `ALLOWED_ORIGINS` env var (comma-separated), a catch-all exception handler that always returns JSON instead of a traceback, and `GET /health`.
- `.gitignore` (covering `.env`, venv, caches) written and committed *before* `.env.example`/`app.py` so no secret could ever land in history.
- `.env.example` documents every env var the app needs: `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `NCBI_API_KEY`, `NCBI_EMAIL`, `NCBI_TOOL_NAME`, `ALLOWED_ORIGINS`, `PORT`.
- `requirements.txt`: flask, flask-cors, requests, python-dotenv, gunicorn, anthropic.
- Verified locally: `python app.py` (port 5000 was taken by macOS AirPlay Receiver, moved local dev to 5001 via `.env`) → `curl localhost:5001/health` → `{"status": "ok"}`.
