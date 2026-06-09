import json, os, re, time, threading, smtplib, ssl
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date
from email.mime.text import MIMEText
import pymysql, requests
from flask import Flask, jsonify, send_from_directory, request, Response
from flask_cors import CORS
from scheduler_service import SchedulerService

scheduler = None  # initialized in __main__

class EnhancedEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        try:
            return super().default(o)
        except TypeError:
            return str(o)

app = Flask(__name__, static_folder='static')
CORS(app)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)

def get_fe_config():
    return load_config()["cluster"]

CACHE = {"data": None, "timestamp": 0, "lock": threading.Lock()}
CACHE_TTL = 10
MV_CACHE = {"list": None, "timestamp": 0, "lock": threading.Lock()}
MV_CACHE_TTL = 30
DB_CACHE = {"databases": None, "timestamp": 0, "lock": threading.Lock()}
DB_CACHE_TTL = 60

# ─── Alert system ─────────────────────────────────────────

ALERT_DEFAULTS = {
    "enabled": False,
    "smtp_host": "", "smtp_port": 465,
    "smtp_user": "", "smtp_password": "",
    "sender_email": "", "recipients": "",
    "check_interval_seconds": 300,
}
_alert_known = set()
_alert_lock = threading.Lock()
_alert_thread = None

def load_alert_config():
    cfg = load_config()
    ac = cfg.get("alert", {})
    return {**ALERT_DEFAULTS, **ac}

def save_alert_config(ac):
    cfg = load_config()
    cfg["alert"] = ac
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

def send_email(subject, body, ac=None):
    if ac is None: ac = load_alert_config()
    if not ac.get("smtp_host") or not ac.get("recipients"): return False
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = ac["sender_email"] or ac["smtp_user"]
    msg["To"] = ac["recipients"]
    try:
        port = int(ac.get("smtp_port", 465))
        if port == 465:
            with smtplib.SMTP_SSL(ac["smtp_host"], port, timeout=10, context=ssl.create_default_context()) as s:
                if ac.get("smtp_user"): s.login(ac["smtp_user"], ac["smtp_password"] or "")
                s.send_message(msg)
        else:
            with smtplib.SMTP(ac["smtp_host"], port, timeout=10) as s:
                s.starttls(context=ssl.create_default_context())
                if ac.get("smtp_user"): s.login(ac["smtp_user"], ac["smtp_password"] or "")
                s.send_message(msg)
        return True
    except Exception:
        return False

def check_alerts(data):
    issues = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for fe in data.get("fe_status", []):
        if not fe.get("alive", True):
            issues.append(("fe_down", fe["host"], "FE %s (%s) 已宕机" % (fe.get("name",""), fe["host"])))
    for be in data.get("be_status", []):
        if not be.get("alive", True):
            issues.append(("be_down", be["host"], "BE %s (%s) 已宕机" % (be.get("backend_id",""), be["host"])))
        pct = be.get("used_pct", 0)
        if pct and pct > 85:
            issues.append(("be_disk", be["host"], "BE %s (%s) 磁盘使用率 %.1f%%" % (be.get("backend_id",""), be["host"], pct)))
    for mv in data.get("materialized_views", []):
        if mv.get("last_status") == "FAILED":
            key = "%s.%s" % (mv["database"], mv["name"])
            issues.append(("mv_fail", key, "MV %s 刷新失败" % key))
    health = data.get("tablet_health", {})
    if isinstance(health, dict):
        n = health.get("unhealthy_tablets", 0)
        if n > 0:
            issues.append(("unhealthy_tablets", "", "%d 个异常 Tablet" % n))
    for fe in data.get("fe_status", []):
        host = fe["host"]
        m = (data.get("fe_metrics") or {}).get(host, {})
        if m.get("jvm_heap_max_mb") and m.get("jvm_heap_used_mb"):
            pct = m["jvm_heap_used_mb"] / m["jvm_heap_max_mb"] * 100
            if pct > 90:
                issues.append(("fe_jvm", host, "FE %s JVM 堆使用率 %.0f%%" % (host, pct)))
    return issues

def build_alert_body(issues):
    lines = ["Doris 集群异常告警", "时间: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"), ""]
    groups = {"fe_down": "FE 节点", "be_down": "BE 节点", "be_disk": "磁盘使用率", "mv_fail": "物化视图", "unhealthy_tablets": "Tablet 健康", "fe_jvm": "FE JVM"}
    by_type = {}
    for tp, key, msg in issues:
        by_type.setdefault(tp, []).append("  - " + msg)
    for tp, title in groups.items():
        if tp in by_type:
            lines.append("■ " + title)
            lines.extend(by_type[tp])
            lines.append("")
    return "\n".join(lines)

def alert_checker_loop():
    while True:
        try:
            ac = load_alert_config()
            if not ac.get("enabled"):
                time.sleep(10); continue
            data = collect_metrics()
            data["tablet_health"] = get_tablet_health()
            issues = check_alerts(data)
            new_issue_keys = set(tp + ":" + key for tp, key, msg in issues)
            with _alert_lock:
                old_known = set(_alert_known)
                to_notify = new_issue_keys - old_known
                recovered = old_known - new_issue_keys
                _alert_known.clear()
                _alert_known.update(new_issue_keys)
            if to_notify and issues:
                filtered = [i for i in issues if (i[0] + ":" + i[1]) in to_notify]
                body = build_alert_body(filtered)
                if recovered:
                    body += "\n已恢复:\n" + "\n".join("  - " + r for r in sorted(recovered))
                send_email("Doris 集群异常告警", body, ac)
            time.sleep(max(30, ac.get("check_interval_seconds", 300)))
        except Exception:
            time.sleep(60)

def start_alert_checker():
    global _alert_thread
    if _alert_thread is None or not _alert_thread.is_alive():
        _alert_thread = threading.Thread(target=alert_checker_loop, daemon=True)
        _alert_thread.start()

# ─── DB helpers ───────────────────────────────────────────

def get_db():
    cfg = get_fe_config()
    return pymysql.connect(
        host=cfg["host"], port=cfg["port"], user=cfg["user"],
        password=cfg["password"], connect_timeout=5, read_timeout=10
    )

def query(sql):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            if cur.description is None:
                return []
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        conn.close()

def fetch_url(url, timeout=5):
    try:
        r = requests.get(url, timeout=timeout)
        return r.text
    except Exception:
        return None

def parse_capacity(val):
    if not val: return 0
    val = str(val).strip()
    if val in ('0.000','0'): return 0
    try:
        if 'TB' in val: return float(val.replace('TB','').strip())*1024
        if 'GB' in val: return float(val.replace('GB','').strip())
        if 'MB' in val: return float(val.replace('MB','').strip())/1024
        if 'KB' in val: return float(val.replace('KB','').strip())/1024/1024
        return float(val)
    except (ValueError, TypeError):
        return 0

# ─── FE / BE status ──────────────────────────────────────

