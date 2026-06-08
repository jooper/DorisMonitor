# Doris Monitor — 功能规格说明书 (FSD)

**版本**: 1.0  
**项目**: `doris_mt_pro`  
**定位**: Apache Doris 集群实时监控与管理 Web 面板

---

## 1. 项目概述

基于 Python Flask 的单进程 Web 应用，通过 MySQL 协议和 HTTP 接口采集 Apache Doris 集群的 FE/BE 节点状态、资源指标、查询信息、物化视图状态等数据，提供可视化监控面板与邮件告警功能。零外部前端构建工具，开箱即用。

### 1.1 技术栈

| 层级 | 技术 |
|---|---|
| 后端 | Python 3 + Flask + PyMySQL + Requests |
| 前端 | 原生 HTML5 + CSS3 + JavaScript (ES5) |
| 图谱 | vis.js 4.21 (CDN) |
| 通信 | RESTful JSON API |
| 部署 | 单进程，`python app.py` 启动 |

---

## 2. 系统架构

```
┌─────────────────────────────────────────────────────┐
│                   浏览器 (SPA)                        │
│  dashboard.html — vis.js 关系图谱                     │
└──────────────────────┬──────────────────────────────┘
                       │ HTTP REST API (JSON)
┌──────────────────────▼──────────────────────────────┐
│                  Flask Backend (app.py)               │
│  ┌─────────┐ ┌──────────┐ ┌────────┐ ┌───────────┐  │
│  │ 数据采集 │ │ 缓存层   │ │ 告警引擎│ │ 配置管理  │  │
│  └────┬────┘ └──────────┘ └────────┘ └───────────┘  │
└───────┼──────────────────────────────────────────────┘
        │
  ┌─────┴───────┬──────────────────┐
  │ MySQL协议    │ HTTP GET         │
  ▼              ▼                  ▼
 FE / BE     FE/BE HTTP         SMTP 邮件
 (9030)      /metrics (8030/8040)
```

---

## 3. 后端功能模块

### 3.1 数据采集层

所有采集函数通过 `collect_metrics()` 统一编排，返回全量数据集。

| 函数 | 数据来源 | 采集方式 | 返回内容 |
|---|---|---|---|
| `get_fe_status()` | `SHOW FRONTENDS` | MySQL | Name, Host, Role, IsMaster, Alive, ReplayedJournalId, LastHeartbeat, ErrMsg, Version |
| `get_be_status()` | `SHOW BACKENDS` | MySQL | BackendId, Host, Alive, TabletNum, 容量(GB), 使用率%, LastHeartbeat, ErrMsg |
| `get_cluster_stats()` | `SHOW PROC '/statistic'` | MySQL | 库/表/分区/Tablet/Replica 总数 + 按库明细 |
| `get_tablet_health()` | `SHOW PROC '/cluster_health/tablet_health'` | MySQL | 异常 Tablet 数量 |
| `get_fe_metrics_all()` | FE HTTP `/metrics` | HTTP GET | JVM Heap (used/max), editlog (read/write), query_total, threads |
| `get_be_metrics_all()` | BE HTTP `/metrics` | HTTP GET | CPU, load, threads, memory, fd, 各磁盘使用率 |
| `get_queries()` | `SHOW FULL PROCESSLIST` | MySQL | QueryId, User, Host, Db, Time, State, SQL, ScanRows, ScanBytes, MemUsed |
| `discover_mvs()` | `tasks('type'='mv')` + `information_schema` | MySQL | MV名称/库/DDL/刷新类型/基表依赖 |
| `get_mv_latest_tasks()` | `tasks('type'='mv')` 自关联取最新 | MySQL | Status, FinishTime, DurationMs, ErrorMsg |
| `get_all_tables()` | `information_schema.TABLES` (排除MV) | MySQL | 名称/库/行数/大小/创建时间/备注 |
| `get_table_detail()` | `SHOW FULL COLUMNS` + `SHOW CREATE TABLE` | MySQL | 列定义 + DDL |
| `get_jobs()` | `SHOW JOBS` | MySQL | ID/Name/Status/Type/Schedule/DB/ExecuteSql/ErrorMsg |
| `pause_job()` | `PAUSE JOB WHERE job_id = ...` | MySQL | 暂停定时任务 |
| `resume_job()` | `RESUME JOB WHERE job_id = ...` | MySQL | 恢复定时任务 |
| `drop_job()` | `DROP JOB WHERE job_id = ...` | MySQL | 删除定时任务 |

