import tempfile
import threading
import unittest
from datetime import datetime
import json
from pathlib import Path

from code_harness.cron_scheduler.queue import CronEvent, CronEventQueue
from code_harness.cron_scheduler.scheduler import (
    CronJob,
    CronScheduler,
    start_cron_scheduler_daemon,
)


class CronSchedulerDaemonTests(unittest.TestCase):
    def test_start_cron_scheduler_daemon_uses_daemon_thread(self):
        started = threading.Event()

        class FakeScheduler:
            def loop(self):
                started.set()

        thread = start_cron_scheduler_daemon(FakeScheduler())
        thread.join(timeout=1)

        self.assertEqual(thread.name, "cron-scheduler")
        self.assertTrue(thread.daemon)
        self.assertTrue(started.is_set())


class CronSchedulerTests(unittest.TestCase):
    def test_matching_job_is_enqueued(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            event_queue = CronEventQueue(Path(tmpdir))
            scheduler = CronScheduler(Path(tmpdir), event_queue)
            job = CronJob(
                id="job-1",
                cron="30 9 * * *",
                prompt="run morning check",
                recurring=True,
                durable=False,
            )
            scheduler.schedule_job(job)

            scheduler._process_once(datetime(2026, 7, 4, 9, 30))

            events = event_queue.drain()
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].job_id, job.id)
            self.assertEqual(events[0].prompt, job.prompt)
            self.assertEqual(events[0].fired_at, "2026-07-04T09:30:00")

    def test_matching_job_fires_once_per_minute(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            event_queue = CronEventQueue(Path(tmpdir))
            scheduler = CronScheduler(Path(tmpdir), event_queue)
            job = CronJob(
                id="job-1",
                cron="30 9 * * *",
                prompt="run morning check",
                recurring=True,
                durable=False,
            )
            scheduler.schedule_job(job)
            now = datetime(2026, 7, 4, 9, 30)

            scheduler._process_once(now)
            scheduler._process_once(now)

            self.assertEqual(len(event_queue.drain()), 1)

    def test_load_events_restores_json_events_to_queue(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            event = CronEvent(
                event_id="event-1",
                job_id="job-1",
                prompt="run saved work",
                fired_at="2026-07-04T09:30:00",
            )
            (path / ".cron_events.json").write_text(
                json.dumps([event.__dict__]),
                encoding="utf-8",
            )
            event_queue = CronEventQueue(path)

            loaded_count = event_queue.load_events()

            self.assertEqual(loaded_count, 1)
            self.assertEqual(event_queue.drain(), [event])


if __name__ == "__main__":
    unittest.main()