def get_fe_status():
    rows = query("SHOW FRONTENDS")
    for r in rows:
        r["_isHealthy"] = r.get("Alive") == "true"
    # Process raw rows into structured output
    return [{
        "name": r.get("Name","")[:24],
        "host": r.get("Host",""),
        "role": r.get("Role",""),
        "is_master": r.get("IsMaster","")=="true",
        "alive": r.get("Alive","")=="true",
        "replayed_journal_id": int(r.get("ReplayedJournalId",0) or 0),
        "last_heartbeat": r.get("LastHeartbeat",""),
        "err_msg": r.get("ErrMsg",""),
        "version": r.get("Version",""),
        "journal_lag": int(r.get("ReplayedJournalId",0) or 0) and False,
    } for r in rows]

def get_be_status():
    rows = query("SHOW BACKENDS")
    result = []
    for r in rows:
        total = parse_capacity(r.get("TotalCapacity","0"))
        used = parse_capacity(r.get("AvailCapacity","0"))
        avail = used
        used_gb = total - avail
        used_pct = float(r.get("UsedPct","0").split("%")[0].strip()) if r.get("UsedPct") else 0
        result.append({
            "backend_id": r.get("BackendId",""),
            "host": r.get("Host",""),
            "alive": r.get("Alive","")=="true",
            "tablet_num": int(r.get("TabletNum",0) or 0),
            "total_capacity_gb": round(total,2),
            "used_capacity_gb": round(total - avail,2),
            "data_used_gb": round(parse_capacity(r.get("DataUsedCapacity","0")),2),
            "avail_capacity_gb": round(avail,2),
            "used_pct": round(used_pct,2),
            "max_disk_used_pct": f"{used_pct:.2f} %",
            "last_heartbeat": r.get("LastHeartbeat",""),
            "err_msg": r.get("ErrMsg",""),
            "version": r.get("Version",""),
        })
    return result

# ─── Statistics with per-db breakdown ────────────────────

def get_cluster_stats():
    rows = query("SHOW PROC '/statistic'")
    stats = {"db_num": 0, "table_num": 0, "partition_num": 0, "tablet_num": 0, "replica_num": 0, "per_db": []}
    for r in rows:
        if r.get("DbId") == "Total":
            stats["table_num"] = int(r.get("TableNum",0) or 0)
            stats["partition_num"] = int(r.get("PartitionNum",0) or 0)
            stats["tablet_num"] = int(r.get("TabletNum",0) or 0)
            stats["replica_num"] = int(r.get("ReplicaNum",0) or 0)
        else:
            stats["db_num"] += 1
            stats["per_db"].append({
                "name": r.get("DbName",""),
                "table_num": int(r.get("TableNum",0) or 0),
                "partition_num": int(r.get("PartitionNum",0) or 0),
                "tablet_num": int(r.get("TabletNum",0) or 0),
            })
    return stats

def get_tablet_health():
    rows = query("SHOW PROC '/cluster_health/tablet_health'")
    unhealthy = 0
    for r in rows:
        if r.get("DbId") == "Total": continue
        for key in r:
            if key.endswith("Num") and key not in ("TabletNum","HealthyNum"):
                unhealthy += int(r.get(key,0) or 0)
    return {"unhealthy_tablets": unhealthy}

# ─── FE metrics from HTTP ────────────────────────────────

def get_fe_metrics_all():
    fe_list = query("SHOW FRONTENDS")
    result = {}
    for fe in fe_list:
        host = fe.get("Host","")
        port = fe.get("HttpPort",8030)
        raw = fetch_url(f"http://{host}:{port}/metrics", timeout=3)
        if not raw:
            result[host] = {"host": host, "error": "无法连接"}
            continue
        m = {}
        for line in raw.split('\n'):
            line = line.strip()
            if line.startswith('#') or not line: continue
            parts = line.split()
            if len(parts) >= 2:
                m[parts[0]] = parts[-1]
        result[host] = {
            "host": host,
            "jvm_heap_used_mb": round(float(m.get("doris_fe_jvm{name=\"heap_used\"}",0)),1),
            "jvm_heap_max_mb": round(float(m.get("doris_fe_jvm{name=\"heap_max\"}",0)),1),
            "editlog_read": float(m.get("doris_fe_editlog{op=\"read\",status=\"ok\"}",0)),
            "editlog_write": float(m.get("doris_fe_editlog{op=\"write\",status=\"ok\"}",0)),
            "query_total": float(m.get("doris_fe_request_total",0)),
            "threads": float(m.get("doris_fe_thread_pool{name=\"agent-task-pool\",type=\"size\"}",0)),
        }
    return result

# ─── BE metrics from HTTP ────────────────────────────────

def get_be_metrics_all():
    be_list = query("SHOW BACKENDS")
    result = {}
    for be in be_list:
        host = be.get("Host","")
        port = be.get("HttpPort",8040)
        raw = fetch_url(f"http://{host}:{port}/metrics", timeout=3)
        if not raw:
            result[host] = {"host": host, "error": "无法连接"}
            continue
        m = {}
        for line in raw.split('\n'):
            line = line.strip()
            if line.startswith('#') or not line: continue
            parts = line.split(None, 1)
            if len(parts) == 2:
                m[parts[0]] = parts[-1]
        def get_val(key, default=0):
            for k, v in m.items():
                if k.startswith(key):
                    try: return float(v)
                    except: pass
            return default
        # Parse disks
        disks = []
        disk_pct_keys = [k for k in m if k.startswith("doris_be_disk_used_pct")]
        for key in disk_pct_keys:
            device = ""
            # Extract device from label
            mm = re.search(r'device="([^"]+)"', key)
            if mm: device = mm.group(1)
            if not device:
                mm = re.search(r"device='([^']+)'", key)
                if mm: device = mm.group(1)
            if device:
                total_key = next((k for k in m if k.startswith("doris_be_disk_total") and device in k), None)
                used_key = next((k for k in m if k.startswith("doris_be_disk_used") and device in k), None)
                total_gb = round(float(m.get(total_key, 0)) / (1024**3), 1) if total_key else 0
                used_gb = round(float(m.get(used_key, 0)) / (1024**3), 1) if used_key else 0
                disks.append({
                    "device": device,
                    "total_gb": total_gb,
                    "used_gb": used_gb,
                    "used_pct": round(float(m.get(key, 0)), 1),
                })
        result[host] = {
            "host": host,
            "avail_cpu_num": get_val("doris_be_avail_cpu_num"),
            "load_1m": get_val("doris_be_load_average"),
            "load_5m": 0,
            "process_thread_num": get_val("doris_be_thread_pool_active_threads"),
            "procs_running": 0,
            "memory_allocated_mb": round(get_val("doris_be_memory_allocated_bytes") / (1024**2), 1),
            "memory_jemalloc_mb": round(get_val("doris_be_memory_jemalloc_resident_bytes") / (1024**2), 1),
            "fd_used": get_val("doris_be_fd_num_used"),
            "fd_limit": get_val("doris_be_fd_num_limit"),
            "pipeline_task_queue_size": 0,
            "disks": [],  # No disk_pct exposed in this Doris version's /metrics
        }
    return result

# ─── Queries ─────────────────────────────────────────────

