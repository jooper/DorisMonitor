## Project Knowledge Graph

This project has a knowledge graph at `graphify-out/` with community structure, god nodes, and cross-file relationships.

**Always check the graph first** before reading source files directly:

- `graphify-out/GRAPH_REPORT.md` — architecture overview, community structure, god nodes, surprising connections
- `graphify-out/graph.json` — raw GraphRAG-ready graph data for queries
- `graphify-out/wiki/index.md` — agent-crawlable wiki with one article per community

Use `/graphify query "<question>"` for broad context, `/graphify path "<A>" "<B>"` for relationships, and `/graphify explain "<concept>"` for focused concepts. These return scoped subgraphs that are faster than browsing the full codebase.
