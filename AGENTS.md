# Agent instructions (OpenCode and other assistants)

This repository is shared between two machines and two AI coding assistants: Claude Code on native Linux and
OpenCode on Windows + WSL. The project instructions live in **`CLAUDE.md`**. Read it first, together with
`B1_CONTEXT.md` and `docs/development_environment.md`. This file only points there, so the two cannot drift apart.

Short version of the shared rules:
- Git is the source of truth. One codebase, no OS-specific branches; branches are for features only.
- Before editing: `git status`, `git fetch`, then integrate the remote changes. Never `reset --hard`,
  `clean -fd` or force-push unless the user explicitly asks.
- `.env` is local to each machine and never committed. Never print secrets, and never `source .env` in a shell:
  read it only through Python (`python-dotenv`).
- No absolute paths (`/home/...`, `C:\...`) in code. Run scripts from the repository root.
- Neo4j (Docker volume) is local per machine and is not synchronised. Rebuild it with the scripts.
- Do not commit or push unless the user asks. Run the tests before suggesting a commit.