def get_queries():
    try:
        rows = query("SHOW FULL PROCESSLIST")
        return [{
            "query_id": q.get("QueryId",""),
            "user": q.get("User",""),
            "host": q.get("Host",""),
            "db": q.get("Db",""),
            "command": q.get("Command",""),
            "time": q.get("Time",0),
            "state": q.get("State",""),
            "info": (q.get("Info") or "")[:300],
            "scan_rows": q.get("ScanRows",""),
            "scan_bytes": q.get("ScanBytes",""),
            "mem_used": q.get("MemUsed",""),
            "start_time": q.get("StartTime",""),
        } for q in rows]
    except Exception:
        return []

# ─── MV ──────────────────────────────────────────────────

def parse_mv_ddl(create_sql):
    result = {"refreshType": "", "refreshInterval": "", "baseTables": [], "definition": ""}
    if "REFRESH AUTO ON COMMIT" in create_sql:
        result["refreshType"] = "AUTO ON COMMIT"
    elif "REFRESH COMPLETE ON SCHEDULE" in create_sql:
        result["refreshType"] = "SCHEDULE"
        m = re.search(r'EVERY\s+(\d+)\s+(MINUTE|HOUR|DAY|SECOND)', create_sql, re.IGNORECASE)
        if m: result["refreshInterval"] = f"{m.group(1)} {m.group(2)}"
    elif "REFRESH ON SCHEDULE" in create_sql:
        result["refreshType"] = "SCHEDULE"
    elif "REFRESH MANUAL" in create_sql:
        result["refreshType"] = "MANUAL"
    elif "REFRESH AUTO" in create_sql:
        result["refreshType"] = "AUTO"
    # Extract SELECT
    idx = -1
    for pat in ["\nAS SELECT", "\nAS\nSELECT", "AS SELECT", "\nAS select"]:
        i = create_sql.upper().rfind(pat)
        if i >= 0: idx = i; break
    if idx >= 0:
        select_part = create_sql[idx:]
        result["definition"] = select_part.strip()
        tables = set()
        upper = select_part.upper()
        for keyword, offset in [("FROM ",5), ("JOIN ",5)]:
            pos = 0
            while True:
                p = upper.find(keyword, pos)
                if p < 0: break
                rest = select_part[p+offset:].lstrip()
                if rest.startswith('('): pos = p+offset; continue
                end = len(rest)
                for d in (' ', ',', '\n', '\r', ';'):
                    di = rest.find(d)
                    if 0 <= di < end: end = di
                raw = rest[:end].strip().rstrip(',').replace('`','')
                if raw and not raw.startswith('('):
                    tables.add(raw)
                pos = p + offset
        result["baseTables"] = sorted(tables)
    return result

