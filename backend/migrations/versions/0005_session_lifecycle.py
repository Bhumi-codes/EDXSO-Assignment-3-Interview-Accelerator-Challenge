"""Three-level lifecycle timestamps and idempotent separate redo attempts."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg
revision='0005'
down_revision='0004'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('interview_sessions',sa.Column('source_session_id',pg.UUID(as_uuid=True),sa.ForeignKey('interview_sessions.id'),nullable=True))
    op.add_column('interview_sessions',sa.Column('redo_request_id',pg.UUID(as_uuid=True),nullable=True))
    op.add_column('interview_sessions',sa.Column('started_at',sa.DateTime(timezone=True),nullable=True))
    op.add_column('interview_sessions',sa.Column('ended_at',sa.DateTime(timezone=True),nullable=True))
    op.create_unique_constraint('uq_session_redo_request','interview_sessions',['user_id','redo_request_id'])
    op.alter_column('interview_levels','started_at',nullable=True)

def downgrade():
    # Explicitly restore a non-null timestamp only when reversing this migration.
    op.execute("UPDATE interview_levels SET started_at=COALESCE(started_at,ended_at,now())")
    op.alter_column('interview_levels','started_at',nullable=False)
    op.drop_constraint('uq_session_redo_request','interview_sessions',type_='unique')
    for column in ('ended_at','started_at','redo_request_id','source_session_id'):
        op.drop_column('interview_sessions',column)
