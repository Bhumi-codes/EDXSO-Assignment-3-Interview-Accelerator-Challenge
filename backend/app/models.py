import uuid
from datetime import datetime
from sqlalchemy import Boolean, Float, Integer, UniqueConstraint, CheckConstraint, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class Profile(Base):
    __tablename__ = 'profiles'
    # The FK to Supabase-managed auth.users is installed in the migration.
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class InterviewSession(Base):
    __tablename__ = 'interview_sessions'
    __table_args__ = (
        CheckConstraint("status IN ('draft','analysing','ready','in_progress','completed','ended_early')", name='session_status'),
        Index('ix_sessions_owner_created', 'user_id', 'created_at'),
        UniqueConstraint('user_id','redo_request_id',name='uq_session_redo_request'))
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('profiles.user_id', ondelete='CASCADE'))
    source_session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('interview_sessions.id'),nullable=True)
    redo_request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True),nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),nullable=True)
    title: Mapped[str] = mapped_column(String(160))
    jd_text: Mapped[str] = mapped_column(Text, default='')
    resume_text: Mapped[str] = mapped_column(Text, default='')
    input_metadata: Mapped[dict] = mapped_column(JSONB, default=dict)
    configuration: Mapped[dict] = mapped_column(JSONB, default=lambda: {'budgets': [4,4,7], 'version': 1})
    role_profile: Mapped[dict] = mapped_column(JSONB, default=dict)
    candidate_profile: Mapped[dict] = mapped_column(JSONB, default=dict)
    fit_summary: Mapped[dict] = mapped_column(JSONB, default=dict)
    processing_metadata: Mapped[dict] = mapped_column(JSONB, default=dict)
    interview_state: Mapped[dict] = mapped_column(JSONB, default=dict)
    job_fit_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default='draft')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class SessionRequirement(Base):
    __tablename__='session_requirements'
    __table_args__=(UniqueConstraint('session_id','key',name='uq_requirement_key'),
                   Index('ix_requirements_session','session_id'))
    id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True)
    session_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('interview_sessions.id',ondelete='CASCADE'))
    key: Mapped[str]=mapped_column(String(200))
    label: Mapped[str]=mapped_column(Text)
    category: Mapped[str]=mapped_column(String(30))
    importance: Mapped[str]=mapped_column(String(20))
    origin: Mapped[str]=mapped_column(String(20))
    evidence: Mapped[list]=mapped_column(JSONB)
    scoring_weight: Mapped[int]=mapped_column(Integer)
    include_in_fit: Mapped[bool]=mapped_column(Boolean)

class RequirementMatch(Base):
    __tablename__='requirement_matches'
    id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    requirement_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('session_requirements.id',ondelete='CASCADE'),unique=True)
    match_status: Mapped[str]=mapped_column(String(20))
    resume_evidence: Mapped[list]=mapped_column(JSONB)
    reason: Mapped[str]=mapped_column(Text)
    preparation_note: Mapped[str]=mapped_column(Text)
    probe_target: Mapped[str]=mapped_column(Text)

class InterviewLevel(Base):
    __tablename__='interview_levels'
    __table_args__=(UniqueConstraint('session_id','level_number',name='uq_level_number'),
        CheckConstraint('level_number BETWEEN 1 AND 3',name='level_number_range'),
        CheckConstraint('question_budget > 0',name='level_budget_positive'))
    id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    session_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('interview_sessions.id',ondelete='CASCADE'),index=True)
    level_number: Mapped[int]=mapped_column(Integer)
    question_budget: Mapped[int]=mapped_column(Integer)
    status: Mapped[str]=mapped_column(String(24),default='in_progress')
    started_at: Mapped[datetime | None]=mapped_column(DateTime(timezone=True),nullable=True,server_default=func.now())
    ended_at: Mapped[datetime | None]=mapped_column(DateTime(timezone=True),nullable=True)

class InterviewTurn(Base):
    __tablename__='interview_turns'
    __table_args__=(UniqueConstraint('level_id','turn_number',name='uq_turn_number'),
        UniqueConstraint('id','level_id',name='uq_turn_parent_level'),
        CheckConstraint('turn_number > 0',name='turn_number_positive'),
        CheckConstraint('filler_count IS NULL OR filler_count >= 0',name='filler_nonnegative'))
    id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    level_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('interview_levels.id',ondelete='CASCADE'),index=True)
    turn_number: Mapped[int]=mapped_column(Integer)
    parent_turn_id: Mapped[uuid.UUID | None]=mapped_column(ForeignKey('interview_turns.id'),nullable=True)
    question_text: Mapped[str]=mapped_column(Text)
    question_spec: Mapped[dict]=mapped_column(JSONB)
    raw_transcript: Mapped[str | None]=mapped_column(Text,nullable=True)
    submitted_answer_text: Mapped[str | None]=mapped_column(Text,nullable=True)
    answer_mode: Mapped[str | None]=mapped_column(String(10),nullable=True)
    response_duration_seconds: Mapped[float | None]=mapped_column(Float,nullable=True)
    filler_count: Mapped[int | None]=mapped_column(Integer,nullable=True)
    status: Mapped[str]=mapped_column(String(30),default='asked')
    asked_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())
    answered_at: Mapped[datetime | None]=mapped_column(DateTime(timezone=True),nullable=True)

class TurnEvaluation(Base):
    __tablename__='turn_evaluations'
    id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    turn_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('interview_turns.id',ondelete='CASCADE'),unique=True)
    assessment_label: Mapped[str]=mapped_column(String(20))
    competency_scores: Mapped[list]=mapped_column(JSONB)
    reasoning: Mapped[str]=mapped_column(Text)
    answer_evidence: Mapped[list]=mapped_column(JSONB)
    strengths: Mapped[list]=mapped_column(JSONB)
    improvements: Mapped[list]=mapped_column(JSONB)
    ideal_direction: Mapped[str]=mapped_column(Text)
    recommended_action: Mapped[str]=mapped_column(String(20))
    action_reason: Mapped[str]=mapped_column(Text)
    evaluation_metadata: Mapped[dict]=mapped_column(JSONB)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())

class InterviewReport(Base):
    __tablename__='interview_reports'
    __table_args__=(
        CheckConstraint("status IN ('pending','generating','ready','failed')",name='report_status'),
        CheckConstraint('overall_score IS NULL OR overall_score BETWEEN 0 AND 100',name='report_overall_range'),
        CheckConstraint('readiness_score IS NULL OR readiness_score BETWEEN 0 AND 100',name='report_readiness_range'))
    id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    session_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('interview_sessions.id',ondelete='CASCADE'),unique=True)
    status: Mapped[str]=mapped_column(String(20),default='pending')
    overall_score: Mapped[float | None]=mapped_column(Float,nullable=True)
    competency_summary: Mapped[dict]=mapped_column(JSONB,default=dict)
    coverage_summary: Mapped[dict]=mapped_column(JSONB,default=dict)
    readiness_label: Mapped[str | None]=mapped_column(String(100),nullable=True)
    readiness_score: Mapped[float | None]=mapped_column(Float,nullable=True)
    strengths: Mapped[list]=mapped_column(JSONB,default=list)
    weaknesses: Mapped[list]=mapped_column(JSONB,default=list)
    preparation_plan: Mapped[list]=mapped_column(JSONB,default=list)
    summary: Mapped[str | None]=mapped_column(Text,nullable=True)
    report_metadata: Mapped[dict]=mapped_column(JSONB,default=dict)
    generated_at: Mapped[datetime | None]=mapped_column(DateTime(timezone=True),nullable=True)