def discover_mvs(database=None):
    if database:
        rows = query(f"SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA='{database}' AND TABLE_NAME LIKE '%mv%'")
        names = [r.get("TABLE_NAME") for r in rows]
    else:
        rows = query("SELECT DISTINCT MvDatabaseName,MvName FROM tasks('type'='mv')")
        return [{"name":r.get("MvName",""),"database":r.get("MvDatabaseName","")} for r in rows if r.get("MvName")]
    if len(names) <= 2:
        return _fetch_mv_ddls(database, names)
    chunk_size = max(1, len(names)//5)
    chunks = [names[i:i+chunk_size] for i in range(0, len(names), chunk_size)]
    all_mvs = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        for f in as_completed({ex.submit(_fetch_mv_ddls,database,c):c for c in chunks}):
            try: all_mvs.extend(f.result())
            except: pass
    return all_mvs

def _fetch_mv_ddls(database, names):
    mvs = []
    for name in names:
        try:
            ddl_rows = query(f"SHOW CREATE MATERIALIZED VIEW {database}.{name}")
        except Exception:
            continue
        if not ddl_rows: continue
        create_sql = ddl_rows[0].get("Create Materialized View","")
        parsed = parse_mv_ddl(create_sql)
        mvs.append({"name":name,"database":database,"ddl":create_sql,
            "refresh_type":parsed["refreshType"],"refresh_interval":parsed["refreshInterval"],
            "base_tables":parsed["baseTables"],"definition":parsed["definition"]})
    return mvs

def get_mv_latest_tasks(database):
    try:
        rows = query(f"""
            SELECT t1.MvName,t1.Status,t1.FinishTime,t1.DurationMs,t1.CreateTime,t1.StartTime,
                   t1.RefreshMode,t1.Progress,t1.ErrorMsg
            FROM tasks('type'='mv') t1 INNER JOIN (
                SELECT MvName,MAX(CreateTime) as MaxTime FROM tasks('type'='mv')
                WHERE MvDatabaseName='{database}' GROUP BY MvName
            ) t2 ON t1.MvName=t2.MvName AND t1.CreateTime=t2.MaxTime
            WHERE t1.MvDatabaseName='{database}'
        """)
        return {r.get("MvName",""):{
            "status":r.get("Status",""),"finish_time":r.get("FinishTime",""),
            "duration_ms":int(r.get("DurationMs",0) or 0),"create_time":r.get("CreateTime",""),
            "start_time":r.get("StartTime",""),"refresh_mode":r.get("RefreshMode",""),
            "progress":r.get("Progress",""),"error_msg":r.get("ErrorMsg","")} for r in rows}
    except Exception:
        return {}

def get_mv_today_counts(database):
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        rows = query(f"SELECT MvName,COUNT(*) as cnt FROM tasks('type'='mv') WHERE MvDatabaseName='{database}' AND CreateTime>='{today}' GROUP BY MvName")
        return {r.get("MvName",""):int(r.get("cnt",0) or 0) for r in rows}
    except Exception:
        return {}

def get_mv_row_sizes(database, mv_names=None):
    try:
        if mv_names:
            names_q = ",".join("'"+n+"'" for n in mv_names)
            rows = query(f"SELECT TABLE_NAME,TABLE_ROWS,DATA_LENGTH FROM information_schema.TABLES WHERE TABLE_SCHEMA='{database}' AND TABLE_NAME IN ({names_q})")
        else:
            rows = query(f"SELECT TABLE_NAME,TABLE_ROWS,DATA_LENGTH FROM information_schema.TABLES WHERE TABLE_SCHEMA='{database}' AND TABLE_NAME LIKE '%mv%'")
        return {r.get("TABLE_NAME",""):{"row_count":int(r.get("TABLE_ROWS",0) or 0),"data_size_mb":round((int(r.get("DATA_LENGTH",0) or 0))/(1024**2),2)} for r in rows}
    except Exception:
        return {}

def build_mv_dep_map(mvs):
    mv_names = {mv["name"] for mv in mvs}
    dep_map = {}
    for mv in mvs:
        deps = []
        for bt in mv["base_tables"]:
            tbl = bt.split(".")[-1] if "." in bt else bt
            if tbl in mv_names: deps.append(tbl)
            else:
                for dm in mvs:
                    if dm["name"] == tbl or dm["name"] in bt:
                        deps.append(dm["name"])
        dep_map[mv["name"]] = list(set(deps))
    dep_map["_allMvNames"] = sorted(mv_names)
    return dep_map

def fetch_mv_history(db, name, limit=20):
    try:
        rows = query(f"SELECT * FROM tasks('type'='mv') WHERE MvDatabaseName='{db}' AND MvName='{name}' ORDER BY CreateTime DESC LIMIT {limit}")
        return [{
            "start_time": r.get("CreateTime", ""),
            "finish_time": r.get("FinishTime", ""),
            "duration_ms": r.get("DurationMs", 0),
            "status": r.get("Status", ""),
        } for r in rows]
    except Exception:
        return []

# ─── Tables ──────────────────────────────────────────────

def get_all_tables():
    """Discover all user tables across databases."""
    try:
        db_rows = query("SHOW DATABASES")
        if not db_rows:
            return []
    except Exception:
        return []
    sys_dbs = {"__internal_schema", "information_schema", "mysql", "sys", "_statistics_"}
    dbs = [r.get("Database","") for r in db_rows if not r.get("Database","").startswith("_") and r.get("Database","") not in sys_dbs]
    all_tables = []
    for db in dbs:
        try:
            rows = query(f"SELECT TABLE_NAME, TABLE_ROWS, DATA_LENGTH, CREATE_TIME, UPDATE_TIME, TABLE_COMMENT FROM information_schema.TABLES WHERE TABLE_SCHEMA='{db}' ORDER BY TABLE_ROWS DESC")
        except Exception:
            continue
        for r in rows:
            name = r.get("TABLE_NAME","")
            if name.startswith("mv_"):
                continue
            all_tables.append({
                "name": name,
                "database": db,
                "row_count": int(r.get("TABLE_ROWS",0) or 0),
                "data_size_mb": round((int(r.get("DATA_LENGTH",0) or 0))/(1024**2), 2),
                "create_time": (r.get("CREATE_TIME") or ""),
                "comment": (r.get("TABLE_COMMENT") or ""),
            })
    return all_tables

def get_table_detail(db, name, catalog=""):
    """Get DDL + columns for a specific table."""
    result = {"name": name, "database": db, "columns": [], "ddl": "", "partitions": []}
    tbl_ref = f"`{catalog}`.`{db}`.`{name}`" if catalog else f"`{db}`.`{name}`"
    try:
        col_rows = query(f"SHOW FULL COLUMNS FROM {tbl_ref}")
        result["columns"] = [{
            "field": c.get("Field",""), "type": c.get("Type",""),
            "key": c.get("Key",""), "extra": c.get("Extra",""),
            "default": c.get("Default",""), "comment": c.get("Comment",""),
        } for c in col_rows]
    except Exception:
        pass
    try:
        ddl_rows = query(f"SHOW CREATE TABLE {tbl_ref}")
        if ddl_rows:
            result["ddl"] = ddl_rows[0].get("Create Table","")
    except Exception:
        pass
    return result

# ─── Unified metrics ─────────────────────────────────────

def collect_metrics():
    fe_status = get_fe_status()
    be_status = get_be_status()
    statistic = get_cluster_stats()
    health = get_tablet_health()
    fe_metrics = get_fe_metrics_all()
    be_metrics = get_be_metrics_all()
    queries = get_queries()
    # Add journal_lag properly
    master_id = None
    for f in fe_status:
        if f["is_master"]:
            master_id = f["replayed_journal_id"]
    for f in fe_status:
        if master_id and not f["is_master"]:
            f["journal_lag"] = master_id - f["replayed_journal_id"]
        else:
            f["journal_lag"] = 0
    # Collect MV data from all databases that have MVs
    mv_dbs = []
    try:
        rows = query("SELECT DISTINCT MvDatabaseName FROM tasks('type'='mv') WHERE MvDatabaseName NOT IN ('__internal_schema')")
        mv_dbs = [r.get("MvDatabaseName","") for r in rows if r.get("MvDatabaseName")]
    except Exception:
        pass
    all_mvs = []
    all_tasks = []
    for db in mv_dbs:
        try:
            mvs = discover_mvs(database=db)
            if not mvs: continue
            tasks = get_mv_latest_tasks(database=db)
            today = get_mv_today_counts(database=db)
            sizes = get_mv_row_sizes(database=db, mv_names=[m["name"] for m in mvs])
            for mv in mvs:
                t = tasks.get(mv["name"], {})
                s = sizes.get(mv["name"], {})
                mv["daily_refresh_count"] = today.get(mv["name"], 0)
                mv["row_count"] = s.get("row_count", 0)
                mv["data_size_mb"] = s.get("data_size_mb", 0)
                mv["last_status"] = t.get("status", "")
                mv["last_finish_time"] = t.get("finish_time", "")
                mv["last_duration_ms"] = t.get("duration_ms", 0)
            all_mvs.extend(mvs)
        except Exception:
            pass
    return {
        "fe_status": fe_status,
        "be_status": be_status,
        "fe_metrics": fe_metrics,
        "be_metrics": be_metrics,
        "statistic": statistic,
        "materialized_views": all_mvs,
        "mv_tasks": [],
        "tables": get_all_tables(),
        "processlist": queries,
        "errors": [],
    }

# ─── Jobs (CREATE JOB scheduler) ────────────────────────

def get_jobs():
    queries = [
        'SELECT * FROM jobs("type"="insert")',
        "SELECT * FROM information_schema.jobs WHERE type = 'INSERT'",
        "SHOW JOBS",
    ]
    for sql in queries:
        try:
            rows = query(sql)
            if not rows:
                continue
            return [{
                "id": r.get("Id", r.get("JobId", 0)),
                "name": r.get("Name", r.get("JobName", "")),
                "status": r.get("Status", ""),
                "type": r.get("ExecuteType", r.get("Type", "")),
                "schedule": r.get("RecurringStrategy", r.get("Schedule", "")),
                "database": r.get("Database", r.get("DbName", "")),
                "execute_sql": r.get("ExecuteSql", ""),
                "create_time": r.get("CreateTime", ""),
                "error_msg": r.get("ErrorMsg", ""),
                "timeout": r.get("Timeout", ""),
                "comment": r.get("Comment", ""),
            } for r in rows]
        except Exception:
            continue
    return {"error": "当前 Doris 版本不支持查询 Job 调度信息"}

def _exec_job_cmd(cmd_template, job_name):
    # Try multiple WHERE syntaxes for compatibility
    for clause in [
        f"jobname = '{job_name}'",
        f"jobName = '{job_name}'",
        f"job_id = {job_name}",
        f"name = '{job_name}'",
    ]:
        try:
            query(f"{cmd_template} WHERE {clause}")
            return True, ""
        except Exception:
            continue
    return False, f"无法对 '{job_name}' 执行操作，当前 Doris 版本可能不支持"

def pause_job(job_name):
    return _exec_job_cmd("PAUSE JOB", job_name)

def resume_job(job_name):
    return _exec_job_cmd("RESUME JOB", job_name)

def drop_job(job_name):
    return _exec_job_cmd("DROP JOB", job_name)

# ─── Job creation helpers ──────────────────────────────

def get_catalogs():
    try:
        rows = query("SHOW CATALOGS")
        return [r.get("Catalog", r.get("CatalogName", r.get("name", ""))) for r in rows
                if r.get("Catalog", r.get("CatalogName", r.get("name", ""))) not in ("internal", "")]
    except Exception as e:
        return {"error": str(e)}

def get_catalog_databases(catalog):
    try:
        rows = query(f"SHOW DATABASES FROM `{catalog}`")
        return [r.get("Database", "") for r in rows if r.get("Database", "")]
    except Exception as e:
        return {"error": str(e)}

def get_catalog_tables(catalog, db):
    try:
        rows = query(f"SHOW TABLES FROM `{catalog}`.`{db}`")
        key = next(k for k in rows[0].keys() if k.lower() in ("tables_in_%s" % db.lower(), "table", "name"))
        return [r.get(key, "") for r in rows if r.get(key, "")]
    except Exception:
        try:
            rows = query(f"SELECT TABLE_NAME as name FROM information_schema.TABLES WHERE TABLE_CATALOG='{catalog}' AND TABLE_SCHEMA='{db}'")
            return [r.get("name", "") for r in rows if r.get("name", "")]
        except Exception as e:
            return {"error": str(e)}

def get_table_columns(catalog, db, table):
    # Try SHOW FULL COLUMNS first (works for both internal and catalog tables)
    try:
        rows = query(f"SHOW FULL COLUMNS FROM `{catalog}`.`{db}`.`{table}`")
        result = []
        for r in rows:
            col = {
                "name": r.get("Field", ""),
                "type": r.get("Type", ""),
                "comment": r.get("Comment", ""),
                "char_len": 0,
                "num_prec": 0,
                "num_scale": 0,
            }
            col["doris_type"] = map_doris_type(col)
            result.append(col)
        return result
    except Exception:
        pass
    # Fallback: information_schema
    try:
        cats_to_try = [catalog, "internal"]
        for cat in cats_to_try:
            rows = query(f"SELECT COLUMN_NAME, DATA_TYPE, COLUMN_COMMENT, IFNULL(CHARACTER_MAXIMUM_LENGTH, 0) as CHAR_LEN, IFNULL(NUMERIC_PRECISION, 0) as NUM_PREC, IFNULL(NUMERIC_SCALE, 0) as NUM_SCALE FROM information_schema.COLUMNS WHERE TABLE_CATALOG='{cat}' AND TABLE_SCHEMA='{db}' AND TABLE_NAME='{table}' ORDER BY ORDINAL_POSITION")
            if rows:
                result = []
                for r in rows:
                    col = {
                        "name": r.get("COLUMN_NAME", ""),
                        "type": r.get("DATA_TYPE", ""),
                        "comment": r.get("COLUMN_COMMENT", ""),
                        "char_len": int(r.get("CHAR_LEN", 0) or 0),
                        "num_prec": int(r.get("NUM_PREC", 0) or 0),
                        "num_scale": int(r.get("NUM_SCALE", 0) or 0),
                    }
                    col["doris_type"] = map_doris_type(col)
                    result.append(col)
                return result
    except Exception:
        pass
    return {"error": f"无法获取表 {catalog}.{db}.{table} 的列信息"}

def get_internal_databases():
    try:
        rows = query("SHOW DATABASES")
        sys_dbs = {"__internal_schema", "information_schema", "mysql", "sys", "_statistics_"}
        return [r.get("Database", "") for r in rows
                if r.get("Database", "") and not r.get("Database", "").startswith("_")
                and r.get("Database", "") not in sys_dbs]
    except Exception as e:
        return {"error": str(e)}

def _col_name(col):
    return col.get("target_name", col["name"])

def map_doris_type(col):
    raw = col["type"].strip().lower()
    m = re.match(r'(\w+)(?:\(([^)]*)\))?', raw)
    if not m:
        return "VARCHAR(65533)"
    base = m.group(1)
    params = m.group(2)
    if base in ("int", "integer", "tinyint", "smallint", "mediumint", "int unsigned", "tinyint unsigned", "smallint unsigned"):
        return "INT"
    if base in ("bigint", "bigint unsigned"):
        return "BIGINT"
    if base in ("varchar", "string", "text", "character varying", "varchar2"):
        if params and params.isdigit() and int(params) < 65533:
            return f"VARCHAR({params})"
        return "VARCHAR(65533)"
    if base in ("char",):
        if params and params.isdigit():
            return f"CHAR({params})"
        return "CHAR(1)"
    if base in ("decimal", "numeric", "number", "dec", "fixed"):
        if params:
            parts = params.split(",")
            p = min(int(parts[0].strip()), 38) if parts[0].strip().isdigit() else 38
            s = int(parts[1].strip()) if len(parts) > 1 and parts[1].strip().isdigit() else 0
        else:
            p, s = 38, 0
        return f"DECIMAL({p},{s})"
    if base in ("float",):
        return "FLOAT"
    if base in ("double", "real"):
        return "DOUBLE"
    if base in ("date",):
        return "DATE"
    if base in ("datetime", "timestamp", "timestamp without time zone", "timestamp with time zone", "datetime(6)", "datetime(3)"):
        return "DATETIME"
    if base in ("boolean", "bool", "tinyint(1)"):
        return "BOOLEAN"
    if base in ("array",):
        return "ARRAY<STRING>"
    return "VARCHAR(65533)"

def generate_create_ddl(target_db, target_table, columns, model="DUPLICATE",
                        key_columns=None, etime_enabled=True):
    col_defs_list = []
    for c in columns:
        col_defs_list.append(
            f"`{_col_name(c)}` {map_doris_type(c)}"
            + (f" COMMENT '{c['comment']}'" if c.get("comment") else "")
        )
    if etime_enabled:
        col_defs_list.append("`etl_time` DATETIME DEFAULT CURRENT_TIMESTAMP")
    col_defs = ",\n  ".join(col_defs_list)
    keys = [f"`{_col_name(c)}`" for c in columns
            if _col_name(c).lower() != "etl_time"
            and (not key_columns or any(k == _col_name(c) for k in (key_columns or [])))]
    if not keys:
        keys = [f"`{_col_name(columns[0])}`"] if columns else ["`id`"]
    key_str = ", ".join(keys)
    hash_key = keys[0]
    model_keyword = "UNIQUE KEY" if model.upper() == "UNIQUE" else "DUPLICATE KEY"
    return (f"CREATE TABLE IF NOT EXISTS `{target_db}`.`{target_table}` (\n"
            f"  {col_defs}\n"
            f") {model_keyword} ({key_str})\n"
            f"DISTRIBUTED BY HASH(`{hash_key.strip('`')}`) BUCKETS 1\n"
            f"PROPERTIES ('replication_num' = '1');")

def generate_create_job_sql(job_name, target_db, target_table, columns, source_catalog, source_db, source_table, schedule_value, schedule_unit, start_time):
    col_list = ", ".join(
        (f"`{c['name']}` AS `{c['target_name']}`" if c.get("target_name") and c["target_name"] != c["name"]
         else f"`{c['name']}`")
        for c in columns
    )
    return (f"CREATE JOB `{job_name}`\n"
            f"ON SCHEDULE EVERY {schedule_value} {schedule_unit} STARTS '{start_time}'\n"
            f"DO INSERT INTO `{target_db}`.`{target_table}`\n"
            f"SELECT {col_list} FROM `{source_catalog}`.`{source_db}`.`{source_table}`;")

# ─── Routes ──────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "dashboard.html")

@app.route("/api/ping")
def api_ping():
    return jsonify({"ok": True})

@app.route("/api/metrics")
def api_metrics():
    now = time.time()
    with CACHE["lock"]:
        if CACHE["data"] and (now - CACHE["timestamp"]) < CACHE_TTL:
            return jsonify(CACHE["data"])
    data = collect_metrics()
    with CACHE["lock"]:
        CACHE["data"] = data
        CACHE["timestamp"] = now
    return jsonify(data)

@app.route("/api/test-connection")
def api_test_connection():
    try:
        cfg = get_fe_config()
        conn = pymysql.connect(host=cfg["host"], port=cfg["port"], user=cfg["user"],
                               password=cfg["password"], connect_timeout=5)
        conn.close()
        return jsonify({"status": "ok", "message": "MySQL 连接成功"})
    except Exception as e:
        return jsonify({"status": "fail", "message": f"连接失败: {e}"})

@app.route("/api/mv-history")
def api_mv_history():
    db = request.args.get("db", "")
    name = request.args.get("name", "")
    if not name: return jsonify({"error": "name required"}), 400
    limit = request.args.get("limit", 20, type=int)
    history = fetch_mv_history(db, name, limit=limit)
    return jsonify({"history": history})

def execute_ddl(sql):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        return True, ""
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()

@app.route("/api/materialized-view", methods=["POST"])
def api_create_mv():
    data = request.get_json()
    database = (data.get("database") or "").strip()
    sql = (data.get("sql") or "").strip()
    if not database or not sql:
        return jsonify({"error": "database and sql required"}), 400
    ok, err = execute_ddl(f"USE `{database}`")
    if not ok: return jsonify({"error": f"USE failed: {err}"}), 400
    ok, err = execute_ddl(sql)
    if ok:
        return jsonify({"status": "ok", "message": "MV created"})
    return jsonify({"error": err}), 400

@app.route("/api/materialized-view", methods=["PUT"])
def api_alter_mv():
    data = request.get_json()
    database = (data.get("database") or "").strip()
    sql = (data.get("sql") or "").strip()
    if not database or not sql:
        return jsonify({"error": "database and sql required"}), 400
    ok, err = execute_ddl(f"USE `{database}`")
    if not ok: return jsonify({"error": f"USE failed: {err}"}), 400
    ok, err = execute_ddl(sql)
    if ok:
        return jsonify({"status": "ok", "message": "MV updated"})
    return jsonify({"error": err}), 400

@app.route("/api/materialized-view", methods=["DELETE"])
def api_drop_mv():
    database = request.args.get("db", "")
    name = request.args.get("name", "")
    if not database or not name:
        return jsonify({"error": "db and name required"}), 400
    ok, err = execute_ddl(f"DROP MATERIALIZED VIEW `{database}`.`{name}`")
    if ok:
        return jsonify({"status": "ok", "message": f"MV {name} dropped"})
    return jsonify({"error": err}), 400

@app.route("/api/materialized-view/refresh", methods=["POST"])
def api_refresh_mv():
    data = request.get_json()
    database = (data.get("database") or "").strip()
    name = (data.get("name") or "").strip()
    if not database or not name:
        return jsonify({"error": "database and name required"}), 400
    ok, err = execute_ddl(f"REFRESH MATERIALIZED VIEW `{database}`.`{name}` AUTO")
    if ok:
        return jsonify({"status": "ok", "message": f"MV {name} refresh triggered"})
    return jsonify({"error": err}), 400

@app.route("/api/materialized-view/toggle", methods=["POST"])
def api_toggle_mv():
    data = request.get_json()
    database = (data.get("database") or "").strip()
    name = (data.get("name") or "").strip()
    action = (data.get("action") or "").strip()
    if not database or not name or action not in ("pause", "resume"):
        return jsonify({"error": "database, name, and action (pause|resume) required"}), 400
    sql = f"ALTER MATERIALIZED VIEW `{database}`.`{name}` {'PAUSE' if action == 'pause' else 'RESUME'}"
    ok, err = execute_ddl(sql)
    if ok:
        return jsonify({"status": "ok", "message": f"MV {name} {action}d"})
    return jsonify({"error": err}), 400

@app.route("/api/tables")
def api_tables():
    tables = get_all_tables()
    return jsonify({"tables": tables})

@app.route("/api/table-detail")
def api_table_detail():
    db = request.args.get("db", "")
    name = request.args.get("name", "")
    catalog = request.args.get("catalog", "")
    if not name: return jsonify({"error": "name required"}), 400
    return jsonify(get_table_detail(db, name, catalog))

@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    if request.method == "GET":
        cfg = load_config()
        safe = {k: v for k, v in cfg["cluster"].items() if k != "password"}
        safe["password"] = "********" if cfg["cluster"].get("password") else ""
        safe["connect_timeout"] = cfg["cluster"].get("connect_timeout", 10)
        return jsonify({**safe, "refresh_interval_seconds": cfg.get("refresh_interval_seconds", 30)})
    data = request.get_json(force=True)
    cfg = load_config()
    pw = data.get("password", "")
    if not pw or pw == "********":
        pw = cfg["cluster"].get("password", "")
    cluster = {
        "host": data.get("host", ""), "port": int(data.get("port", 9030)),
        "user": data.get("user", ""), "password": pw,
        "fe_http_port": int(data.get("fe_http_port", 8030)),
        "be_http_port": int(data.get("be_http_port", 8040)),
        "connect_timeout": int(data.get("connect_timeout", 10)),
    }
    config = {"cluster": cluster, "refresh_interval_seconds": int(data.get("refresh_interval_seconds", 30))}
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    with CACHE["lock"]: CACHE["data"] = None; CACHE["timestamp"] = 0
    return jsonify({"status": "ok", "message": "配置已保存"})

@app.route("/api/alert-config", methods=["GET", "POST"])
def api_alert_config():
    if request.method == "GET":
        ac = load_alert_config()
        safe = {k: v for k, v in ac.items() if k != "smtp_password"}
        safe["smtp_password"] = "********" if ac.get("smtp_password") else ""
        return jsonify(safe)
    data = request.get_json(force=True)
    ac = {k: data.get(k, ALERT_DEFAULTS[k]) for k in ALERT_DEFAULTS}
    save_alert_config(ac)
    return jsonify({"status": "ok", "message": "告警配置已保存"})

@app.route("/api/alert-test", methods=["POST"])
def api_alert_test():
    data = request.get_json(force=True)
    ac = {k: data.get(k, ALERT_DEFAULTS[k]) for k in ALERT_DEFAULTS}
    ok = send_email("Doris 测试邮件", "这是一封测试邮件，来自 Doris 监控系统。\n时间: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"), ac)
    if ok:
        return jsonify({"status": "ok", "message": "测试邮件发送成功，请检查收件箱"})
    return jsonify({"status": "fail", "message": "发送失败，请检查 SMTP 配置"})

