# Claude Code Instructions

## Project

Small AgiMo B1 Streetscape Knowledge Graph proof-of-concept.

Read `B1_CONTEXT.md` before making architectural decisions.

## Rules

- Do not over-engineer.
- Keep the implementation small and understandable.
- Use Neo4j from the beginning.
- Use Python + GeoPandas for geospatial data processing.
- Prefer real-world open data for the prototype.
- Start with a small geographic study area.
- OpenStreetMap and Mapillary are the preferred initial external data
  sources.
- Use dummy data only for development, testing, or when real data is
  not yet available.
- Do not download unnecessarily large datasets.
- Inspect real input data before designing import logic.
- Preserve original source IDs where possible.
- Preserve provenance where practical.
- Keep GIS-derived information separate from VLM observations.
- Do not introduce GNNs, vector databases, agents, microservices or
  complex ontology frameworks unless explicitly requested.
- Prefer working prototypes over abstractions.
- Implement the project in phases.
- Do not automatically continue to the next phase.
- After each phase, test it and report what was done.

## Development approach

Before each phase:

1. Inspect the current project.
2. Briefly explain what will be implemented.
3. Implement only that phase.
4. Test it.
5. Report what was created and tested.
6. Stop and wait for further instructions.

## Cross-machine development

This repository is developed on two machines: native Linux with Claude Code, and Windows + WSL with OpenCode.
See `docs/development_environment.md`. `AGENTS.md` points OpenCode to this file.

- Git is the source of truth. One codebase; branches are for features, never per operating system.
- Before editing: `git status` + `git fetch`, and integrate remote work first. No destructive git commands
  (`reset --hard`, `clean -fd`, force push) unless explicitly requested.
- `.env` is machine-local and never committed. Never print secrets; load `.env` only via Python.
- No absolute or OS-specific paths in code. Run scripts from the repository root.
- Neo4j state is local per machine. It is rebuilt from scripts and committed data, not synchronised.
- Do not commit or push unless asked. Before a commit: run the tests, check the diff, check that no
  secrets or generated files are staged.
