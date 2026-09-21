import json
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from code_harness.events.models import CronEvent
from code_harness.events.queue import EventQueue


@dataclass
class CronJob:
    id: str
    cron: str  # "0 9 * * *"
    prompt: str  # message to inject when fired
    recurring: bool  # True = recurring, False = one-shot
    durable: bool  # True = persist to disk


class CronScheduler:
    def __init__(self, work_dir: Path, event_queue: EventQueue):
        self._jobs: dict[str, CronJob] = {}
        self._lock = threading.Lock()
        self._event_queue = event_queue
        self.DURABLE_PATH = work_dir / ".scheduled_tasks.json"
        self._last_fired: dict[str, str] = {}
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the scheduler once in a managed background thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self.loop,
            daemon=True,
            name="cron-scheduler",
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        """Request shutdown and wait briefly for the scheduler thread."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def loop(self) -> None:
        while not self._stop_event.wait(1):
            self._process_once(datetime.now())

    def _process_once(self, now: datetime) -> None:
        # Date-aware marker prevents daily jobs from skipping on day 2+.
        minute_marker = now.strftime("%Y-%m-%d %H:%M")
        for job in self.list_jobs():
            try:
                if self.cron_matches(job.cron, now):
                    if self._last_fired.get(job.id) != minute_marker:
                        event = CronEvent(
                            event_id=f"event_{uuid4().hex}",
                            job_id=job.id,
                            prompt=job.prompt,
                            fired_at=now.isoformat(),
                        )
                        self._event_queue.put(event)
                        self._last_fired[job.id] = minute_marker
                        print(
                            f"  \033[35m[cron fire] {job.id} -> "
                            f"{job.prompt[:40]}\033[0m"
                        )

                    if not job.recurring:
                        self.remove_job(job.id)
                        if job.durable:
                            self.save_durable_jobs()

            except Exception as e:
                print(f"  \033[31m[cron error] {job.id}: {e}\033[0m")

    def _cron_field_matches(self, field: str, value: int) -> bool:
        """Match a single cron field against a value."""
        if field == "*":
            return True
        if field.startswith("*/"):
            step = int(field[2:])
            return step > 0 and value % step == 0
        if "," in field:
            return any(
                self._cron_field_matches(f.strip(), value) for f in field.split(",")
            )
        if "-" in field:
            lo, hi = field.split("-", 1)
            return int(lo) <= value <= int(hi)
        return value == int(field)

    def cron_matches(self, cron_expr: str, dt: datetime) -> bool:
        """Check if a 5-field cron expression matches the given datetime.
        Standard cron semantics: DOM and DOW use OR when both are constrained."""
        fields = cron_expr.strip().split()
        if len(fields) != 5:
            return False
        minute, hour, dom, month, dow = fields
        dow_val = (dt.weekday() + 1) % 7  # Python Monday=0 → cron Sunday=0

        m = self._cron_field_matches(minute, dt.minute)
        h = self._cron_field_matches(hour, dt.hour)
        dom_ok = self._cron_field_matches(dom, dt.day)
        month_ok = self._cron_field_matches(month, dt.month)
        dow_ok = self._cron_field_matches(dow, dow_val)

        # Minute, hour, month must all match
        if not (m and h and month_ok):
            return False
        # DOM and DOW: if both constrained, either matching is enough (OR)
        dom_unconstrained = dom == "*"
        dow_unconstrained = dow == "*"
        if dom_unconstrained and dow_unconstrained:
            return True
        if dom_unconstrained:
            return dow_ok
        if dow_unconstrained:
            return dom_ok
        return dom_ok or dow_ok

    def _validate_cron_field(self, field: str, lo: int, hi: int) -> str | None:
        """Validate a single cron field value is within [lo, hi]."""
        if field == "*":
            return None
        if field.startswith("*/"):
            step_str = field[2:]
            if not step_str.isdigit():
                return f"Invalid step: {field}"
            step = int(step_str)
            if step <= 0:
                return f"Step must be > 0: {field}"
            return None
        if "," in field:
            for part in field.split(","):
                err = self._validate_cron_field(part.strip(), lo, hi)
                if err:
                    return err
            return None
        if "-" in field:
            parts = field.split("-", 1)
            if not parts[0].isdigit() or not parts[1].isdigit():
                return f"Invalid range: {field}"
            a, b = int(parts[0]), int(parts[1])
            if a < lo or a > hi or b < lo or b > hi:
                return f"Range {field} out of bounds [{lo}-{hi}]"
            if a > b:
                return f"Range start > end: {field}"
            return None
        if not field.isdigit():
            return f"Invalid field: {field}"
        val = int(field)
        if val < lo or val > hi:
            return f"Value {val} out of bounds [{lo}-{hi}]"
        return None

    def validate_cron(self, cron_expr: str) -> str | None:
        """Validate a cron expression. Returns error message or None."""
        fields = cron_expr.strip().split()
        if len(fields) != 5:
            return f"Expected 5 fields, got {len(fields)}"
        bounds = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]
        names = ["minute", "hour", "day-of-month", "month", "day-of-week"]
        for field, (lo, hi), name in zip(fields, bounds, names, strict=True):
            err = self._validate_cron_field(field, lo, hi)
            if err:
                return f"{name}: {err}"
        return None

    def save_durable_jobs(self):
        """Persist durable jobs to .scheduled_tasks.json."""
        durable = [asdict(j) for j in self._jobs.values() if j.durable]
        self.DURABLE_PATH.write_text(json.dumps(durable, indent=2))

    def load_durable_jobs(self):
        """Load durable jobs from disk on startup."""
        if not self.DURABLE_PATH.exists():
            return
        try:
            jobs = json.loads(self.DURABLE_PATH.read_text())
            for j in jobs:
                job = CronJob(**j)
                err = self.validate_cron(job.cron)
                if err:
                    print(
                        f"  \033[31m[cron] skipping invalid job {job.id}: {err}\033[0m"
                    )
                    continue
                self._jobs[job.id] = job
            valid = [j for j in jobs if j["id"] in self._jobs]
            if valid:
                print(f"  \033[35m[cron] loaded {len(valid)} durable job(s)\033[0m")
        except Exception:
            pass

    def schedule_job(self, job: CronJob) -> str:
        err = self.validate_cron(job.cron)
        if err:
            return err

        with self._lock:
            self._jobs[job.id] = job
        if job.durable:
            self.save_durable_jobs()

        return f"{job.id} is scheduled"

    def list_jobs(self) -> list[CronJob]:
        with self._lock:
            return list(self._jobs.values())

    def list_jobs_text(self) -> str:
        jobs = self.list_jobs()

        if not jobs:
            return "No cron jobs. Use schedule_cron to add one."

        lines = []
        for job in jobs:
            tag = "recurring" if job.recurring else "one-shot"
            dur = "durable" if job.durable else "session"
            lines.append(f"  {job.id}: '{job.cron}' → {job.prompt[:40]} [{tag}, {dur}]")

        return "\n".join(lines)

    def remove_job(self, job_id: str) -> CronJob | None:
        with self._lock:
            return self._jobs.pop(job_id, None)


def start_cron_scheduler_daemon(cron_scheduler: CronScheduler) -> threading.Thread:
    """Compatibility wrapper for callers migrating to ``CronScheduler.start``."""
    start = getattr(cron_scheduler, "start", None)
    if callable(start):
        start()
        thread = getattr(cron_scheduler, "_thread", None)
        if thread is not None:
            return thread

    thread = threading.Thread(
        target=cron_scheduler.loop,
        daemon=True,
        name="cron-scheduler",
    )
    thread.start()
    return thread
