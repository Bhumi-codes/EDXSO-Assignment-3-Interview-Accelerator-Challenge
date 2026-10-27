from typing import Literal
from uuid import UUID
from pydantic import Field
from .analysis_schemas import StrictModel

Competency=Literal['role_fit','technical_knowledge','problem_solving','communication','confidence','depth','behavioural_fit']
Action=Literal['clarify','deepen','simplify','new_topic']

class Rubric(StrictModel):
    adequate_criteria:list[str]
    useful_evidence:list[str]
    misconceptions:list[str]

class Question(StrictModel):
    question_text:str=Field(min_length=1,description="One focused question, 3 to 60 whitespace-separated words inclusive")
    topic_key:str
    difficulty:Literal[1,2,3]
    target_competencies:list[Competency]
    rubric:Rubric

class CompetencyScore(StrictModel):
    competency:Competency
    score:int=Field(ge=0,le=4)

class Evaluation(StrictModel):
    assessment_label:Literal['Strong','Adequate','Partial','Insufficient','Unassessable']
    competency_scores:list[CompetencyScore]
    reasoning:str
    answer_evidence:list[str]
    strengths:list[str]
    improvements:list[str]
    ideal_direction:str
    recommended_action:Action
    action_reason:str

class AnswerInput(StrictModel):
    turn_id:UUID
    submission_id:UUID
    text:str=Field(min_length=1)
    mode:Literal['voice','text']
    skip:bool=False

class RedoInput(StrictModel):
    request_id:UUID