### 3.2 缓存策略

| 缓存 | TTL | 用途 |
|---|---|---|
| 主指标 (CACHE) | 10s | `/api/metrics` 全量数据 |
| MV 列表 (MV_CACHE) | 30s | 物化视图发现 |
| 数据库列表 (DB_CACHE) | 60s | 数据库名称枚举 |

> 缓存基于内存字典 + 时间戳 + 线程锁，非分布式友好。

### 3.3 告警系统

- **后台线程**: `alert_checker_loop()` — daemon 模式常驻
- **检测项**:
  - FE 节点宕机
  - BE 节点宕机
  - BE 磁盘使用率 > 85%
  - 物化视图刷新失败 (last_status == "FAILED")
  - 异常 Tablet 数 > 0
  - FE JVM 堆使用率 > 90%
- **去重机制**: 基于 `类型:key` 的集合对比，只有**新出现**或**已恢复**的问题才触发邮件
- **发送方式**: SMTP (SSL 465 / STARTTLS)，支持认证
- **检查间隔**: 默认 300s，可配置（ALERT_DEFAULTS）

### 3.4 API 接口

| 路由 | 方法 | 参数 | 功能 |
|---|---|---|---|
| `/` | GET | — | 服务静态首页 dashboard.html |
| `/api/ping` | GET | — | 健康检查，返回 `{"ok": true}` |
| `/api/metrics` | GET | — | 全量集群指标（含缓存） |
| `/api/test-connection` | GET | — | 测试 MySQL 连接 |
| `/api/config` | GET | — | 读取集群配置（密码脱敏） |
| `/api/config` | POST | JSON body | 保存集群配置，清空缓存 |
| `/api/alert-config` | GET | — | 读取告警配置（密码脱敏） |
| `/api/alert-config` | POST | JSON body | 保存告警配置 |
| `/api/alert-test` | POST | JSON body | 发送测试告警邮件 |
| `/api/alert-issues` | GET | — | 当前已知告警列表 |
| `/api/mv-history` | GET | `db`, `name` | 指定 MV 的刷新历史 (limit 20) |
| `/api/tables` | GET | — | 全量数据表列表 |
| `/api/table-detail` | GET | `db`, `name` | 表 DDL + 列定义 |
| `/api/jobs` | GET | — | 查询所有 CREATE JOB 定时任务 |
| `/api/jobs/pause` | POST | `name` | 暂停指定 Job（按名称） |
| `/api/jobs/resume` | POST | `name` | 恢复指定 Job（按名称） |
| `/api/jobs/drop` | POST | `name` | 删除指定 Job（按名称） |
| `/api/jobs/catalogs` | GET | — | 列出所有 Catalog（排除 internal） |
| `/api/jobs/databases` | GET | `catalog` | 列出指定 Catalog 下的数据库 |
| `/api/jobs/tables` | GET | `catalog`, `db` | 列出指定数据库下的表 |
| `/api/jobs/columns` | GET | `catalog`, `db`, `table` | 获取表列定义（SHOW FULL COLUMNS） |
| `/api/jobs/internal-dbs` | GET | — | 列出 Doris 内部库（排除系统库） |
| `/api/jobs/preview` | POST | `columns`, `target_db`, `target_table` | 生成建表 DDL 预览 |
| `/api/jobs/execute-ddl` | POST | `sql` | 执行任意 DDL 语句 |
| `/api/jobs/create` | POST | 完整配置 | 创建调度任务（CREATE JOB） |

### 3.5 配置存储

文件 `config.json`，示例结构：

```json
{
  "cluster": {
    "host": "10.11.2.101",
    "port": 9030,
    "user": "admin",
    "password": "bigdata@",
    "fe_http_port": 8030,
    "be_http_port": 8040,
    "connect_timeout": 10
  },
  "refresh_interval_seconds": 30,
  "alert": {
    "enabled": false,
    "smtp_host": "",
    "smtp_port": 465,
    "smtp_user": "",
    "smtp_password": "",
    "sender_email": "",
    "recipients": "",
    "check_interval_seconds": 300
  }
}
```

