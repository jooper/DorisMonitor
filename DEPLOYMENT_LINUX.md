# Linux 服务器部署方案

本文面向 Doris 物化视图管理系统（`doris_mt_pro`）的 Linux 服务器部署，覆盖环境准备、目录规划、配置管理、systemd 服务、访问控制、日志、健康检查、升级回滚和常见问题排查。

> 部署原则：本系统已内置基于 Flask Session 的静态账号登录（在 `config.json` 的 `auth` 节点配置用户名/密码，默认 `admin`），但没有内置 TLS，默认监听 `0.0.0.0:5000`。生产环境仍应将其限制在可信内网、VPN 或反向代理之后，不应直接暴露到公网。

## 1. 运行环境与依赖

### 1.1 运行环境

- Linux 发行版：Ubuntu 20.04+、Debian 11+、RHEL 8+ 或兼容 systemd 的发行版
- Python：`3.8+`，推荐 `3.11` 或 `3.12`
- 网络：应用服务器可访问 Doris FE MySQL 协议端口（默认 `9030`）和 FE/BE HTTP 端口（默认 `8030/8040`）
- 权限：部署用户可创建虚拟环境并监听 `5000` 端口

### 1.2 安装系统依赖

以 Ubuntu/Debian 为例：

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git
```

RHEL/CentOS/Rocky：

先确认系统默认 `python3` 是否满足要求：

```bash
python3 --version
```

若输出为 `Python 3.8+`，可直接安装：

```bash
sudo dnf install -y python3 python3-pip git
```

注意：RHEL 8 / CentOS 8 的默认 `python3` 常见为 `3.6`，低于本系统要求的 `3.8+`，不能直接使用。此时需要启用较新的 Python module。不同发行版和小版本提供的 module 名称、流可能不同，应先查看：

```bash
sudo dnf module list python*
```

RHEL 8 / CentOS 8 可按实际可用流选择，例如启用 Python 3.9：

```bash
sudo dnf module enable python39 -y
sudo dnf install -y python39 python39-pip git
```

或启用 Python 3.11：

```bash
sudo dnf module enable python3.11 -y
sudo dnf install -y python3.11 python3.11-pip git
```

RHEL 9 / Rocky 9 等较新发行版的默认 Python 通常已满足要求，但仍应先执行 `python3 --version` 确认。

### 1.3 Python 依赖

项目已提供 `requirements.txt`：

```text
Flask>=3.0
flask-cors>=4.0
PyMySQL>=1.1
requests>=2.31
```

安装：

创建虚拟环境时应显式使用已确认的 `3.8+` 解释器。以下以 Python 3.11 为例；如启用的是 Python 3.9，请将解释器替换为 `/usr/bin/python3.9`：

```bash
/usr/bin/python3.11 -m venv /opt/doris-mt/venv
/opt/doris-mt/venv/bin/python --version
/opt/doris-mt/venv/bin/pip install --upgrade pip
/opt/doris-mt/venv/bin/pip install -r /opt/doris-mt/app/requirements.txt
```

可选开发/测试依赖：

```text
-r requirements.txt
pytest>=8.0
```

安装开发依赖：

```bash
/opt/doris-mt/venv/bin/pip install -r /opt/doris-mt/app/requirements-dev.txt
```

### 1.4 Python 版本说明

- Flask 3.x 支持 Python 3.8+
- RHEL 8 / CentOS 8 不应使用默认 Python 3.6，需启用 `python39`、`python3.11` 等满足要求的 module
- 生产建议使用当前仍在维护周期内的 Python 版本
- 建议固定虚拟环境解释器，并在部署前执行 `python --version` 复核

## 2. 目录规划与部署用户

### 2.1 部署用户

建议创建专用非 root 用户运行服务：

```bash
sudo useradd --system --home /opt/doris-mt --create-home --shell /usr/sbin/nologin doris-mt
```

该用户仅用于运行本系统，不授予 sudo 权限，不使用 root 运行 Flask 进程。

### 2.2 目录规划

推荐目录：

```text
/opt/doris-mt/
├── app/                  # 应用代码
│   ├── app.py
│   ├── scheduler_service.py
│   ├── static/
│   ├── requirements.txt
│   ├── config.json       # 真实配置，不入库
│   └── data/             # 调度作业与物化视图元数据
│       ├── scheduler_jobs.json
│       └── mv_meta.json
└── venv/                 # Python 虚拟环境
```

初始化：

```bash
sudo mkdir -p /opt/doris-mt/app /opt/doris-mt/app/data /opt/doris-mt/venv
sudo chown -R doris-mt:doris-mt /opt/doris-mt
sudo chmod 750 /opt/doris-mt
sudo chmod 750 /opt/doris-mt/app
sudo chmod 750 /opt/doris-mt/app/data
```

### 2.3 版本化发布（可选）

更稳妥的生产目录可以使用版本目录加软链接：

```text
/opt/doris-mt/
├── releases/
│   ├── 2026-09-29/
│   └── 2026-09-28/
└── current -> releases/2026-09-29
```

优点：升级和回滚只需切换 `current` 软链接。为避免文档过长，后文以 `/opt/doris-mt/app` 直接部署为例。

### 2.4 代码发布

```bash
# 将项目代码发布到 /opt/doris-mt/app
# 可使用 rsync/scp/git clone，以下为示例
sudo rsync -a --delete \
  --exclude '.git' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude 'config.json' \
  --exclude 'data/' \
  ./ /opt/doris-mt/app/

