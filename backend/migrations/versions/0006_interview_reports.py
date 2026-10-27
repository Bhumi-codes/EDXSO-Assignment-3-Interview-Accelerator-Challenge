"""Private final reports with deterministic scores and source-linked guidance."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg
revision='0006'
down_revision='0005'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('interview_reports',
        sa.Column('id',pg.UUID(as_uuid=True),primary_key=True),
        sa.Column('session_id',pg.UUID(as_uuid=True),sa.ForeignKey('interview_sessions.id',ondelete='CASCADE'),unique=True,nullable=False),
        sa.Column('status',sa.String(20),nullable=False),
        sa.Column('overall_score',sa.Float(),nullable=True),
        sa.Column('competency_summary',pg.JSONB(),nullable=False),
        sa.Column('coverage_summary',pg.JSONB(),nullable=False),
        sa.Column('readiness_label',sa.String(100),nullable=True),
        sa.Column('readiness_score',sa.Float(),nullable=True),
        sa.Column('strengths',pg.JSONB(),nullable=False),
        sa.Column('weaknesses',pg.JSONB(),nullable=False),
        sa.Column('preparation_plan',pg.JSONB(),nullable=False),
        sa.Column('summary',sa.Text(),nullable=True),
        sa.Column('report_metadata',pg.JSONB(),nullable=False),
        sa.Column('generated_at',sa.DateTime(timezone=True),nullable=True),
        sa.CheckConstraint("status IN ('pending','generating','ready','failed')",name='report_status'),
        sa.CheckConstraint('overall_score IS NULL OR overall_score BETWEEN 0 AND 100',name='report_overall_range'),
        sa.CheckConstraint('readiness_score IS NULL OR readiness_score BETWEEN 0 AND 100',name='report_readiness_range'))
    op.execute('ALTER TABLE public.interview_reports ENABLE ROW LEVEL SECURITY')
    op.execute('REVOKE ALL ON TABLE public.interview_reports FROM anon, authenticated')

def downgrade():
    op.drop_table('interview_reports')
