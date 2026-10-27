"""Voice and adaptive Screening foundation; full lifecycle follows in M4."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg
revision='0003'
down_revision='0002'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('interview_sessions',sa.Column('interview_state',pg.JSONB(),nullable=False,server_default=sa.text("'{}'::jsonb")))
    op.create_table('interview_levels',
        sa.Column('id',pg.UUID(as_uuid=True),primary_key=True),
        sa.Column('session_id',pg.UUID(as_uuid=True),sa.ForeignKey('interview_sessions.id',ondelete='CASCADE'),nullable=False),
        sa.Column('level_number',sa.Integer(),nullable=False),
        sa.Column('question_budget',sa.Integer(),nullable=False),
        sa.Column('status',sa.String(24),nullable=False),
        sa.Column('started_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.Column('ended_at',sa.DateTime(timezone=True),nullable=True),
        sa.UniqueConstraint('session_id','level_number',name='uq_level_number'),
        sa.CheckConstraint('level_number BETWEEN 1 AND 3',name='level_number_range'),
        sa.CheckConstraint('question_budget>0',name='level_budget_positive'))
    op.create_index('ix_interview_levels_session_id','interview_levels',['session_id'])
    op.create_table('interview_turns',
        sa.Column('id',pg.UUID(as_uuid=True),primary_key=True),
        sa.Column('level_id',pg.UUID(as_uuid=True),sa.ForeignKey('interview_levels.id',ondelete='CASCADE'),nullable=False),
        sa.Column('turn_number',sa.Integer(),nullable=False),
        sa.Column('parent_turn_id',pg.UUID(as_uuid=True),nullable=True),
        sa.Column('question_text',sa.Text(),nullable=False),
        sa.Column('question_spec',pg.JSONB(),nullable=False),
        sa.Column('raw_transcript',sa.Text(),nullable=True),
        sa.Column('submitted_answer_text',sa.Text(),nullable=True),
        sa.Column('answer_mode',sa.String(10),nullable=True),
        sa.Column('response_duration_seconds',sa.Float(),nullable=True),
        sa.Column('filler_count',sa.Integer(),nullable=True),
        sa.Column('status',sa.String(30),nullable=False),
        sa.Column('asked_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.Column('answered_at',sa.DateTime(timezone=True),nullable=True),
        sa.UniqueConstraint('level_id','turn_number',name='uq_turn_number'),
        sa.UniqueConstraint('id','level_id',name='uq_turn_parent_level'),
        sa.ForeignKeyConstraint(['parent_turn_id','level_id'],['interview_turns.id','interview_turns.level_id']),
        sa.CheckConstraint('turn_number>0',name='turn_number_positive'),
        sa.CheckConstraint('filler_count IS NULL OR filler_count>=0',name='filler_nonnegative'),
        sa.CheckConstraint("status IN ('asked','answered','skipped','unanswered_at_finalisation')",name='turn_status'),
        sa.CheckConstraint("answer_mode IS NULL OR answer_mode IN ('voice','text')",name='answer_mode'))
    op.create_index('ix_interview_turns_level_id','interview_turns',['level_id'])
    op.create_table('turn_evaluations',
        sa.Column('id',pg.UUID(as_uuid=True),primary_key=True),
        sa.Column('turn_id',pg.UUID(as_uuid=True),sa.ForeignKey('interview_turns.id',ondelete='CASCADE'),unique=True,nullable=False),
        sa.Column('assessment_label',sa.String(20),nullable=False),
        sa.Column('competency_scores',pg.JSONB(),nullable=False),
        sa.Column('reasoning',sa.Text(),nullable=False),
        sa.Column('answer_evidence',pg.JSONB(),nullable=False),
        sa.Column('strengths',pg.JSONB(),nullable=False),
        sa.Column('improvements',pg.JSONB(),nullable=False),
        sa.Column('ideal_direction',sa.Text(),nullable=False),
        sa.Column('recommended_action',sa.String(20),nullable=False),
        sa.Column('action_reason',sa.Text(),nullable=False),
        sa.Column('evaluation_metadata',pg.JSONB(),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False))
    op.execute("""CREATE FUNCTION public.check_interview_parent() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.parent_turn_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.interview_turns p WHERE p.id=NEW.parent_turn_id
        AND p.level_id=NEW.level_id AND p.turn_number<NEW.turn_number
      ) THEN RAISE EXCEPTION 'Parent must be an earlier turn in the same level'; END IF;
      RETURN NEW;
    END $$""")
    op.execute('CREATE TRIGGER interview_parent_guard BEFORE INSERT OR UPDATE ON public.interview_turns FOR EACH ROW EXECUTE FUNCTION public.check_interview_parent()')
    for table in ('interview_levels','interview_turns','turn_evaluations'):
        op.execute(f'ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY')
        op.execute(f'REVOKE ALL ON TABLE public.{table} FROM anon, authenticated')
    op.execute('REVOKE ALL ON FUNCTION public.check_interview_parent() FROM PUBLIC')

def downgrade():
    op.drop_table('turn_evaluations')
    op.drop_table('interview_turns')
    op.execute('DROP FUNCTION public.check_interview_parent()')
    op.drop_table('interview_levels')
    op.drop_column('interview_sessions','interview_state')
