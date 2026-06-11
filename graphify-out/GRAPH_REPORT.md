# Graph Report - .  (2026-06-10)

## Corpus Check
- Corpus is ~19,073 words - fits in a single context window. You may not need a graph.

## Summary
- 161 nodes · 267 edges · 20 communities (14 shown, 6 thin omitted)
- Extraction: 91% EXTRACTED · 9% INFERRED · 0% AMBIGUOUS · INFERRED: 24 edges (avg confidence: 0.84)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Alert & Monitoring System|Alert & Monitoring System]]
- [[_COMMUNITY_Flask API Routes|Flask API Routes]]
- [[_COMMUNITY_Job Scheduler Service|Job Scheduler Service]]
- [[_COMMUNITY_MV Management API|MV Management API]]
- [[_COMMUNITY_Metrics Collection Pipeline|Metrics Collection Pipeline]]
- [[_COMMUNITY_Cluster Configuration|Cluster Configuration]]
- [[_COMMUNITY_System Architecture Overview|System Architecture Overview]]
- [[_COMMUNITY_Job Lifecycle Management|Job Lifecycle Management]]
- [[_COMMUNITY_DDL Generation|DDL Generation]]
- [[_COMMUNITY_MV Discovery|MV Discovery]]
- [[_COMMUNITY_Catalog Connection|Catalog Connection]]
- [[_COMMUNITY_Table Discovery|Table Discovery]]
- [[_COMMUNITY_Permission Settings|Permission Settings]]
- [[_COMMUNITY_Jobs Persistence|Jobs Persistence]]
- [[_COMMUNITY_Table Detail|Table Detail]]
- [[_COMMUNITY_Plugin Config|Plugin Config]]
- [[_COMMUNITY_Internal Database Queries|Internal Database Queries]]
- [[_COMMUNITY_BE Status Parsing|BE Status Parsing]]

## God Nodes (most connected - your core abstractions)
1. `query()` - 30 edges
2. `SchedulerService` - 19 edges
3. `collect_metrics()` - 16 edges
4. `Flask Backend (app)` - 14 edges
5. `cluster` - 8 edges
6. `alert_checker_loop()` - 7 edges
7. `dashboard.html Frontend SPA` - 7 edges
8. `get_db()` - 6 edges
9. `collect_metrics() orchestrator` - 6 edges
10. `load_config()` - 5 edges

## Surprising Connections (you probably didn't know these)
- `Single-Process Deployment` --rationale_for--> `Flask Backend (app)`  [INFERRED]
  FSD.md → app.py
- `Threaded Concurrent Collection` --rationale_for--> `collect_metrics() orchestrator`  [INFERRED]
  FSD.md → app.py
- `dashboard.html Frontend SPA` --conceptually_related_to--> `Cache Layer (CACHE/MV_CACHE/DB_CACHE)`  [INFERRED]
  static/dashboard.html → app.py
- `vis.js Dependency Graph` --conceptually_related_to--> `MV Discovery & Management`  [INFERRED]
  static/dashboard.html → app.py
- `3-Step Job Creation Wizard` --conceptually_related_to--> `Job Management (get_jobs, pause/resume/drop)`  [INFERRED]
  static/dashboard.html → app.py

## Hyperedges (group relationships)
- **Data Pipeline: Doris → collect → cache → API → UI** — app_collect_metrics, app_cache_layer, app_app, static_dashboard [INFERRED 0.95]
- **Alert System: detect → dedup → notify** — app_alert_system, fsd_alert_dedup, app_collect_metrics [INFERRED 0.95]
- **Job Scheduling: wizard → API → scheduler → persistence** — static_dashboard_job_wizard, app_job_management, scheduler_service_scheduler_service, data_scheduler_jobs [INFERRED 0.95]

## Communities (20 total, 6 thin omitted)

### Community 0 - "Alert & Monitoring System"
Cohesion: 0.13
Nodes (23): Alert System, Flask Backend (app), Cache Layer (CACHE/MV_CACHE/DB_CACHE), Catalog Management, collect_metrics() orchestrator, DDL Generation (generate_create_ddl), EnhancedEncoder (JSON datetime), Job Management (get_jobs, pause/resume/drop) (+15 more)