sudo chown -R doris-mt:doris-mt /opt/doris-mt/app
```

注意：

- 不要用 `--delete` 覆盖或删除已有 `config.json` 与 `data/`
- 若首次部署，可同步 `config.json.example`，再复制为 `config.json`
- `data/` 应由备份流程单独管理

## 3. 配置管理

### 3.1 配置文件

配置文件为 `config.json`，模板为 `config.json.example`：

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

首次部署：

```bash
cd /opt/doris-mt/app
sudo -u doris-mt cp config.json.example config.json
sudo -u doris-mt vi config.json
```

### 3.2 权限要求

`config.json` 包含 Doris 连接密码，应仅允许运行用户读取：

```bash
sudo chmod 600 /opt/doris-mt/app/config.json
sudo chown doris-mt:doris-mt /opt/doris-mt/app/config.json
```

建议：

- `config.json` 不提交 Git
- 不要把真实密码写入 `config.json.example`
- 不要把配置文件放到共享目录
- 更换密码时同步备份加密策略
- 如后续引入环境变量或密钥管理系统，可进一步降低明文密码风险

### 3.3 数据文件

运行时会维护：

- `data/scheduler_jobs.json`
- `data/mv_meta.json`

这些文件包含调度作业和物化视图元数据，应纳入备份。建议：

```bash
sudo chmod 640 /opt/doris-mt/app/data/scheduler_jobs.json
sudo chmod 640 /opt/doris-mt/app/data/mv_meta.json
sudo chown doris-mt:doris-mt /opt/doris-mt/app/data/*.json
```

## 4. 服务运行方式

推荐使用 systemd 托管，不使用 `nohup` 或手工终端运行。

### 4.1 systemd Unit 示例

创建：

```bash
sudo vi /etc/systemd/system/doris-mt.service
```

示例内容：

```ini
[Unit]
Description=Doris Materialized View Management System
Documentation=file:///opt/doris-mt/app/README.md
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=doris-mt
Group=doris-mt
WorkingDirectory=/opt/doris-mt/app
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=PYTHONUNBUFFERED=1
Environment=TZ=Asia/Shanghai
ExecStart=/opt/doris-mt/venv/bin/python /opt/doris-mt/app/app.py
Restart=on-failure
RestartSec=5s
TimeoutStopSec=20s
KillSignal=SIGTERM
StandardOutput=journal
StandardError=journal
SyslogIdentifier=doris-mt
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=/opt/doris-mt/app/data /opt/doris-mt/app/config.json

[Install]
WantedBy=multi-user.target
```

说明：

- `WorkingDirectory` 必须是应用根目录，否则 `config.json`、`data/` 等相对路径无法正确解析
- `ExecStart` 使用虚拟环境中的 Python，并显式指定 `app.py` 绝对路径
- `config.json` 是应用必需文件，需在启用服务前从 `config.json.example` 创建；`ReadWritePaths` 中包含不存在的普通文件路径时，systemd 启动会失败
- 当前应用监听 `0.0.0.0:5000`，端口通过防火墙控制
- `Restart=on-failure` 处理异常退出
- `ProtectSystem=strict` 与 `ReadWritePaths` 将写入范围限制到数据文件和配置文件
- 如系统不支持某些 systemd 选项，可先删除对应加固行，再逐步启用

启用服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now doris-mt.service
sudo systemctl status doris-mt.service --no-pager
```

### 4.2 手动启动（仅调试）

```bash
sudo systemctl stop doris-mt
sudo -u doris-mt /opt/doris-mt/venv/bin/python app.py
```

调试结束后应立即改回 systemd 托管。

### 4.3 WSGI 模式（可选）

应用对象为 `app`，可在 WSGI 容器中导入。例如 Gunicorn：

```bash
/opt/doris-mt/venv/bin/pip install gunicorn
/opt/doris-mt/venv/bin/gunicorn \
  --chdir /opt/doris-mt/app \
  --workers 2 \
  --threads 4 \
  --bind 127.0.0.1:5000 \
  app:app
```

对应 Unit 可将 `ExecStart` 改为上述 Gunicorn 命令。

需要注意：当前应用设计为单进程内存缓存与调度器模型，多 worker 会带来状态与缓存不一致问题。若使用 Gunicorn，建议 `--workers 1 --threads 4`，并接受调度器不自动启动。

## 5. 防火墙与访问控制

### 5.1 当前风险

当前应用：

- 无登录鉴权
- 无 RBAC 权限模型
- 监听 `0.0.0.0:5000`
- 前端页面可查看集群信息
- 后端接口可修改配置、暂停/恢复物化视图、操作调度作业
- 可保存 SMTP 告警配置

风险结论：任何能访问 5000 端口的人都可能获得系统控制能力，并可能看到或修改敏感配置。禁止直接暴露公网。

### 5.2 推荐访问模式

按优先级：

1. 仅运维内网访问，服务器防火墙只放行指定网段
2. 通过 VPN 访问内网
3. 通过 Nginx 反向代理做 TLS、来源白名单和统一认证
4. 临时使用 SSH 隧道

### 5.3 firewalld 示例

仅允许本机与内网 `10.10.0.0/16` 访问 5000 端口：

```bash
# 先确认网卡实际绑定的 zone 和已有策略，不要盲目套用示例
sudo firewall-cmd --get-active-zones
sudo firewall-cmd --list-all-zones

sudo firewall-cmd --permanent --zone=internal --add-rich-rule='rule family=ipv4 source address=10.10.0.0/16 port port=5000 protocol=tcp accept'
sudo firewall-cmd --permanent --zone=public --remove-port=5000/tcp || true
sudo firewall-cmd --reload
```

注意：

- `internal` 只是示例 zone，必须与服务器网卡实际绑定 zone 一致
- 需检查 `public`、`external`、`drop` 等其他 zone 是否已放行 5000 端口
- 云服务器还需检查安全组、云防火墙和宿主机网络策略
- 不要将与本应用无关的 `http`/80 端口规则加入本示例

若只想本机访问：

```bash
sudo firewall-cmd --permanent --remove-port=5000/tcp || true
```

然后通过 SSH 隧道访问：

```bash
ssh -L 5000:127.0.0.1:5000 user@server
```

### 5.4 nftables 示例

```bash
sudo nft add rule inet filter input ip saddr 127.0.0.1 tcp dport 5000 accept
sudo nft add rule inet filter input ip saddr 10.10.0.0/16 tcp dport 5000 accept
sudo nft add rule inet filter input tcp dport 5000 drop
```

实际规则应根据现有防火墙策略调整，避免重复或冲突。

### 5.5 Nginx 反向代理（可选）

```nginx
server {
    listen 443 ssl;
    server_name doris-mt.internal.example.com;

    ssl_certificate     /etc/ssl/certs/doris-mt.pem;
    ssl_certificate_key /etc/ssl/private/doris-mt.key;

    location / {
        allow 10.10.0.0/16;
        deny all;

        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

注意：Nginx 白名单不是用户级鉴权。如需用户登录，还需在网关层接入统一认证或后续为应用增加鉴权功能。

## 6. 日志与轮转

### 6.1 journald

systemd Unit 已将标准输出和错误输出写入 journal：

```bash
sudo journalctl -u doris-mt -f
sudo journalctl -u doris-mt --since "1 hour ago"
sudo journalctl -u doris-mt --since today --no-pager
```

可调整 `/etc/systemd/journald.conf`：

```ini
[Journal]
Storage=persistent
Compress=yes
MaxRetentionSec=30day
```

修改后：

```bash
sudo systemctl restart systemd-journald
```

### 6.2 logrotate（可选）

若将日志写入文件，可将 Unit 中：

```ini
StandardOutput=journal
StandardError=journal
```

改为：

```ini
StandardOutput=append:/var/log/doris-mt/app.log
StandardError=append:/var/log/doris-mt/error.log
```

创建目录：

```bash
sudo mkdir -p /var/log/doris-mt
sudo chown doris-mt:doris-mt /var/log/doris-mt
sudo chmod 750 /var/log/doris-mt
```

`/etc/logrotate.d/doris-mt`：

```text
/var/log/doris-mt/*.log {
    daily
    rotate 30
    missingok
    notifempty
    compress
    delaycompress
    copytruncate
    su doris-mt doris-mt
}
```

验证：

```bash
sudo logrotate -d /etc/logrotate.d/doris-mt
```

### 6.3 日志安全

日志中可能包含异常堆栈和请求信息。建议：

- 不要将日志目录开放给普通用户
- 定期归档并按安全策略清理
- 如接入集中日志平台，注意脱敏

## 7. 健康检查

### 7.1 systemd 状态

```bash
sudo systemctl is-active doris-mt
sudo systemctl status doris-mt --no-pager
```

期望状态为 `active (running)`。

### 7.2 HTTP 健康检查

当前应用提供：

```text
GET /api/ping
```

响应示例：

```json
{"ok": true}
```

本机检查：

```bash
curl -fsS http://127.0.0.1:5000/api/ping
```

如需从内网检查，可在允许访问的机器上执行：

```bash
curl -fsS http://<server-ip>:5000/api/ping
```

### 7.3 端口检查

```bash
sudo ss -ltnp | grep ':5000'
```

期望看到 `doris-mt` 服务进程监听 `5000`。

### 7.4 进程检查

```bash
pgrep -af '/opt/doris-mt/venv/bin/python app.py'
```

### 7.5 Doris 连通性

可在系统页面使用连接测试功能，或确认配置指向的 FE/BE 端口可访问。排查网络时可使用：

```bash
nc -zv <doris_fe_host> 9030
curl -I http://<doris_fe_host>:8030
```

不要在生产检查中执行任何修改 Doris 数据或物化视图状态的操作。

## 8. 升级、回滚与备份

### 8.1 升级前检查

1. 记录当前版本：
   ```bash
   cd /opt/doris-mt/app
   git rev-parse HEAD 2>/dev/null || echo "manual release"
   ```
2. 确认服务当前状态：
   ```bash
   sudo systemctl status doris-mt --no-pager
   ```
3. 确认备份已完成
4. 通知用户短暂不可用窗口

### 8.2 备份

备份配置和本地数据：

```bash
sudo install -d -o doris-mt -g doris-mt /opt/doris-mt/backups
sudo -u doris-mt cp /opt/doris-mt/app/config.json /opt/doris-mt/backups/config.json.$(date +%Y%m%d-%H%M%S)
sudo -u doris-mt cp /opt/doris-mt/app/data/scheduler_jobs.json /opt/doris-mt/backups/scheduler_jobs.json.$(date +%Y%m%d-%H%M%S)
sudo -u doris-mt cp /opt/doris-mt/app/data/mv_meta.json /opt/doris-mt/backups/mv_meta.json.$(date +%Y%m%d-%H%M%S)
```

建议每日备份，并至少保留 7-30 天。

### 8.3 升级流程

```bash
sudo systemctl stop doris-mt

# 备份（见 8.2）

# 发布新代码，保留 config.json 和 data/
sudo rsync -a --delete \
  --exclude '.git' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude 'config.json' \
  --exclude 'data/' \
  ./ /opt/doris-mt/app/

sudo chown -R doris-mt:doris-mt /opt/doris-mt/app
sudo chmod 600 /opt/doris-mt/app/config.json

# 可选：更新依赖
sudo -u doris-mt /opt/doris-mt/venv/bin/pip install -r /opt/doris-mt/app/requirements.txt

# 可选：离线测试；pytest 属于开发依赖，需先安装 requirements-dev.txt
sudo -u doris-mt /opt/doris-mt/venv/bin/pip install -r /opt/doris-mt/app/requirements-dev.txt
cd /opt/doris-mt/app
sudo -u doris-mt /opt/doris-mt/venv/bin/python -B -m pytest -q

sudo systemctl start doris-mt
curl -fsS http://127.0.0.1:5000/api/ping
```

### 8.4 回滚流程

```bash
sudo systemctl stop doris-mt
# 回滚代码版本或恢复备份
sudo systemctl start doris-mt
curl -fsS http://127.0.0.1:5000/api/ping
```

如果使用版本目录 + `current` 软链接，只需切换软链接并重启服务。

### 8.5 备份文件安全

备份中的 `config.json` 同样包含敏感信息，应：

- 权限 `600`
- 不放入公开目录
- 如复制到异地，应加密传输
- 不提交 Git

## 9. Scheduler 与运行模式

当前 `app.py` 的行为：

- `python app.py` 启动 Flask 服务
- 主入口中会调用 `scheduler.start()`
- 主入口中会启动告警检查
- 监听 `0.0.0.0:5000`
- `threaded=True`

含义：使用 systemd 直接运行 `python app.py` 时，调度线程会自动启动，本地 scheduler 作业会按配置执行。

### 9.1 systemd + python app.py（当前推荐）

适用情况：

- 需要系统页面完整功能
- 需要本地 scheduler 自动执行作业
- 希望部署简单、运维成本低

风险与注意事项：

- 升级或重启会中断当前线程中的执行
- 调度状态保存在 `data/scheduler_jobs.json`
- 若作业配置错误，可能对 Doris 执行作业 SQL
- 部署前应检查作业列表与目标库表
- 应限制访问来源，避免未授权用户修改作业

当前建议：内网运维工具场景优先使用该模式，并配合防火墙/VPN/Nginx 白名单。

### 9.2 WSGI 模式（可选）

在 WSGI 容器中导入 `app:app` 时，`if __name__ == "__main__"` 不会执行，因此：

- Flask HTTP 服务可用
- `scheduler.start()` 不会自动启动
- 告警检查线程不会自动启动
- 本地 scheduler 作业不会自动执行

适用情况：

- 只希望查看和操作页面，不希望后台自动执行作业
- 希望由独立进程专门负责调度
- 希望使用更成熟的 WSGI 服务管理方式

风险与注意事项：

- 当前系统没有为“Web + 调度分离”提供独立调度启动入口
- 多 worker 会带来内存状态不一致
- 使用 WSGI 前需明确接受本地调度不自动执行

当前建议：若不需要自动调度，可使用单 worker Gunicorn 并明确告知使用方；若需要完整功能，继续使用 `python app.py`。

## 10. 常见问题排查

### 10.1 服务启动失败

```bash
sudo systemctl status doris-mt --no-pager
sudo journalctl -u doris-mt -n 100 --no-pager
```

常见原因：

- `config.json` 缺失或 JSON 格式错误
- 虚拟环境路径不正确
- `WorkingDirectory` 不是应用根目录
- 依赖未安装
- 5000 端口被占用
- 文件权限不足

手工验证：

```bash
sudo -u doris-mt /opt/doris-mt/venv/bin/python -c "import sys; print(sys.executable)"
sudo -u doris-mt /opt/doris-mt/venv/bin/python -c "import flask, pymysql, requests; print('deps ok')"
```

### 10.2 `/api/ping` 不通

检查：

```bash
sudo systemctl is-active doris-mt
sudo ss -ltnp | grep ':5000'
curl -v http://127.0.0.1:5000/api/ping
sudo journalctl -u doris-mt -n 100 --no-pager
```

若本机可访问但远端不可访问：

- 检查防火墙规则
- 检查是否需要 VPN 或 SSH 隧道
- 检查安全组/云防火墙

### 10.3 Doris 连接失败

检查：

```bash
nc -zv <doris_host> 9030
curl -I http://<doris_host>:8030
```

确认：

- `config.json` 中 host/port/user/password 正确
- 应用服务器可访问 FE
- Doris 账号权限满足页面操作需求
- FE/BE HTTP 端口未阻断

查看日志：

```bash
sudo journalctl -u doris-mt --since "10 minutes ago" --no-pager
```

### 10.4 配置保存失败

常见原因：

- `config.json` 权限不是 `doris-mt:doris-mt`
- systemd 加固限制写入
- JSON 文件损坏
- 磁盘空间不足

处理：

```bash
sudo chown doris-mt:doris-mt /opt/doris-mt/app/config.json
sudo chmod 600 /opt/doris-mt/app/config.json
sudo systemctl restart doris-mt
```

若 JSON 损坏，应从备份恢复，而不是直接提交半损坏文件。

### 10.5 调度作业未执行

排查顺序：

1. 确认运行模式是 `python app.py`
2. 检查 `data/scheduler_jobs.json` 中的作业状态
3. 检查 `systemctl` 与 journal
4. 检查作业目标库表和 SQL
5. 检查 Doris 连接

注意：WSGI 模式不会自动启动本地 scheduler。

### 10.6 端口占用

```bash
sudo ss -ltnp | grep ':5000'
```

处理旧进程：

```bash
sudo systemctl stop doris-mt
sudo fuser -k 5000/tcp   # 谨慎执行，仅确认是本服务旧进程时使用
```

### 10.7 数据文件损坏

症状：作业列表为空、元数据异常、服务启动报 JSON 错误。

处理：

1. 停止服务
2. 从备份恢复 `data/scheduler_jobs.json` 或 `data/mv_meta.json`
3. 修正权限
4. 重启服务

### 10.8 日志权限错误

若选择文件日志，检查：

```bash
sudo ls -ld /var/log/doris-mt
sudo ls -l /var/log/doris-mt
```

应为 `doris-mt:doris-mt` 且目录权限建议 `750`。

## 11. 部署检查清单

- [ ] Python 解释器版本已确认为 3.8+（RHEL 8/CentOS 8 不使用默认 Python 3.6）
- [ ] 虚拟环境使用正确的 Python 解释器创建
- [ ] 专用用户 `doris-mt` 已创建
- [ ] 代码位于 `/opt/doris-mt/app`
- [ ] 虚拟环境位于 `/opt/doris-mt/venv`
- [ ] 依赖已安装
- [ ] `config.json` 已配置且权限为 `600`
- [ ] `data/` 目录存在且归属正确
- [ ] systemd Unit 已配置
- [ ] 服务已启用并运行
- [ ] `/api/ping` 返回 `{"ok":true}`
- [ ] 5000 端口未暴露公网
- [ ] 访问来源已限制
- [ ] 日志可查询
- [ ] 备份策略已落地
- [ ] 已确认是否需要 scheduler 自动执行
- [ ] 运维人员知晓无鉴权风险

## 12. 附：常用命令

```bash
sudo systemctl start doris-mt
sudo systemctl stop doris-mt
sudo systemctl restart doris-mt
sudo systemctl status doris-mt --no-pager
sudo journalctl -u doris-mt -f
curl -fsS http://127.0.0.1:5000/api/ping
sudo ss -ltnp | grep ':5000'
cd /opt/doris-mt/app && sudo -u doris-mt /opt/doris-mt/venv/bin/python -B -m pytest -q
```
