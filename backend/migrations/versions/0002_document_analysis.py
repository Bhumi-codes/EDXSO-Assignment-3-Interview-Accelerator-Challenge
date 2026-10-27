"""Evidence-backed document analysis and canonical requirement matches."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg
revision='0002'
down_revision='0001'
branch_labels=None
depends_on=None

def upgrade():
    for name in ('role_profile','candidate_profile','fit_summary','processing_metadata'):
        op.add_column('interview_sessions',sa.Column(name,pg.JSONB(),nullable=False,server_default=sa.text("'{}'::jsonb")))
    op.add_column('interview_sessions',sa.Column('job_fit_score',sa.Float(),nullable=True))
    op.create_check_constraint('fit_score_range','interview_sessions','job_fit_score IS NULL OR (job_fit_score >= 0 AND job_fit_score <= 100)')
    op.create_table('session_requirements',
        sa.Column('id',pg.UUID(as_uuid=True),primary_key=True),
        sa.Column('session_id',pg.UUID(as_uuid=True),sa.ForeignKey('interview_sessions.id',ondelete='CASCADE'),nullable=False),
        sa.Column('key',sa.String(200),nullable=False),
        sa.Column('label',sa.Text(),nullable=False),
        sa.Column('category',sa.String(30),nullable=False),
        sa.Column('importance',sa.String(20),nullable=False),
        sa.Column('origin',sa.String(20),nullable=False),
        sa.Column('evidence',pg.JSONB(),nullable=False),
        sa.Column('scoring_weight',sa.Integer(),nullable=False),
        sa.Column('include_in_fit',sa.Boolean(),nullable=False),
        sa.UniqueConstraint('session_id','key',name='uq_requirement_key'),
        sa.CheckConstraint("importance IN ('required','preferred','unspecified')",name='requirement_importance'),
        sa.CheckConstraint("origin IN ('explicit','inferred')",name='requirement_origin'),
        sa.CheckConstraint("((origin='inferred' OR importance='unspecified') AND scoring_weight=0 AND NOT include_in_fit) OR (origin='explicit' AND importance='required' AND scoring_weight=3 AND include_in_fit) OR (origin='explicit' AND importance='preferred' AND scoring_weight=1 AND include_in_fit)",name='requirement_weight'))
    op.create_index('ix_requirements_session','session_requirements',['session_id'])
    op.create_table('requirement_matches',
        sa.Column('id',pg.UUID(as_uuid=True),primary_key=True),
        sa.Column('requirement_id',pg.UUID(as_uuid=True),sa.ForeignKey('session_requirements.id',ondelete='CASCADE'),unique=True,nullable=False),
        sa.Column('match_status',sa.String(20),nullable=False),
        sa.Column('resume_evidence',pg.JSONB(),nullable=False),
        sa.Column('reason',sa.Text(),nullable=False),
        sa.Column('preparation_note',sa.Text(),nullable=False),
        sa.Column('probe_target',sa.Text(),nullable=False),
        sa.CheckConstraint("match_status IN ('strong','partial','not_evidenced','not_assessed')",name='match_status'))
    for table in ('session_requirements','requirement_matches'):
        op.execute(f'ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY')
        op.execute(f'REVOKE ALL ON TABLE public.{table} FROM anon, authenticated')

def downgrade():
    op.drop_table('requirement_matches')
    op.drop_table('session_requirements')
    op.drop_constraint('fit_score_range','interview_sessions',type_='check')
    for name in ('job_fit_score','role_profile','candidate_profile','fit_summary','processing_metadata'):
        op.drop_column('interview_sessions',name)
