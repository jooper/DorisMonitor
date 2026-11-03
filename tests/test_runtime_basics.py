import json
import sys
import time
from pathlib import Path

import pytest

import scheduler_service


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FakeScheduler:
    def __init__(self, get_db):
        self.get_db = get_db
        self.started = False
        self.jobs = []

    def start(self):
        self.started = True

    def list_jobs(self):
        return list(self.jobs)


@pytest.fixture
def flask_app(monkeypatch):
    monkeypatch.setattr(scheduler_service, "SchedulerService", FakeScheduler)
    sys.modules.pop("app", None)
    import app

    try:
        yield app
    finally:
        sys.modules.pop("app", None)


@pytest.fixture
def config_path(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "cluster": {
                    "host": "example.test",
                    "port": 9030,
                    "user": "test",
                    "password": "cluster-secret",
                    "fe_http_port": 8030,
                    "be_http_port": 8040,
                    "connect_timeout": 10,
                },
                "refresh_interval_seconds": 30,
                "alert": {
                    "enabled": True,
                    "smtp_host": "smtp.example.test",
                    "smtp_port": 465,
                    "smtp_user": "alert-user",
                    "smtp_password": "alert-secret",
                    "sender_email": "alert@example.test",
                    "recipients": "ops@example.test",
                    "check_interval_seconds": 123,
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def test_start_batch_uses_its_own_directory():
    text = (PROJECT_ROOT / "start.bat").read_text(encoding="ascii")
    assert 'cd /d "%~dp0"' in text
    assert "D:\\Projects\\Sources\\BDProject" not in text


def test_scheduler_is_available_and_jobs_api_works_without_main(flask_app, monkeypatch):
    monkeypatch.setattr(flask_app, "get_jobs", lambda: [])

    assert flask_app.scheduler is not None
    assert flask_app.scheduler.started is False

    response = flask_app.app.test_client().get("/api/jobs")

    assert response.status_code == 200
    assert response.get_json() == {"jobs": []}


def test_post_config_preserves_alert_settings(flask_app, config_path, monkeypatch):
    monkeypatch.setattr(flask_app, "CONFIG_PATH", str(config_path))

    response = flask_app.app.test_client().post(
        "/api/config",
        json={
            "host": "new.example.test",
            "port": 9031,
            "user": "new-user",
            "password": "********",
            "fe_http_port": 8031,
            "be_http_port": 8041,
            "connect_timeout": 7,
            "refresh_interval_seconds": 45,
        },
    )

    assert response.status_code == 200
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["cluster"]["host"] == "new.example.test"
    assert saved["cluster"]["password"] == "cluster-secret"
    assert saved["refresh_interval_seconds"] == 45
    assert saved["alert"]["smtp_password"] == "alert-secret"
    assert saved["alert"]["check_interval_seconds"] == 123


def test_alert_config_preserves_masked_password(flask_app, config_path, monkeypatch):
    monkeypatch.setattr(flask_app, "CONFIG_PATH", str(config_path))
    client = flask_app.app.test_client()

    response = client.post(
        "/api/alert-config",
        json={
            "enabled": True,
            "smtp_host": "smtp2.example.test",
            "smtp_port": 587,
            "smtp_user": "new-alert-user",
            "smtp_password": "********",
            "sender_email": "alerts@example.test",
            "recipients": "new-ops@example.test",
        },
    )

    assert response.status_code == 200
    saved = json.loads(config_path.read_text(encoding="utf-8"))["alert"]
    assert saved["smtp_password"] == "alert-secret"
    assert saved["smtp_user"] == "new-alert-user"
    assert saved["check_interval_seconds"] == 123
    safe = client.get("/api/alert-config").get_json()
    assert safe["smtp_password"] == "********"
    assert safe["smtp_user"] == "new-alert-user"


def test_alert_test_uses_mocked_email_sender_and_existing_config(
    flask_app, config_path, monkeypatch
):
    monkeypatch.setattr(flask_app, "CONFIG_PATH", str(config_path))
    calls = []

    def fake_send_email(subject, body, ac):
        calls.append((subject, body, ac))
        return True

    monkeypatch.setattr(flask_app, "send_email", fake_send_email)

    response = flask_app.app.test_client().post(
        "/api/alert-test",
        json={"smtp_password": "********"},
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"
    assert len(calls) == 1
    assert calls[0][2]["smtp_host"] == "smtp.example.test"
    assert calls[0][2]["smtp_user"] == "alert-user"
    assert calls[0][2]["smtp_password"] == "alert-secret"
    assert calls[0][2]["recipients"] == "ops@example.test"


def test_scheduler_drop_requires_source(flask_app, monkeypatch):
    dropped = []

    monkeypatch.setattr(flask_app.scheduler, "drop_job", lambda job_id: dropped.append(job_id) or True, raising=False)

    response = flask_app.app.test_client().post(
        "/api/jobs/drop",
        json={"id": "job-id", "source": "scheduler"},
    )

    assert response.status_code == 200
    assert dropped == ["job-id"]


def test_mv_toggle_uses_doris_31_compatible_sql(flask_app, monkeypatch):
    calls = []

    def fake_execute_ddl(sql):
        calls.append(sql)
        return True, ""

    monkeypatch.setattr(flask_app, "execute_ddl", fake_execute_ddl)
    client = flask_app.app.test_client()

    response = client.post(
        "/api/materialized-view/toggle",
        json={"database": "test_db", "name": "test_mv", "action": "pause"},
    )

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "message": "MV test_mv paused"}
    assert calls == ["PAUSE MATERIALIZED VIEW JOB ON `test_db`.`test_mv`"]

    response = client.post(
        "/api/materialized-view/toggle",
        json={"database": "test_db", "name": "test_mv", "action": "resume"},
    )

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "message": "MV test_mv resumed"}
    assert calls[-1] == "RESUME MATERIALIZED VIEW JOB ON `test_db`.`test_mv`"


def test_mv_toggle_failure_returns_execute_ddl_error(flask_app, monkeypatch):
    calls = []

    def fake_execute_ddl(sql):
        calls.append(sql)
        return False, "mock pause failure"

    monkeypatch.setattr(flask_app, "execute_ddl", fake_execute_ddl)

    response = flask_app.app.test_client().post(
        "/api/materialized-view/toggle",
        json={"database": "test_db", "name": "test_mv", "action": "pause"},
    )

    assert response.status_code == 400
    assert response.get_json() == {"error": "mock pause failure"}
    assert calls == ["PAUSE MATERIALIZED VIEW JOB ON `test_db`.`test_mv`"]


def test_dashboard_shows_mv_toggle_failure_details():
    html = (PROJECT_ROOT / "static" / "dashboard.html").read_text(encoding="utf-8")

    assert "var done=0,fail=0,errors=[]" in html
    assert "errors.push(m.name+': '+(d.error||'\u63a5\u53e3\u672a\u8fd4\u56de\u9519\u8bef\u4fe1\u606f'))" in html
    assert "errors.push(m.name+': '+(e&&e.message?e.message:'\u8bf7\u6c42\u5931\u8d25'))" in html
    assert "msg+='\uff1b\u5931\u8d25\u660e\u7ec6\uff1a'+errors.join('\uff1b')" in html
    assert "showToast(msg,fail?'error':'info')" in html


def configure_collect_metrics_mocks(flask_app, monkeypatch, job_rows=None, job_error=None):
    queries = []
    mvs = [
        {"database": "test_db", "name": "paused_mv"},
        {"database": "test_db", "name": "running_mv"},
        {"database": "test_db", "name": "unknown_mv"},
    ]

    def fake_query(sql):
        queries.append(sql)
        if "SELECT DISTINCT MvDatabaseName FROM tasks" in sql:
            return [{"MvDatabaseName": "test_db"}]
        if 'FROM jobs("type"="mv")' in sql:
            if job_error is not None:
                raise job_error
            return job_rows or []
        raise AssertionError(f"unexpected query: {sql}")

    monkeypatch.setattr(flask_app, "query", fake_query)
    for name, value in (
        ("get_fe_status", []),
        ("get_be_status", []),
        ("get_cluster_stats", {}),
        ("get_tablet_health", {}),
        ("get_fe_metrics_all", {}),
        ("get_be_metrics_all", {}),
        ("get_queries", []),
        ("get_all_tables", []),
        ("get_mv_latest_tasks", {}),
        ("get_mv_today_counts", {}),
        ("get_mv_row_sizes", {}),
    ):
        monkeypatch.setattr(flask_app, name, lambda *args, value=value, **kwargs: value)
    monkeypatch.setattr(flask_app, "discover_mvs", lambda database=None: mvs)
    return queries, mvs


def test_collect_metrics_maps_mv_job_pause_status(flask_app, monkeypatch):
    job_rows = [
        {"MvDatabaseName": "test_db", "MvName": "paused_mv", "Status": "PAUSED"},
        {"MvDatabaseName": "test_db", "MvName": "running_mv", "Status": "RUNNING"},
    ]
    queries, _ = configure_collect_metrics_mocks(flask_app, monkeypatch, job_rows=job_rows)

    data = flask_app.collect_metrics()

    assert 'SELECT MvDatabaseName, MvName, Status FROM jobs("type"="mv")' in queries
    assert data["materialized_views"][0]["paused"] is True
    assert data["materialized_views"][1]["paused"] is False
    assert data["materialized_views"][2]["paused"] is False


def test_collect_metrics_degrades_when_mv_job_status_query_fails(flask_app, monkeypatch):
    configure_collect_metrics_mocks(
        flask_app,
        monkeypatch,
        job_error=RuntimeError("mock jobs query failure"),
    )

    data = flask_app.collect_metrics()

    assert [mv["paused"] for mv in data["materialized_views"]] == [False, False, False]
    assert data["errors"] == []


def test_mv_toggle_success_invalidates_metrics_cache(flask_app, monkeypatch):
    monkeypatch.setattr(flask_app, "execute_ddl", lambda sql: (True, ""))

    try:
        with flask_app.CACHE["lock"]:
            flask_app.CACHE["data"] = {"materialized_views": []}
            flask_app.CACHE["timestamp"] = time.time()

        response = flask_app.app.test_client().post(
            "/api/materialized-view/toggle",
            json={"database": "test_db", "name": "test_mv", "action": "pause"},
        )

        assert response.status_code == 200
        assert response.get_json()["status"] == "ok"
        with flask_app.CACHE["lock"]:
            assert flask_app.CACHE["data"] is None
            assert flask_app.CACHE["timestamp"] == 0
    finally:
        with flask_app.CACHE["lock"]:
            flask_app.CACHE["data"] = None
            flask_app.CACHE["timestamp"] = 0


def test_dashboard_displays_and_filters_paused_mvs():
    html = (PROJECT_ROOT / "static" / "dashboard.html").read_text(encoding="utf-8")

    assert '<option value="PAUSED">PAUSED</option>' in html
    assert "(!st||(st==='PAUSED'?!!m.paused:m.last_status===st))" in html
    assert "var st=mv.paused?" in html
    assert ">\u5df2\u6682\u505c</span>" in html


def test_dashboard_wires_alert_and_scheduler_delete_requests():
    html = (PROJECT_ROOT / "static" / "dashboard.html").read_text(encoding="utf-8")

    for expected in (
        "function loadAlertConfig()",
        "function saveAlertConfig()",
        "function testAlert()",
        "fetch('/api/alert-config'",
        "fetch('/api/alert-test'",
        "smtp_user: document.getElementById('alert-user').value",
        "document.getElementById('alert-user').value=d.smtp_user",
    ):
        assert expected in html

    assert "source==='scheduler' ? {id:name, source:'scheduler'}" in html


def test_requirements_declare_runtime_dependencies():
    text = (PROJECT_ROOT / "requirements.txt").read_text(encoding="ascii")
    requirements = [line.strip() for line in text.splitlines() if line.strip()]

    assert "Flask>=3.0" in requirements
    assert "flask-cors>=4.0" in requirements
    assert "PyMySQL>=1.1" in requirements
    assert "requests>=2.31" in requirements

    dev_text = (PROJECT_ROOT / "requirements-dev.txt").read_text(encoding="ascii")
    dev_requirements = [line.strip() for line in dev_text.splitlines() if line.strip()]
    assert "-r requirements.txt" in dev_requirements
    assert "pytest>=8.0" in dev_requirements
