from uuid import uuid4

from pydantic import BaseModel, Field

from code_harness.cron_scheduler.runtime import get_cron_scheduler
from code_harness.cron_scheduler.scheduler import CronJob
from code_harness.tools.tools import BaseTool


class ScheduleCronInput(BaseModel):
    cron: str = Field(description="Five-field cron expression, like '0 9 * * *'.")
    prompt: str = Field(description="Prompt to send to the agent when the cron fires.")
    recurring: bool = True
    durable: bool = True
    job_id: str | None = None


class ScheduleCronTool(BaseTool):
    name = "schedule_cron"
    description = "Schedule a cron prompt for the agent to run later."
    input_model = ScheduleCronInput

    def run(self, arguments:ScheduleCronInput)->str:
        scheduler = get_cron_scheduler()
        job = CronJob(
            id=arguments.job_id or f"cron_{uuid4().hex}",
            cron=arguments.cron,
            prompt=arguments.prompt,
            recurring=arguments.recurring,
            durable=arguments.durable,
        )
        return scheduler.schedule_job(job)
    
class ListCronsInput(BaseModel):
    pass


class ListCronsTool(BaseTool):
    name = "list_crons"
    description = "List scheduled cron jobs."
    input_model = ListCronsInput

    def run(self, arguments: ListCronsInput) -> str:
        return get_cron_scheduler().list_jobs_text()
    
class CancelCronInput(BaseModel):
    job_id: str

class CancelCronTool(BaseTool):
    name = "cancel_cron"
    description = "Cancel a scheduled cron job by id."
    input_model = CancelCronInput

    def run(self, arguments: CancelCronInput) -> str:
        job= get_cron_scheduler().remove_job(arguments.job_id)

        if job is None:
            return f"No cron job found id: {arguments.job_id}"
        if job.durable:
            get_cron_scheduler().save_durable_jobs()

        return f"Cancelled cron job: {arguments.job_id}"


    
