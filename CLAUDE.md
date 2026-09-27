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