@app.route("/api/alert-issues")
def api_alert_issues():
    with _alert_lock:
        return jsonify({"known_issues": sorted(_alert_known)})

@app.route("/api/jobs")
def api_jobs():
    doris_jobs = []
    data = get_jobs()
    if not (isinstance(data, dict) and "error" in data):
        for j in data:
            j["source"] = "doris"
            doris_jobs.append(j)
    sched_jobs = []
    for j in scheduler.list_jobs():
        sched_jobs.append({
            "id": j["id"],
            "name": j["name"],
            "status": j["status"],
            "source": "scheduler",
            "schedule": f"EVERY {j['schedule']['value']} {j['schedule']['unit']}",
            "database": j.get("target_db", ""),
            "execute_sql": j.get("sql", ""),
            "mode": j.get("mode", "full_refresh"),
            "create_time": j.get("created_at", ""),
            "last_run": j.get("last_run", ""),
            "run_count": j.get("run_count", 0),
            "next_run": j.get("next_run", ""),
            "last_watermark": j.get("last_watermark", ""),
        })
    return jsonify({"jobs": doris_jobs + sched_jobs})

@app.route("/api/jobs/pause", methods=["POST"])
def api_jobs_pause():
    body = request.get_json(force=True)
    source = body.get("source", "doris")
    if source == "scheduler":
        jid = body.get("id", "")
        if not jid:
            return jsonify({"status": "fail", "message": "缺少 id"}), 400
        ok = scheduler.pause_job(jid)
        return jsonify({"status": "ok" if ok else "fail", "message": "已暂停" if ok else "Job 不存在"})
    name = body.get("name")
    if not name:
        return jsonify({"status": "fail", "message": "缺少 job name"}), 400
    ok, msg = pause_job(name)
    return jsonify({"status": "ok" if ok else "fail", "message": msg or "已暂停"})