### Community 1 - "Flask API Routes"
Cohesion: 0.11
Nodes (13): api_catalog_alter(), api_catalog_create(), api_catalog_drop(), api_jobs(), api_jobs_catalogs(), api_jobs_databases(), api_jobs_tables(), api_mv_history() (+5 more)

### Community 3 - "MV Management API"
Cohesion: 0.12
Nodes (19): alert_checker_loop(), api_alert_config(), api_alert_test(), api_alter_mv(), api_config(), api_create_mv(), api_drop_mv(), api_refresh_mv() (+11 more)

### Community 4 - "Metrics Collection Pipeline"
Cohesion: 0.25
Nodes (14): api_jobs_execute_ddl(), api_metrics(), collect_metrics(), fetch_url(), get_be_metrics_all(), get_cluster_stats(), get_fe_metrics_all(), get_fe_status() (+6 more)

### Community 5 - "Cluster Configuration"
Cohesion: 0.18
Nodes (10): Config Management (load_config/save), cluster, be_http_port, connect_timeout, fe_http_port, host, password, port (+2 more)

### Community 6 - "System Architecture Overview"
Cohesion: 0.22
Nodes (9): Alert Engine, Browser SPA (dashboard.html + vis.js), Cache Layer, Config Management, Data Collection Module, Flask Backend (app.py), HTTP GET /metrics (FE 8030 / BE 8040), MySQL Protocol (FE/BE port 9030) (+1 more)

### Community 7 - "Job Lifecycle Management"
Cohesion: 0.29
Nodes (7): api_jobs_drop(), api_jobs_pause(), api_jobs_resume(), drop_job(), _exec_job_cmd(), pause_job(), resume_job()

### Community 8 - "DDL Generation"
Cohesion: 0.33
Nodes (6): api_jobs_columns(), api_jobs_preview(), _col_name(), generate_create_ddl(), get_table_columns(), map_doris_type()

### Community 9 - "MV Discovery"
Cohesion: 0.67
Nodes (3): discover_mvs(), _fetch_mv_ddls(), parse_mv_ddl()

### Community 10 - "Catalog Connection"
Cohesion: 0.67
Nodes (3): api_catalogs(), _parse_catalog_props(), Extract key-value properties from a CREATE CATALOG statement.

### Community 11 - "Table Discovery"
Cohesion: 0.67
Nodes (3): api_tables(), get_all_tables(), Discover all user tables across databases.

### Community 14 - "Table Detail"
Cohesion: 0.67
Nodes (3): api_table_detail(), get_table_detail(), Get DDL + columns for a specific table.

## Knowledge Gaps
- **25 isolated node(s):** `host`, `port`, `user`, `password`, `fe_http_port` (+20 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **6 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `EnhancedEncoder` connect `Job Scheduler Service` to `Flask API Routes`?**
  _High betweenness centrality (0.135) - this node is a cross-community bridge._
- **Why does `Flask Backend (app)` connect `Alert & Monitoring System` to `Cluster Configuration`?**
  _High betweenness centrality (0.033) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `Flask Backend (app)` (e.g. with `dashboard.html Frontend SPA` and `Single-Process Deployment`) actually correct?**
  _`Flask Backend (app)` has 2 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Discover all user tables across databases.`, `Get DDL + columns for a specific table.`, `Extract key-value properties from a CREATE CATALOG statement.` to the rest of the system?**
  _30 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Alert & Monitoring System` be split into smaller, more focused modules?**
  _Cohesion score 0.12681159420289856 - nodes in this community are weakly interconnected._
- **Should `Flask API Routes` be split into smaller, more focused modules?**
  _Cohesion score 0.1067193675889328 - nodes in this community are weakly interconnected._
- **Should `MV Management API` be split into smaller, more focused modules?**
  _Cohesion score 0.11695906432748537 - nodes in this community are weakly interconnected._