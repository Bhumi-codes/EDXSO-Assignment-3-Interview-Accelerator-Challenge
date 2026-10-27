"""Behavioural payload regressions; provider interpretation is checked separately live."""
import asyncio
from copy import deepcopy
from uuid import uuid4
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import select
from test_foundation import fixture
from test_interview import interview,qdict,evaluation
from app.main import app
from app.database import get_db
from app.models import InterviewSession,InterviewLevel,InterviewTurn
from app import interview_service as service
from app.interview_budget import bound_interview_context
from app.interview_schemas import Question,Evaluation
from app.calibration import trails_for_level,examples_for

def test_generation_payload_gets_inventory_project_scope_and_stage_example(interview,monkeypatch):
    import app.interview_ai as ai
    client,_,_,session_id=interview
    db=next(app.dependency_overrides[get_db]())
    row=db.get(InterviewSession,session_id)
    row.candidate_profile={'projects':[{'value':'Image classifier','origin':'explicit','excerpt':'project evidence '*20+'TensorFlow and Keras'}],
        'skills':[{'value':'scikit-learn','origin':'explicit','excerpt':'scikit-learn in a separate tabular predictor'}]}
    level=InterviewLevel(session_id=session_id,level_number=2,question_budget=4)
    db.add(level);db.flush()
    previous=InterviewTurn(level_id=level.id,turn_number=1,question_text='Why did you choose that architecture?',
        question_spec=qdict(1,'architecture'),status='answered',submitted_answer_text='It was the first network I learned. I did not compare architectures.')
    db.add(previous);db.commit()
    _,turns=service.level_and_turns(db,session_id)
    context=service.build_context(db,row,turns,None)
    assert 'TensorFlow and Keras' in context['candidate']['projects'][0]['excerpt']
    assert context['candidate']['skills'][0]['value']=='scikit-learn'
    assert context['asked_question_inventory'][0]['question']==previous.question_text
    captured={}
    async def provider(schema,instructions,data,validate,**kwargs):
        captured.update(data)
        return validate(schema.model_validate({**qdict(2,'evaluation'),'difficulty':2})),None,[]
    monkeypatch.setattr(ai,'structured',provider)
    asyncio.run(ai.generate_question(context,None,2,'new_topic',[previous.question_text]))
    assert captured['asked_question_inventory']==context['asked_question_inventory']
    assert captured['complete_interview_trails'][0]['level']==2
    db.close()

def test_question_inventory_survives_aggressive_request_compaction():
    inventory=[{'ref':f'L3Q{i}','level':3,'question':f'Question {i}: describe the complete proposed pipeline.'} for i in range(1,7)]
    original={'level':3,'asked_question_inventory':inventory,'source_lines':{'S001':'The current answer, unchanged.'},
        'current_answer_supplied_separately':True,'saved_question':qdict(7,'pipeline'),
        'conversation_history':[{'turn_id':str(i),'question':'Question','answer':'older text '*1000} for i in range(14)]}
    before=deepcopy(original)
    fitted,metadata=bound_interview_context(original,'Instructions',Question.model_json_schema(),1800,5000)
    assert metadata['context_mode']>0
    assert fitted['asked_question_inventory']==inventory
    assert fitted['source_lines']==original['source_lines']
    assert original==before

def test_evaluation_uses_the_latest_answer_and_level_specific_boundary_examples(monkeypatch):
    import app.interview_ai as ai
    captured={}
    async def provider(schema,instructions,data,validate,**kwargs):
        captured.update(data)
        value=schema.model_validate({**evaluation(),'memory_update':{'summary':'The candidate acknowledged the comparison limit.','facts':[{'scope':'architecture','statement':'No systematic comparison was performed.','kind':'uncertainty','evidence_ids':['S001']}],'question_parts':[],'useful_next_angles':[]}});value.answer_evidence=['S001']
        return validate(value),None,[]
    monkeypatch.setattr(ai,'structured',provider)
    answer='I chose it because it was the first network I learned; I did not compare alternatives.'
    asyncio.run(ai.evaluate_answer({'level':2,'asked_question_inventory':[{'ref':'L2Q1','question':'Why this architecture?'}]},
        qdict(1,'architecture'),answer))
    assert ' '.join(captured['source_lines'].values())==answer
    assert any(e['category']=='partial_justification' and e['action']=='new_topic' for e in captured['calibration_examples'])
    assert captured['saved_question']['rubric']==qdict(1,'architecture')['rubric']

def test_examples_demonstrate_breadth_with_only_relevant_stage_depth():
    screening=trails_for_level(1)[0]['turns']
    competency=trails_for_level(2)[0]['turns']
    deep=trails_for_level(3)[0]['turns']
    assert [len(screening),len(competency),len(deep)]==[5,4,7]
    for level,turns in ((1,screening),(2,competency),(3,deep)):
        assert all(t['level']==level and 3<=len(t['q'].split())<=60 and t['a'] and t['next'] for t in turns)
    assert any(e['category']=='exhausted_hypothetical' for e in examples_for('evaluation',level=3))


def test_screening_priority_guidance_is_broad_not_two_technical_keywords():
    from types import SimpleNamespace
    item=SimpleNamespace(fit_summary={'requirements':[
        {'key':'framework','category':'skill','weight':3},
        {'key':'architecture','category':'skill','weight':3}]})
    assert service.priority_topics(item,1)==['background_and_role_fit','motivation_and_goals']
    assert service.priority_topics(item,2)==['framework','architecture']


def test_screening_context_includes_broad_resume_evidence_and_not_gap_drilling(interview):
    client,_,_,session_id=interview
    db=next(app.dependency_overrides[get_db]())
    item=db.get(InterviewSession,session_id)
    item.candidate_profile={key:[{'value':key+' evidence','origin':'explicit','excerpt':key}] for key in ('education','experience','skills','achievements','certifications','projects','claims_to_probe')}
    item.fit_summary={'matches':[{'requirement_key':'framework','status':'not_evidenced','reason':'Not in resume','probe_target':'Framework'}]}
    db.commit()
    client.post(f'/api/sessions/{session_id}/interview/start')
    db.expire_all();item=db.get(InterviewSession,session_id)
    _,turns=service.level_and_turns(db,session_id)
    context=service.build_context(db,item,turns,None)
    assert context['candidate']['education'][0]['value']=='education evidence'
    assert context['candidate']['experience'] and context['candidate']['achievements']
    assert context['job_fit_gaps']==[]
    assert 'claims_to_probe' not in context['candidate']
    db.close()


def test_final_level_turn_keeps_answer_and_rubric_without_routing_only_inventory():
    original={'remaining_turns':0,'source_lines':{'S001':'Final accepted answer.'},'saved_question':qdict(7,'reasoning'),
        'asked_question_inventory':[{'ref':'L3Q'+str(i),'question':'Long prior question '*50} for i in range(6)]}
    bounded,_=bound_interview_context(original,'Evaluate final answer',Question.model_json_schema(),1800,7000)
    assert bounded['source_lines']==original['source_lines']
    assert bounded['saved_question']['rubric']==original['saved_question']['rubric']
    assert 'asked_question_inventory' not in bounded
    assert 'asked_question_inventory' in original
