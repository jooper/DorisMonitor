import json, os, threading, time, uuid
from datetime import datetime, timedelta

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
JOBS_FILE = os.path.join(DATA_DIR, "scheduler_jobs.json")

class SchedulerService:
    def __init__(self, get_db_func):
        self.get_db = get_db_func
        self.jobs = []
        self.lock = threading.Lock()
        self.running = False
        self.thread = None
        self._load()

    def _ensure_data_dir(self):
        if not os.path.exists(DATA_DIR):
            os.makedirs(DATA_DIR)

    def _load(self):
        self._ensure_data_dir()
        if os.path.exists(JOBS_FILE):
            try:
                with open(JOBS_FILE, 'r', encoding='utf-8') as f:
                    self.jobs = json.load(f).get("jobs", [])
                for j in self.jobs:
                    j.setdefault("run_count", 0)
            except Exception:
                self.jobs = []
        else:
            self.jobs = []

    def _save(self):
        self._ensure_data_dir()
        with open(JOBS_FILE, 'w', encoding='utf-8') as f:
            json.dump({"version": 1, "jobs": self.jobs}, f, ensure_ascii=False, indent=2)

    def add_job(self, job_def):
        job = {
            "id": str(uuid.uuid4()),
            "name": job_def["name"],
            "target_db": job_def["target_db"],
            "mode": job_def.get("mode", "full_refresh"),
            "sql": job_def["sql"],
            "schedule": {"value": job_def["schedule_value"], "unit": job_def["schedule_unit"]},
            "start_time": job_def["start_time"],
            "status": "RUNNING",
            "run_count": 0,
            "last_run": None,
            "next_run": job_def.get("start_time"),
            "last_watermark": None,
            "watermark_column": job_def.get("watermark_column"),
            "watermark_type": job_def.get("watermark_type"),
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        with self.lock:
            self.jobs.append(job)
            self._save()
        return job["id"]

    def get_job(self, job_id):
        with self.lock:
            for j in self.jobs:
                if j["id"] == job_id:
                    return dict(j)
        return None

    def list_jobs(self):
        with self.lock:
            return [dict(j) for j in self.jobs]

    def pause_job(self, job_id):
        with self.lock:
            for j in self.jobs:
                if j["id"] == job_id:
                    j["status"] = "PAUSED"
                    self._save()
                    return True
        return False

    def resume_job(self, job_id):
        with self.lock:
            for j in self.jobs:
                if j["id"] == job_id:
                    j["status"] = "RUNNING"
                    self._save()
                    return True
        return False

    def drop_job(self, job_id):
        with self.lock:
            for i, j in enumerate(self.jobs):
                if j["id"] == job_id:
                    self.jobs.pop(i)
                    self._save()
                    return True
        return False

    def _resolve_sql(self, job):
        sql = job["sql"]
        if job.get("mode") == "incremental" and job.get("last_watermark"):
            sql = sql.replace("{{LAST_RUN_TS}}", job["last_watermark"])
        return sql

    def _run_job(self, job):
        sql = self._resolve_sql(job)
        try:
            conn = self.get_db()
            with conn.cursor() as cur:
                if job.get("target_db"):
                    cur.execute(f"USE `{job['target_db']}`")
                cur.execute(sql)
                conn.commit()
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            sv = job["schedule"]["value"]
            su = job["schedule"]["unit"]
            if su == "HOUR":
                next_time = datetime.now() + timedelta(hours=sv)
            elif su == "DAY":
                next_time = datetime.now() + timedelta(days=sv)
            else:
                next_time = datetime.now() + timedelta(minutes=sv)
            with self.lock:
                for j in self.jobs:
                    if j["id"] == job["id"]:
                        j["run_count"] = j.get("run_count", 0) + 1
                        j["last_run"] = now_str
                        j["next_run"] = next_time.strftime("%Y-%m-%d %H:%M:%S")
                        if j.get("mode") == "incremental":
                            j["last_watermark"] = now_str
                        self._save()
                        break
            return True, sql
        except Exception as e:
            return False, str(e)

    def execute_now(self, job_id):
        job = self.get_job(job_id)
        if not job:
            return False, "Job not found"
        return self._run_job(job)

    def tick(self):
        now = datetime.now()
        with self.lock:
            due = [dict(j) for j in self.jobs if j["status"] == "RUNNING" and j.get("next_run")]
        for job in due:
            try:
                nxt = datetime.strptime(job["next_run"], "%Y-%m-%d %H:%M:%S")
                if nxt <= now:
                    ok, msg = self._run_job(job)
                    if not ok:
                        print(f"[Scheduler] Job '{job['name']}' failed: {msg}")
            except Exception as e:
                print(f"[Scheduler] Error on job '{job.get('name')}': {e}")

    def _loop(self):
        while self.running:
            try:
                self.tick()
            except Exception as e:
                print(f"[Scheduler] Tick error: {e}")
            time.sleep(15)

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=3)
