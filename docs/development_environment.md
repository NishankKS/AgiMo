# Development environment (native Linux + Windows/WSL)

One project, one codebase, two machines:

| | Machine 1 | Machine 2 |
|---|---|---|
| OS | native Linux | Windows + WSL (Ubuntu) |
| AI assistant | Claude Code (reads `CLAUDE.md`) | OpenCode (reads `AGENTS.md` → `CLAUDE.md`) |
| Shared via Git | code, config, docs, committed data | same |
| Local only | `.env`, `.venv/`, Neo4j Docker volume, downloaded images, generated HTML | same |

Use the Linux shell on both machines: a terminal on machine 1, the WSL shell on machine 2. All commands below
are bash and are run from the **repository root**, because the scripts use relative paths such as `data/...`.

## Setup (both machines)

```bash
git clone git@github.com:NishankKS/AgiMo.git && cd AgiMo   # on WSL: clone inside the Linux filesystem (~/...), not /mnt/c
cp .env.example .env                                       # then fill in the values with an editor
uv sync                                                    # Python version from .python-version (3.12)
docker compose up -d                                       # Neo4j 5 community, ports 7474 / 7687
uv run python src/check_neo4j.py
```

- **Python / uv:** uv installs the interpreter from `.python-version` and the locked dependencies from `uv.lock`.
  Use `uv sync`, not `pip install`, so both machines get the same versions. Commit dependency changes
  (`pyproject.toml` + `uv.lock`) together.
- **Docker:**
  - Linux: Docker Engine with the Compose plugin.
  - Windows: Docker Desktop with *WSL integration* enabled for the distro, or Docker Engine inside WSL.
    `docker compose` must work from the WSL shell.
- **WSL file location:** keep the clone in the WSL filesystem (`~/...`). On `/mnt/c/...` it is slower, and
  Windows tools may change line endings or file permissions.

## `.env` (local, never committed)

Every machine has its own `.env`; `.env.example` lists the variables with placeholders only.

| Variable | Needed for |
|---|---|
| `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` | Neo4j (local Docker); the password is applied when the volume is first created |
| `OVERPASS_URL`, `STUDY_BBOX` | OSM download (`fetch_osm.py`) |
| `MAPILLARY_ACCESS_TOKEN` | Mapillary download (`fetch_mapillary.py`, `select_vlm_sample.py`) |
| `NVIDIA_API_KEY`, `NIM_MODEL`, optional `NIM_BASE_URL` | NVIDIA VLM runs (`run_vlm.py`) |
| `GROQ_API_KEY` | Groq comparison (`run_vlm.py --provider groq`) |

- **Never print `.env`, and never `source .env` / `. ./.env` in a shell.** The Mapillary token contains `|`,
  and bash executes fragments of it and echoes them. The scripts read `.env` through `python-dotenv`.
- Keys can differ per machine. Only the variable *names* need to match `.env.example`.

## Neo4j (local per machine)

The Docker volume is **not** shared and Git does not synchronise it. Each machine rebuilds its graph from the
committed data:

```bash
uv run python src/import_osm.py                    # OSM layer from data/raw/osm_*.json
uv run python src/verify_graph.py
```

- **Known difference, not yet fixed:** `import_visual_observations.py` imports *all* `b1-prompt-v2` records in
  `data/processed/vlm_observations.jsonl`, which is now 21 images / 336 observations, including Stage 4. The
  graph on machine 1 holds the Stage 3 state: 3 images / 48 observations. Running the importer on a fresh
  machine therefore produces a larger visual layer. Until the importer can be limited to a set of images, do
  not run it just to "sync"; compare `verify_graph.py` counts instead.
- **Checks:** `verify_graph.py` and the read-only scripts print counts that can be compared between machines.

## Data that is (not) in Git

- **Committed:** raw OSM, Mapillary search/metadata JSON, raw VLM responses (V1/V2/Stage 4, Groq), and
  `data/processed/*`, which includes the human-review CSVs and checksum manifests.
- **Not committed:** Mapillary thumbnails (`data/raw/mapillary/images/*.jpg`) and generated HTML
  (`data/visualizations/`). Recreate them on each machine:
  - thumbnails: `uv run python src/fetch_mapillary.py` and `uv run python src/select_vlm_sample.py`. These use
    the cache and the Mapillary API and need the token. The VLM review pages show images only once they exist
    locally.
  - HTML: `uv run python src/visualize_graph.py`, `uv run python src/review_vlm_results.py --html`.
- **Byte-exact data:** `.gitattributes` keeps LF line endings on both platforms and never converts
  `data/raw/**` or `*.csv`, so the checksum tests (`test_vlm_stage5/6/7.py`) pass on both machines.

## Opening generated HTML

- Linux: `xdg-open data/visualizations/<file>.html`. The scripts print this hint.
- WSL: `explorer.exe "$(wslpath -w data/visualizations/<file>.html)"`, or `wslview <file>` if `wslu` is
  installed. Images use relative paths, so open the file from the repository rather than copying it elsewhere.

## Git workflow

```bash
git status && git fetch && git log --oneline -3 HEAD origin/main   # before starting work
git pull --ff-only                                                 # if behind and the tree is clean
# ... work, then run the tests:
for t in test_run_vlm test_import_visual_observations test_fetch_mapillary test_vlm_evaluation \
         test_vlm_stage5 test_vlm_stage6 test_vlm_stage7; do uv run python src/$t.py; done
git status && git diff                                             # check: no .env, no secrets, no generated files
git add <files> && git commit -m "<type>: <what and why>" && git push
```

- Branches represent features or experiments (`feature/vlm-v3`), never operating systems.
- **Before a commit:** the tests pass; `.env` is not staged; no keys appear in the diff; no `/home/...` or
  `C:\...` paths; no generated files are staged.
- **No destructive commands** (`reset --hard`, `clean -fd`, force push) unless the user explicitly asks.
- **Human labels** live in committed CSVs. Label on one machine at a time and push before labelling on the
  other. Otherwise two edits to the same CSV conflict. The merge script itself is idempotent.
- Neo4j counts and test checks are Linux/WSL-neutral. The one OS-specific step is how HTML is opened (above).

## Common platform issues

| Symptom | Likely cause | Fix |
|---|---|---|
| Checksum tests fail after a clone on Windows | line endings converted (clone under `/mnt/c` or Git for Windows with `core.autocrlf`) | clone inside WSL; `.gitattributes` prevents this for new clones |
| `docker compose` not found in WSL | Docker Desktop WSL integration disabled | enable it for the distro |
| Scripts hang when they start | Neo4j container not running | `docker compose up -d` |
| `FileNotFoundError: data/...` | script run from another directory | run from the repository root |
| Review page shows no images | thumbnails are not in Git | download them (see above) |
| Auth error with Neo4j on a new machine | the volume was created with another password | `docker compose down -v` (deletes the local graph), then rebuild |
