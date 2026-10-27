"""Database guards for persisted voice evaluations."""
from alembic import op
revision='0004'
down_revision='0003'
branch_labels=None
depends_on=None
def upgrade():
    op.create_check_constraint('evaluation_label','turn_evaluations',
        "assessment_label IN ('Strong','Adequate','Partial','Insufficient','Unassessable')")
    op.create_check_constraint('evaluation_scores','turn_evaluations',
        """jsonb_typeof(competency_scores)='array'
        AND jsonb_array_length(jsonb_path_query_array(competency_scores,'$[*].score'))=jsonb_array_length(competency_scores)
        AND NOT jsonb_path_exists(competency_scores,'$[*] ? (@.score < 0 || @.score > 4 || @.score.type() != "number")')""")
    op.create_check_constraint('evaluation_assessability','turn_evaluations',
        "(assessment_label='Unassessable') = (jsonb_array_length(competency_scores)=0)")
def downgrade():
    for name in ('evaluation_assessability','evaluation_scores','evaluation_label'):
        op.drop_constraint(name,'turn_evaluations',type_='check')
