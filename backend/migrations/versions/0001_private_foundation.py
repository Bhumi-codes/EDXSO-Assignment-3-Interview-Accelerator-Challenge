"""Private foundation. Further application tables arrive with their milestones."""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op
revision = '0001'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('profiles',
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('auth.users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('display_name', sa.String(200), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_table('interview_sessions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('profiles.user_id', ondelete='CASCADE'), nullable=False),
        sa.Column('title', sa.String(160), nullable=False),
        sa.Column('jd_text', sa.Text(), nullable=False),
        sa.Column('resume_text', sa.Text(), nullable=False),
        sa.Column('input_metadata', postgresql.JSONB(), nullable=False),
        sa.Column('configuration', postgresql.JSONB(), nullable=False),
        sa.Column('status', sa.String(24), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('draft','analysing','ready','in_progress','completed','ended_early')", name='session_status'))
    op.create_index('ix_sessions_owner_created','interview_sessions',['user_id','created_at'])
    # Browser table access is denied; FastAPI enforces ownership with server SQL.
    for table in ('profiles','interview_sessions'):
        op.execute(f'ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY')
        op.execute(f'REVOKE ALL ON TABLE public.{table} FROM anon, authenticated')

def downgrade():
    op.drop_table('interview_sessions')
    op.drop_table('profiles')
