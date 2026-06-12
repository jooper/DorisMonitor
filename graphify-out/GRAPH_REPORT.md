# Graph Report - .  (2026-06-11)

## Corpus Check
- Corpus is ~19,638 words - fits in a single context window. You may not need a graph.

## Summary
- 152 nodes · 254 edges · 22 communities (15 shown, 7 thin omitted)
- Extraction: 98% EXTRACTED · 2% INFERRED · 0% AMBIGUOUS · INFERRED: 5 edges (avg confidence: 0.8)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 21|Community 21]]

## God Nodes (most connected - your core abstractions)
1. `query()` - 30 edges
2. `SchedulerService` - 19 edges
3. `collect_metrics()` - 16 edges
4. `Flask Backend (app.py)` - 15 edges
5. `cluster` - 8 edges
6. `alert_checker_loop()` - 7 edges
7. `get_db()` - 6 edges
8. `load_config()` - 5 edges
9. `load_alert_config()` - 5 edges
10. `get_all_tables()` - 5 edges

## Surprising Connections (you probably didn't know these)
- `Flask Backend (app.py)` --conceptually_related_to--> `System Architecture Diagram (architecture.png)`  [AMBIGUOUS]
  app.py → architecture.png
- `README.md - Project Overview` --references--> `Flask Backend (app.py)`  [INFERRED]
  README.md → app.py
- `Flask Backend (app.py)` --references--> `Dashboard SPA (dashboard.html)`  [EXTRACTED]
  app.py → static/dashboard.html
- `Flask Backend (app.py)` --implements--> `MV Dependency Graph (vis.js)`  [EXTRACTED]
  app.py → static/dashboard.html
- `Single-Process Deployment Decision` --rationale_for--> `Flask Backend (app.py)`  [EXTRACTED]
  FSD.md → app.py

## Hyperedges (group relationships)
- **Metrics Collection and Display Pipeline** — doris_mt_pro_metrics_pipeline, doris_mt_pro_cache_layer, doris_mt_pro_config_main, doris_mt_pro_app_backend, static_dashboard_main [INFERRED 0.95]
- **Alert Detection and Notification Pipeline** — doris_mt_pro_alert_engine, doris_mt_pro_metrics_pipeline, doris_mt_pro_config_main, doris_mt_pro_app_backend [INFERRED 0.95]
- **Dual Job Scheduling Systems** — doris_mt_pro_job_management, doris_mt_pro_internal_scheduler, doris_mt_pro_scheduler_service_main, doris_mt_pro_app_backend [INFERRED 0.85]

## Communities (22 total, 7 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.15
Nodes (22): api_catalog_alter(), api_catalog_drop(), api_jobs_execute_ddl(), api_metrics(), api_tables(), collect_metrics(), discover_mvs(), _fetch_mv_ddls() (+14 more)

### Community 2 - "Community 2"
Cohesion: 0.12
Nodes (9): api_catalog_create(), api_jobs_catalogs(), api_jobs_databases(), api_jobs_internal_dbs(), get_catalog_databases(), get_catalogs(), get_internal_databases(), parse_capacity() (+1 more)

### Community 3 - "Community 3"
Cohesion: 0.14
Nodes (19): Scheduled Jobs Data (scheduler_jobs.json), Alert Engine (SMTP Email), Flask Backend (app.py), System Architecture Diagram (architecture.png), Cache Layer (CACHE/MV_CACHE/DB_CACHE), Catalog Browser (External Data Sources), Cluster Configuration (config.json), FSD.md - Functional Specification (+11 more)

### Community 4 - "Community 4"
Cohesion: 0.20
Nodes (9): cluster, be_http_port, connect_timeout, fe_http_port, host, password, port, user (+1 more)

### Community 5 - "Community 5"
Cohesion: 0.24
Nodes (10): alert_checker_loop(), api_alert_config(), api_alert_test(), api_config(), build_alert_body(), check_alerts(), load_alert_config(), load_config() (+2 more)

### Community 6 - "Community 6"
Cohesion: 0.29
Nodes (7): api_jobs_drop(), api_jobs_pause(), api_jobs_resume(), drop_job(), _exec_job_cmd(), pause_job(), resume_job()

### Community 7 - "Community 7"
Cohesion: 0.33
Nodes (6): api_jobs_columns(), api_jobs_preview(), _col_name(), generate_create_ddl(), get_table_columns(), map_doris_type()

### Community 8 - "Community 8"
Cohesion: 0.40
Nodes (5): api_alter_mv(), api_create_mv(), api_test_connection(), get_db(), get_fe_config()

### Community 9 - "Community 9"
Cohesion: 0.50
Nodes (4): api_drop_mv(), api_refresh_mv(), api_toggle_mv(), execute_ddl()

### Community 10 - "Community 10"
Cohesion: 0.50
Nodes (4): api_get_mv_meta(), api_set_mv_meta(), _load_mv_meta(), _save_mv_meta()

### Community 11 - "Community 11"
Cohesion: 0.50
Nodes (3): instructions, plugin, $schema

### Community 14 - "Community 14"
Cohesion: 0.67
Nodes (3): api_catalogs(), _parse_catalog_props(), Extract key-value properties from a CREATE CATALOG statement.

### Community 15 - "Community 15"
Cohesion: 0.67
Nodes (3): api_table_detail(), get_table_detail(), Get DDL + columns for a specific table.

## Ambiguous Edges - Review These
- `Flask Backend (app.py)` → `System Architecture Diagram (architecture.png)`  [AMBIGUOUS]
  app.py · relation: conceptually_related_to

## Knowledge Gaps
- **21 isolated node(s):** `host`, `port`, `user`, `password`, `fe_http_port` (+16 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **7 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `Flask Backend (app.py)` and `System Architecture Diagram (architecture.png)`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **Why does `EnhancedEncoder` connect `Community 1` to `Community 2`?**
  _High betweenness centrality (0.159) - this node is a cross-community bridge._
- **Why does `query()` connect `Community 0` to `Community 2`, `Community 6`, `Community 7`, `Community 8`, `Community 14`, `Community 15`, `Community 16`, `Community 17`, `Community 18`?**
  _High betweenness centrality (0.019) - this node is a cross-community bridge._
- **What connects `Discover all user tables across databases.`, `Get DDL + columns for a specific table.`, `Extract key-value properties from a CREATE CATALOG statement.` to the rest of the system?**
  _24 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Community 2` be split into smaller, more focused modules?**
  _Cohesion score 0.12280701754385964 - nodes in this community are weakly interconnected._
- **Should `Community 3` be split into smaller, more focused modules?**
  _Cohesion score 0.14035087719298245 - nodes in this community are weakly interconnected._