@app.route("/api/jobs/resume", methods=["POST"])
def api_jobs_resume():
    body = request.get_json(force=True)
    source = body.get("source", "doris")
    if source == "scheduler":
        jid = body.get("id", "")
        if not jid:
            return jsonify({"status": "fail", "message": "缺少 id"}), 400
        ok = scheduler.resume_job(jid)
        return jsonify({"status": "ok" if ok else "fail", "message": "已恢复" if ok else "Job 不存在"})
    name = body.get("name")
    if not name:
        return jsonify({"status": "fail", "message": "缺少 job name"}), 400
    ok, msg = resume_job(name)
    return jsonify({"status": "ok" if ok else "fail", "message": msg or "已恢复"})

@app.route("/api/jobs/drop", methods=["POST"])
def api_jobs_drop():
    body = request.get_json(force=True)
    source = body.get("source", "doris")
    if source == "scheduler":
        jid = body.get("id", "")
        if not jid:
            return jsonify({"status": "fail", "message": "缺少 id"}), 400
        ok = scheduler.drop_job(jid)
        return jsonify({"status": "ok" if ok else "fail", "message": "已删除" if ok else "Job 不存在"})
    name = body.get("name")
    if not name:
        return jsonify({"status": "fail", "message": "缺少 job name"}), 400
    ok, msg = drop_job(name)
    return jsonify({"status": "ok" if ok else "fail", "message": msg or "已删除"})

