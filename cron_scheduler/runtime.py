# code_harness/cron_scheduler/runtime.py
from code_harness.cron_scheduler.scheduler import CronScheduler

_scheduler: CronScheduler | None = None


def set_cron_scheduler(scheduler: CronScheduler) -> None:
    global _scheduler
    _scheduler = scheduler


def get_cron_scheduler() -> CronScheduler:
    if _scheduler is None:
        raise RuntimeError("Cron scheduler is not configured")
    return _scheduler
