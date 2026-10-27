from pydantic import Field
from .analysis_schemas import StrictModel

class ReportInsight(StrictModel):
    title:str=Field(min_length=1,max_length=160)
    explanation:str=Field(min_length=1,max_length=900)
    turn_ids:list[str]=Field(min_length=1,max_length=5,description='At least one supplied saved-answer turn ID supporting this insight. Omit insights without answer evidence; unassessed coverage gaps belong in the preparation plan, not in strengths or weaknesses.')

class PracticeStep(StrictModel):
    objective_id:str
    evidence_summary:str=Field(default='',max_length=650,description='Why this priority follows from the cited accepted answer and assessment; distinguish an observed gap from missing evidence.')
    review_topics:list[str]=Field(default_factory=list,max_length=5,description='Two to five concrete subtopics tailored to this objective and demonstrated gap. Avoid broad labels such as machine learning or Python alone.')
    action:str=Field(min_length=1,max_length=900,description='A NEW prospective practice exercise; never assume steps or tools the candidate used in past work.')
    success_check:str=Field(min_length=1,max_length=600,description='Check the NEW exercise; do not assume prior project implementation.')
    turn_ids:list[str]=Field(max_length=5)

class ReportNarrative(StrictModel):
    summary:str=Field(min_length=1,max_length=1800)
    strengths:list[ReportInsight]=Field(max_length=6,description='Concise source-linked strengths, normally at most four.')
    weaknesses:list[ReportInsight]=Field(max_length=6,description='Concise source-linked improvement areas, normally at most four.')
    preparation_plan:list[PracticeStep]=Field(max_length=6)

    @classmethod
    def model_json_schema(cls,*args,**kwargs):
        schema=super().model_json_schema(*args,**kwargs)
        # Local defaults read older records; provider output must supply new fields.
        for node in [schema,*schema.get('$defs',{}).values()]:
            if node.get('type')=='object':
                node['required']=list(node.get('properties',{}))
                for value in node.get('properties',{}).values():value.pop('default',None)
        return schema
