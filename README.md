# Doris Monitor

Apache Doris 集群实时监控与管理 Web 面板。基于 Python Flask + 原生 JavaScript SPA，通过 MySQL 协议和 HTTP 接口采集集群状态，支持物化视图管理、Catalog 管理、作业调度、依赖关系图谱等。

## Features

- **集群总览** — FE/BE 节点状态、资源指标、活跃查询、Tablet 健康度
- **物化视图** — CRUD、手动/批量刷新、PAUSE/RESUME 自动调度、历史执行记录、分页筛选
- **依赖图谱** — vis.js 关系图谱，展示 MV → 基表 → 库的依赖链，支持全屏/搜索
- **数据表** — 全库表浏览，支持 Catalog 三段式表名展示详情
- **Catalog** — 创建/删除外部 Catalog，属性按类型自动匹配下拉选项
- **作业调度** — CREATE JOB 定时任务的创建、暂停/恢复、立即执行、删除
- **告警系统** — 邮件告警（SMTP），基于节点状态/查询异常的规则检查

## Tech Stack

| 层 | 技术 |
|---|---|
| 后端 | Python 3 + Flask + PyMySQL + Requests |
| 前端 | 原生 HTML5 + CSS3 + JavaScript (ES5) |
| 图谱 | vis.js 4.21 (CDN) |
| SQL 编辑器 | CodeMirror 5 (CDN) |
| 通信 | RESTful JSON API |
| 部署 | 单进程，`python app.py` 启动 |

## Quick Start

```bash
# 安装依赖
pip install flask flask-cors pymysql requests

# 复制 config.json.example 为 config.json, 修改集群连接信息
# 启动
python app.py

# 访问 http://localhost:5000
```

## Configuration

`config.json.example` (复制为 `config.json` 并修改):

```json
{
  "cluster": {
    "host": "your_doris_host",
    "port": 9030,
    "user": "your_username",
    "password": "your_password",
    "fe_http_port": 8030,
    "be_http_port": 8040,
    "connect_timeout": 10
  },
  "refresh_interval_seconds": 300
}
```

## Screenshots

<img width="1920" height="911" alt="image" src="https://github.com/user-attachments/assets/28566144-25c3-43bd-bda6-7323e7fe6172" />
<img width="1920" height="911" alt="image" src="https://github.com/user-attachments/assets/bdfa2287-1cf4-4655-b504-5e124b69f235" />
<img width="1920" height="911" alt="image" src="https://github.com/user-attachments/assets/be6d20c9-1f1a-486d-95ff-1717540318b8" />
<img width="1920" height="911" alt="image" src="https://github.com/user-attachments/assets/4f1bcfaf-40fd-4a84-a712-6f9d8baceb47" />
<img width="1920" height="911" alt="image" src="https://github.com/user-attachments/assets/9b4f1099-6a4b-434d-ad6b-1bb78de1774c" />