@app.route("/api/jobs/catalogs")
def api_jobs_catalogs():
    data = get_catalogs()
    if isinstance(data, dict) and "error" in data:
        return jsonify({"error": data["error"], "catalogs": []})
    return jsonify({"catalogs": data})

@app.route("/api/jobs/databases")
def api_jobs_databases():
    catalog = request.args.get("catalog", "")
    if not catalog:
        return jsonify({"error": "缺少 catalog", "databases": []}), 400
    data = get_catalog_databases(catalog)
    if isinstance(data, dict) and "error" in data:
        return jsonify({"error": data["error"], "databases": []})
    return jsonify({"databases": data})

@app.route("/api/jobs/tables")
def api_jobs_tables():
    catalog = request.args.get("catalog", "")
    db = request.args.get("db", "")
    if not catalog or not db:
        return jsonify({"error": "缺少 catalog 或 db", "tables": []}), 400
    data = get_catalog_tables(catalog, db)
    if isinstance(data, dict) and "error" in data:
        return jsonify({"error": data["error"], "tables": []})
    return jsonify({"tables": data})

@app.route("/api/jobs/columns")
def api_jobs_columns():
    catalog = request.args.get("catalog", "")
    db = request.args.get("db", "")
    table = request.args.get("table", "")
    if not catalog or not db or not table:
        return jsonify({"error": "缺少 catalog/db/table", "columns": []}), 400
    data = get_table_columns(catalog, db, table)
    if isinstance(data, dict) and "error" in data:
        return jsonify({"error": data["error"], "columns": []})
    return jsonify({"columns": data})

@app.route("/api/jobs/internal-dbs")
def api_jobs_internal_dbs():
    data = get_internal_databases()
    if isinstance(data, dict) and "error" in data:
        return jsonify({"error": data["error"], "databases": []})
    return jsonify({"databases": data})

@app.route("/api/jobs/preview", methods=["POST"])
def api_jobs_preview():
    body = request.get_json(force=True)
    columns = body.get("columns", [])
    target_db = body.get("target_db", "")
    target_table = body.get("target_table", "")
    model = body.get("model", "DUPLICATE")
    key_columns = body.get("key_columns", None)
    etime_enabled = body.get("etime_enabled", True)
    if not columns or not target_db or not target_table:
        return jsonify({"error": "缺少参数"}), 400
    ddl = generate_create_ddl(target_db, target_table, columns, model, key_columns, etime_enabled)
    return jsonify({"ddl": ddl})

@app.route("/api/jobs/execute-ddl", methods=["POST"])
def api_jobs_execute_ddl():
    body = request.get_json(force=True)
    sql = body.get("sql", "")
    if not sql:
        return jsonify({"status": "fail", "message": "缺少 SQL"}), 400
    try:
        query(sql)
        return jsonify({"status": "ok", "message": "DDL 执行成功"})
    except Exception as e:
        return jsonify({"status": "fail", "message": str(e)})

@app.route("/api/jobs/create", methods=["POST"])
def api_jobs_create():
    body = request.get_json(force=True)
    sql = body.get("sql", "")
    if not sql:
        return jsonify({"status": "fail", "message": "SQL 不能为空"}), 400
    try:
        job_def = {
            "name": body["name"],
            "target_db": body["target_db"],
            "mode": body.get("mode", "full_refresh"),
            "sql": sql,
            "schedule_value": int(body.get("schedule_value", 10)),
            "schedule_unit": body.get("schedule_unit", "MINUTE"),
            "start_time": body.get("start_time", ""),
            "watermark_column": body.get("watermark_column"),
            "watermark_type": body.get("watermark_type"),
        }
        if not job_def["name"] or not job_def["target_db"] or not job_def["start_time"]:
            return jsonify({"status": "fail", "message": "参数不完整: name/target_db/start_time"}), 400
        jid = scheduler.add_job(job_def)
        return jsonify({"status": "ok", "message": "调度任务创建成功", "job_id": jid, "job_sql": sql})
    except (KeyError, TypeError, ValueError) as e:
        return jsonify({"status": "fail", "message": f"参数错误: {e}"}), 400
    except Exception as e:
        return jsonify({"status": "fail", "message": str(e)})