---

## 4. 前端功能模块

### 4.1 页面布局

```
┌─────────────────────────────────────────────────────┐
│ Titlebar: 窗口控制 · 标题 · 刷新状态指示器            │
├──────────┬──────────────────────────────────────────┤
│ Sidebar  │ Content (标签页切换)                      │
│          │                                          │
│ ● 集群   │ 集群 / 物化视图 / 数据表 / 关系图谱 /        │
│ ● 物化   │ 作业调度 / 设置                             │
│ 视图     │                                          │
│ ● 数据表 │                                          │
│ ● 关系   │                                          │
│ 图谱     │                                          │
│ ● 作业   │                                          │
│ 调度     │                                          │
│ ● 设置   │                                          │
└──────────┴──────────────────────────────────────────┘
```

### 4.2 页面说明

#### 4.2.1 集群概览 (tab: cluster)

- **概要卡片**: FE/BE健康数、表数、活跃查询数
- **FE 节点表**: Name / IP / Role / Leader标识 / Alive状态(绿/红点) / Journal Lag(色阶) / 上次心跳 / 错误信息
- **BE 节点表**: IP / Alive状态 / Tablet数 / 磁盘用量(GB) / 使用率(柱条+百分比) / 错误信息
- **统计卡片**: 数据库数 / 表数 / 分区数 / Tablet数 / Replica数（含各库明细）
- **FE 资源卡片**: 每个FE的JVM堆内存(used/max/百分比) / 线程数 / 总请求量
- **BE 资源卡片**: 每个BE的Load / CPU核数 / Memory / 线程数 / 各磁盘使用率柱条
- **活跃查询表**: QueryID / User / Host / DB / 开始时间 / 运行时长 / State / SQL摘要 / ScanRows / ScanBytes / Mem — 点击行弹窗显示完整SQL

#### 4.2.2 物化视图 (tab: mv)

- **概览卡片**: MV总数 / 健康数 / 失败数 / 刷新类型分布
- **筛选栏**: 数据库下拉 / 刷新类型下拉 / 关键词搜索
- **MV 表格**: Name / Database / Status(OK/Failed/Running 色点) / RefreshType / Interval / 依赖表数 / 今日刷新次数 / 行数 / 大小 / 最近耗时 / 最后刷新时间
- **MV 详情弹窗**:
  - 依赖关系（区分"上游MV"和"基表"）
  - DDL 完整展示
  - 最近刷新历史表（时间/状态/耗时/模式/进度）

#### 4.2.3 数据表 (tab: tables)

- **概览卡片**: 表总数 / 总行数 / 总大小
- **筛选栏**: 数据库下拉 / 关键词搜索
- **可排序表格**: Name / Database / Rows(排序) / Size(排序) / CreateTime / Comment
- **表格详情弹窗**: 列定义表(Field/Type/Key/Default/Extra/Comment) + DDL

#### 4.2.4 作业调度 (tab: jobs)

- **概览卡片**: Job 总数 / Running / Paused / Stopped
- **筛选栏**: 状态下拉 / 关键词搜索
- **Job 表格**: ID / Name / Status(色点) / Type / Schedule / Database / CreateTime / **操作按钮**
  - ▶ 恢复 (仅 PAUSED 状态显示)
  - ⏸ 暂停 (仅 RUNNING 状态显示)
  - ✕ 删除 (所有状态显示，带确认弹窗)
- **Job 详情弹窗**: 显示完整 Execute SQL、Schedule 定义、Timeout、ErrorMsg、Comment
- **"＋创建作业" 按钮**: 打开三步骤创建面板
  - **Step 1 — 选择数据源**: Catalog / Database / Table 三下拉框水平排列，选表后自动加载列信息，每列显示"源类型 → Doris 类型"映射，支持勾选同步列（全选/取消）
  - **Step 2 — 创建目标表**: 选择目标 Internal DB，通过**前缀 + 源表名 + 后缀**自定义目标表名（默认前缀 `ods_{源库名}_`，默认后缀 `_df`），DDL 预览自动将源列类型映射为 Doris 兼容类型（`varchar(1000)` → `VARCHAR(1000)`、`int` → `INT`、`text` → `VARCHAR(65533)` 等），点击"执行建表"调用 `execute-ddl` API
  - **Step 3 — 创建调度**: 配置作业名称、调度频率（分钟/小时/天）、开始时间，预览 CREATE JOB SQL（使用 `INSERT INTO`，因该 Doris 版本 CREATE JOB 不支持 `INSERT OVERWRITE`），确认后调用 `create` API

