from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator


class JobExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    job_id: str
    attempt_number: int
    started_at: datetime
    finished_at: Optional[datetime] = None
    status: str  # "SUCCESS" or "FAILED"
    error_message: Optional[str] = None


class JobBase(BaseModel):
    name: str = Field(..., min_length=1)
    payload: Dict[str, Any]
    schedule_type: str = Field(..., pattern="^(one_time|interval)$")
    run_at: datetime
    interval_seconds: Optional[int] = Field(default=None)
    max_retries: int = Field(default=3, ge=0)


class JobCreate(JobBase):
    @model_validator(mode="after")
    def validate_job_fields(self) -> "JobCreate":
        # Reject run_at in the past
        now = datetime.now(self.run_at.tzinfo) if self.run_at.tzinfo else datetime.utcnow()
        if self.run_at <= now:
            raise ValueError("run_at must be a future datetime")

        # Validate interval settings
        if self.schedule_type == "interval":
            if self.interval_seconds is None or self.interval_seconds <= 0:
                raise ValueError("interval_seconds must be greater than 0 for interval jobs")
        elif self.schedule_type == "one_time":
            if self.interval_seconds is not None:
                raise ValueError("interval_seconds must be null for one_time jobs")

        return self


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    payload: Dict[str, Any]
    schedule_type: str
    run_at: datetime
    interval_seconds: Optional[int] = None
    max_retries: int
    status: str
    created_at: datetime


class JobDetailResponse(JobResponse):
    last_execution: Optional[JobExecutionResponse] = None
    next_run_at: Optional[datetime] = None
    attempt_count: int = 0
    executions: List[JobExecutionResponse] = []