@app.route("/api/jobs/execute", methods=["POST"])
def api_jobs_execute():
    body = request.get_json(force=True)
    jid = body.get("id", "")
    if not jid:
        return jsonify({"status": "fail", "message": "缺少 id"}), 400
    ok, msg = scheduler.execute_now(jid)
    return jsonify({"status": "ok" if ok else "fail", "message": "执行成功" if ok else msg})

# ─── Catalog Management ───────────────────────────────

def _parse_catalog_props(create_sql):
    """Extract key-value properties from a CREATE CATALOG statement."""
    props = {}
    m = re.search(r'PROPERTIES\s*\(([\s\S]*)\)\s*;?\s*$', create_sql, re.IGNORECASE)
    if m:
        for match in re.finditer(r"""(['"])([^'"]+)\1\s*=\s*\1([^'"]*)\1""", m.group(1)):
            props[match.group(2)] = match.group(3)
    return props

@app.route("/api/catalogs")
def api_catalogs():
    try:
        rows = query("SHOW CATALOGS")
        catalogs = []
        for r in rows:
            name = r.get("Catalog", r.get("CatalogName", r.get("name", "")))
            if not name or name == "internal":
                continue
            ctype = r.get("Type", r.get("CatalogType", ""))
            entry = {"name": name, "type": ctype, "properties": {}, "create_sql": ""}
            try:
                cr = query(f"SHOW CREATE CATALOG `{name}`")
                if cr:
                    sql_text = cr[0].get("Create Catalog", cr[0].get("CreateCatalog", ""))
                    entry["create_sql"] = sql_text
                    entry["properties"] = _parse_catalog_props(sql_text)
            except Exception:
                pass
            catalogs.append(entry)
        return jsonify({"catalogs": catalogs})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/catalogs/test", methods=["POST"])
def api_catalog_test():
    import socket as _socket
    data = request.get_json(force=True)
    props = data.get("properties", {})
    if not props:
        return jsonify({"error": "Properties are required"}), 400
    ctype = props.get("type", "")

    if ctype == "jdbc":
        jdbc_url = props.get("jdbc_url", "")
        user = props.get("user", "")
        password = props.get("password", "")
        m = re.search(r'jdbc:mysql://([^:/]+)(?::(\d+))?(?:/([^?]+))?', jdbc_url)
        if not m:
            return jsonify({"status": "fail", "message": "无法解析 JDBC URL，目前仅支持 MySQL 类型"})
        host, port, db = m.group(1), int(m.group(2) or 3306), (m.group(3) or "")
        try:
            conn = pymysql.connect(host=host, port=port, user=user, password=password, connect_timeout=5, database=db)
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            conn.close()
            return jsonify({"status": "ok", "message": "JDBC 连接成功 (SELECT 1 OK)"})
        except Exception as e:
            return jsonify({"status": "fail", "message": f"JDBC 连接失败: {e}"})

    elif ctype in ("hms",):
        uris_str = props.get("hive.metastore.uris", "")
        m = re.search(r'thrift://([^:/]+):(\d+)', uris_str)
        if not m:
            return jsonify({"status": "fail", "message": "无法解析 hive.metastore.uris"})
        host, port = m.group(1), int(m.group(2))
        try:
            s = _socket.create_connection((host, port), timeout=5)
            s.close()
            return jsonify({"status": "ok", "message": f"HMS 端口可达 ({host}:{port})"})
        except Exception as e:
            return jsonify({"status": "fail", "message": f"HMS 连接失败: {e}"})

    elif ctype == "es":
        hosts = props.get("elasticsearch.hosts", "")
        if not hosts:
            return jsonify({"status": "fail", "message": "缺少 elasticsearch.hosts"})
        try:
            r = requests.get(hosts, timeout=5, auth=(props.get("user",""), props.get("password","")) if props.get("user") else None)
            return jsonify({"status": "ok" if r.ok else "fail", "message": f"ES 响应: HTTP {r.status_code}" if not r.ok else "ES 连接成功"})
        except Exception as e:
            return jsonify({"status": "fail", "message": f"ES 连接失败: {e}"})

    elif ctype in ("iceberg",):
        ice_type = props.get("iceberg.catalog.type", "")
        if ice_type == "hms":
            uris_str = props.get("hive.metastore.uris", "")
            m = re.search(r'thrift://([^:/]+):(\d+)', uris_str)
            if m:
                host, port = m.group(1), int(m.group(2))
                try:
                    s = _socket.create_connection((host, port), timeout=5); s.close()
                    return jsonify({"status": "ok", "message": f"Iceberg HMS 端口可达 ({host}:{port})"})
                except Exception as e:
                    return jsonify({"status": "fail", "message": f"Iceberg HMS 连接失败: {e}"})
        return jsonify({"status": "fail", "message": "不支持的 Iceberg catalog type，暂仅支持 hms"})

    elif ctype == "max_compute":
        return jsonify({"status": "ok", "message": "MaxCompute 暂不支持自动测试，请手动验证"})

    elif ctype == "paimon":
        paimon_type = props.get("paimon.catalog.type", "")
        if paimon_type == "hms":
            uris_str = props.get("hive.metastore.uris", "")
            m = re.search(r'thrift://([^:/]+):(\d+)', uris_str)
            if m:
                host, port = m.group(1), int(m.group(2))
                try:
                    s = _socket.create_connection((host, port), timeout=5); s.close()
                    return jsonify({"status": "ok", "message": f"Paimon HMS 端口可达 ({host}:{port})"})
                except Exception as e:
                    return jsonify({"status": "fail", "message": f"Paimon HMS 连接失败: {e}"})
        return jsonify({"status": "fail", "message": "不支持的 Paimon catalog type，暂仅支持 hms"})

    else:
        return jsonify({"status": "ok", "message": f"Catalog 类型 '{ctype}' 暂不支持自动测试"})

@app.route("/api/catalogs", methods=["POST"])
def api_catalog_create():
    data = request.get_json(force=True)
    name = data.get("name", "").strip()
    props = data.get("properties", {})
    if not name:
        return jsonify({"error": "Catalog name is required"}), 400
    if not props:
        return jsonify({"error": "At least one property required"}), 400
    props_str = ", ".join([f'"{k}" = "{v}"' for k, v in props.items()])
    sql = f"CREATE CATALOG `{name}` PROPERTIES ({props_str})"
    try:
        query(sql)
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/catalogs/<name>", methods=["PUT"])
def api_catalog_alter(name):
    data = request.get_json(force=True)
    props = data.get("properties", {})
    if not props:
        return jsonify({"error": "No properties to update"}), 400
    for k, v in props.items():
        sql = f"ALTER CATALOG `{name}` SET PROPERTIES ('{k}' = '{v}')"
        try:
            query(sql)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return jsonify({"status": "ok"})

@app.route("/api/catalogs/<name>", methods=["DELETE"])
def api_catalog_drop(name):
    try:
        query(f"DROP CATALOG `{name}`")
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    import scheduler_service as _ss
    scheduler = _ss.SchedulerService(get_db)
    scheduler.start()
    cfg = get_fe_config()
    print(f"  Doris Monitor @ http://localhost:5000")
    start_alert_checker()
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