#### 4.2.5 关系图谱 (tab: graph)

- **筛选栏**: 数据库下拉 / 指定MV下拉
- **vis.js 层次化有向图** (方向: UD, 上→下):
  - MV节点：绿色椭圆
  - 基表节点：蓝色圆角矩形
  - 边：箭头从MV指向依赖表
  - 图例: 物化视图 / 基表
  - 物理引擎禁用，纯层次布局
- **交互**: 点击MV节点→MV详情弹窗 / 点击基表→被哪些MV引用列表

#### 4.2.6 设置 (tab: config)

- **集群连接配置**: Host / MySQL Port / Username / Password / FE HTTP Port / BE HTTP Port / Connect Timeout / 刷新间隔 → 保存 + 测试连接按钮
- **邮件告警配置**: 启用开关 / SMTP Host / Port / User / Password / 发件人 / 收件人 / 检查间隔 → 保存 + 测试邮件按钮

### 4.3 前端交互特性

| 特性 | 实现 |
|---|---|
| 自动轮询 | `setInterval` 定时请求 `/api/metrics`，间隔保存在 localStorage |
| macOS 风格 | SF/PingFang 字体、半透明模糊标题栏、圆角卡片、信使绿/蓝/红色系 |
| 刷新指示器 | 绿点(正常) / 黄点脉冲(加载中) / 红点(错误)，附时间戳文字 |
| 无构建工具 | 纯 HTML/CSS/JS，CDN 加载 vis.js |
| 响应式筛选 | MV/表格/图谱均支持下拉筛选 + 实时关键词过滤 |
| 表格排序 | 数据表页支持按行数/大小升降序 |

---

## 5. 物化视图 (MV) 发现策略

1. **优先路径**: `SELECT DISTINCT MvDatabaseName,MvName FROM tasks('type'='mv')` — 获取所有有MV记录的数据库
2. **回退路径**: 按数据库查询 `information_schema.TABLES WHERE TABLE_NAME LIKE '%mv%'`
3. **DDL 解析**: 正则提取 `AS SELECT` 后的 SQL 定义，分析 `FROM`/`JOIN` 提取基表依赖
4. **依赖图构建**: `build_mv_dep_map()` — 识别 MV 间依赖（基表如果是另一个MV则标记为上游）

---

## 6. 设计决策

1. **单进程部署**: 零外置服务（无需Nginx/Redis），`python app.py` 即运行
2. **线程并发采集**: 用 `ThreadPoolExecutor` 并行请求多个 FE/BE 的 HTTP /metrics
3. **告警去重**: 内存集合 `_alert_known` 追踪已汇报问题，避免重复发送
4. **JSON 日期序列化**: 自定义 `EnhancedEncoder` 处理 `datetime`/`date`
5. **容量解析**: `parse_capacity()` 处理 MB/GB/TB/KB 字符串统一转为 GB
6. **前端无框架**: 无需 npm/webpack，单页面 + 原生 JS 足够
7. **MV 安全过滤**: 排除 `__internal_schema` 等系统库

---

## 7. 项目文件结构

```
doris_mt_pro/
├── app.py                    # Flask 后端 (740行)
├── config.json               # 集群 + 告警配置
├── opencode.json              # opencode 配置
├── start.bat                 # 启动脚本
├── architecture.png          # 架构图
├── FSD.md                    # 本文档
├── .claude/
│   └── settings.local.json   # 权限配置
└── static/
    ├── dashboard.html        # 前端 SPA (502行)
    └── gen_html.py           # HTML 生成辅助（未完成）
```

---

## 8. 启动与使用

```bash
# 确保 Python 3.8+ 环境
pip install flask flask-cors pymysql requests

# 修改 config.json 中的集群连接信息

# 启动
python app.py

# 浏览器访问
http://localhost:5000
```
