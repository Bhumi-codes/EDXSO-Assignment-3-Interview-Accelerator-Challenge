from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

class SessionCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=160)

class SessionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    status: str
    created_at: datetime

class SessionDetail(SessionSummary):
    jd_text: str
    resume_text: str
    role_profile: dict
    candidate_profile: dict
    fit_summary: dict
    processing_metadata: dict
    job_fit_score: float | None
    source_session_id: UUID | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
