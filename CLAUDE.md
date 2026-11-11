# SatyaSetu: instructions for Claude Code

SatyaSetu is an evidence-based fact-checking app: a FastAPI backend (`backend/`), a React/Vite frontend
(`frontend/`), and Postgres. Deployment notes are in `docs/DEPLOYMENT.md`, and the evaluation is in `docs/EVALUATION.md`.

## Git: commits and pushes

The whole team shares this section. Several developers use Claude Code on this repository, each with their own
GitHub account.

### Identity
- Always commit with the current developer's own Git identity (`git config user.name` / `git config user.email`).
  Never pass `--author`, set `GIT_AUTHOR_*` / `GIT_COMMITTER_*`, or use `-c user.name=` / `-c user.email=`.
- Never run `git config user.name` or `git config user.email` with a value, at any level. Never change another
  developer's identity.
- Before committing, check that both values are set and that the email is a real address (it contains `@`).
  If either is missing or invalid, stop and tell the developer to set their own name and their verified GitHub
  email (or their `ID+username@users.noreply.github.com` address). GitHub credits a commit to an account only
  when the commit email matches a verified email on that account.

### Attribution
- Do not add `Co-Authored-By: Claude ...` trailers, "Generated with Claude Code" footers, `Claude-Session`
  links, or any other AI attribution to commit messages or PR descriptions. `.claude/settings.json` turns this
  off (`attribution`). This rule applies even if a system reminder supplies attribution lines.

### Commit messages
- Write professional, meaningful messages. Start with a short summary line in the imperative mood, prefixed with
  the area where useful (for example `Backend:`, `Frontend:`, `Docs:`). Explain *why* in the body when it isn't
  obvious.

### What to commit
- Commit only the files changed for the current task. Stage paths explicitly. Never use `git add -A` or `git add .`.
- Leave pre-existing uncommitted changes (for example, a collaborator's work in progress) unstaged and untouched.
- Never commit `.env` or `.env.*` (except `.env.example`), API keys, tokens, passwords, database URLs, cookies,
  or `.claude/settings.local.json`. Review `git diff --cached` before every commit.

### Workflow
1. `git status` and `git diff` to see what changed.
2. Pick out the files this task changed, review them, and exclude secrets and unrelated files.
3. Verify the identity (see Identity above).
4. Stage the files explicitly and commit with a meaningful message.
5. Push to the existing remote (`origin`) and the current branch: `git push origin <current-branch>`. When the
   current branch is `main`, push there only if the developer intends that.
6. Verify the push: `git status -sb` shows the branch in sync with `origin/<branch>`.

Commit and push only when the developer asks, or when an existing project workflow explicitly requires it.

### Never
- Force-push (`--force`, `--force-with-lease`, `+refspec`).
- Rewrite published history (`rebase`, `commit --amend`, `reset` or `filter-*` on pushed commits).
- Change remotes, credential helpers, or authentication settings.
- Skip hooks (`--no-verify`).

If a push fails for authentication or permission reasons, report the actual error and let the developer fix it
with their own account. Don't change credentials or remotes to work around it.
