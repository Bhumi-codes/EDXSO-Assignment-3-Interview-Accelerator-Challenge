from copy import deepcopy
from datetime import datetime,timezone
from uuid import uuid4
from unittest.mock import AsyncMock
import asyncio
import pytest
from sqlalchemy import select,delete
from test_foundation import fixture
from test_interview import interview,evaluation,qdict
from app.main import app
from app.database import get_db
from app.models import InterviewSession,InterviewReport,InterviewTurn,TurnEvaluation
from app import report_service as reports
from app.report_scoring import aggregate_report,DIMENSIONS
from app.report_schemas import ReportNarrative
from app.llm import AnalysisUnavailable

def turn(number,level=1,topic=None,parent=None):
    return {'id':str(number),'level':level,'number':number,'question':'A synthetic question?',
        'answer':'I built the API','raw_transcript':None,'status':'answered','parent_turn_id':str(parent) if parent else None,
        'topic_key':topic or f'topic-{number}','mode':'text','target_competencies':list(DIMENSIONS),'filler_count':None}

def rated(score=3,**overrides):
    value=evaluation()
    value['competency_scores']=[{'competency':key,'score':overrides.get(key,score)} for key in DIMENSIONS]
    return value

def metrics(turns,scores,fit=80,requirements=(),matches=(),status='completed'):
    return aggregate_report(turns,scores,list(requirements),list(matches),fit,status)

def sufficient(score=4,**overrides):
    turns=[turn(i+1,level=1 if i<2 else 2 if i<4 else 3) for i in range(8)]
    evaluations={t['id']:rated(score,**overrides) for t in turns}
    return turns,evaluations

def test_explicit_skip_with_no_answers_has_zero_overall_but_no_invented_competency_scores():
    t=turn(1);t['status']='skipped'
    result=metrics([t],{})
    assert result['overall_score']==0
    assert all(d['score_percent'] is None for d in result['competencies'])
    assert result['readiness']['score'] is None and result['coverage']['skipped']==1

def test_chain_averaging_and_prompted_improvement_have_one_topic_weight():
    turns=[turn(1,topic='python'),turn(2,topic='python',parent=1),turn(3,topic='python',parent=2),turn(4,topic='sql')]
    result=metrics(turns,{'1':rated(0),'2':rated(4),'3':rated(4),'4':rated(4)})
    assert result['overall_score']==83.33
    assert result['coverage']['evidence_units']==2
    assert set(result['evidence_units'][0]['prompted_improvement'])==set(DIMENSIONS)

def test_repeated_same_topic_roots_are_collapsed_within_level_not_across_levels():
    result=metrics([turn(1,topic='python'),turn(2,topic='python'),turn(3,2,topic='python')],
        {'1':rated(0),'2':rated(4),'3':rated(4)})
    assert result['coverage']['evidence_units']==2
    assert len(result['evidence_units'][0]['root_turn_ids'])==2
    assert result['overall_score']==75

def test_only_actually_assessed_target_dimensions_receive_scores():
    t=turn(1);t['target_competencies']=['role_fit']
    result=metrics([t],{'1':rated(4)})
    assessed=[d['key'] for d in result['competencies'] if d['score_percent'] is not None]
    assert assessed==['role_fit'] and result['overall_score']==100
    assert result['readiness']['score'] is None

def test_complete_high_evidence_uses_eighty_twenty_formula():
    turns,ratings=sufficient()
    result=metrics(turns,ratings,fit=80)
    assert result['overall_score']==100
    assert result['readiness']['score']==96 and result['readiness']['label']=='Strong Candidate'

def test_missing_fit_uses_disclosed_interview_only_readiness():
    turns,ratings=sufficient()
    result=metrics(turns,ratings,fit=None)
    assert result['overall_score']==100 and result['readiness']['score']==100
    assert 'documented job fit is unavailable' in result['readiness']['formula']

def test_critical_gap_caps_readiness_even_when_other_scores_are_high():
    turns,ratings=sufficient(4,technical_knowledge=1)
    result=metrics(turns,ratings,fit=100)
    assert result['readiness']['raw_formula_score']>80
    assert result['readiness']['score']==64 and result['readiness']['label']=='Needs Preparation'

def test_explicit_unverified_requirement_caps_strong_band_and_inferred_does_not():
    turns,ratings=sufficient()
    requirement={'key':'deployment','label':'Deployment','importance':'required','origin':'explicit','category':'skill'}
    match={'requirement_key':'deployment','status':'not_evidenced'}
    result=metrics(turns,ratings,fit=100,requirements=[requirement],matches=[match])
    assert result['readiness']['score']==79
    requirement['origin']='inferred'
    assert metrics(turns,ratings,fit=100,requirements=[requirement],matches=[match])['readiness']['score']==100

def test_pending_evaluation_does_not_block_seven_dimension_readiness():
    turns,ratings=sufficient();turns.append(turn(9,3))
    result=metrics(turns,ratings)
    assert result['coverage']['pending_evaluations']==1 and result['overall_score']==100
    assert result['readiness']['score']==96 and result['readiness']['coverage_sufficient']

def test_filler_counts_are_raw_only_and_do_not_change_scores():
    turns,ratings=sufficient(3)
    baseline=metrics(turns,ratings)
    turns[0]['raw_transcript']='Um I built it';turns[0]['mode']='voice';turns[0]['filler_count']=1
    result=metrics(turns,ratings)
    assert result['fillers']['total_detected']==1 and result['fillers']['measured_answers']==1
    assert result['overall_score']==baseline['overall_score']
    assert result['readiness']['score']==baseline['readiness']['score']

def test_preparation_priority_combines_demonstrated_gap_and_jd_importance():
    turns=[turn(1,topic='python'),turn(2,topic='sql')]
    requirements=[{'key':'python','label':'Python','importance':'required','origin':'explicit','category':'skill'},
                  {'key':'sql','label':'SQL','importance':'preferred','origin':'explicit','category':'skill'}]
    result=metrics(turns,{'1':rated(1),'2':rated(1)},requirements=requirements)
    assert result['priorities'][0]['title']=='Python'
    assert result['priorities'][0]['turn_ids']==['1']

@pytest.fixture
def report_fixture(interview,monkeypatch):
    client,owner,other,session_id=interview;path=f'/api/sessions/{session_id}/interview'
    view=client.post(path+'/start').json()
    accepted=client.post(path+'/answer',json={'turn_id':view['current_turn']['id'],'submission_id':str(uuid4()),'text':'I built the API','mode':'text'})
    assert accepted.status_code==200
    assert client.post(path+'/end').status_code==200
    async def synthesis(turns,evaluations,metrics):
        first=next(iter(evaluations))
        return {'summary':'Synthetic saved-evidence summary.',
            'strengths':[{'title':'Ownership','explanation':'Specific contribution described.','turn_ids':[first]}],
            'weaknesses':[{'title':'More evidence','explanation':'Clarify the recorded decision.','turn_ids':[first]}],
            'preparation_plan':[{'objective_id':obj['id'],'action':obj['practice_task'],
                'success_check':obj['success_check'],'turn_ids':obj['turn_ids']} for obj in metrics['priorities']]},[]
    monkeypatch.setattr(reports,'synthesize_report',AsyncMock(side_effect=synthesis))
    return interview

def test_reports_block_coaching_before_finalisation(interview):
    client,_,_,session_id=interview;path=f'/api/sessions/{session_id}'
    client.post(path+'/interview/start')
    assert client.get(path+'/report').status_code==409
    assert client.post(path+'/report').status_code==409
    assert client.post(path+'/report/recover-evaluation').status_code==409

def test_final_report_is_owned_cached_and_matches_saved_scores(report_fixture):
    client,_,other,session_id=report_fixture;path=f'/api/sessions/{session_id}/report'
    initial=client.get(path);assert initial.status_code==200
    assert initial.json()['metrics']['overall_score']==75
    assert len(initial.json()['metrics']['competencies'])==7
    assert initial.json()['feedback'][0]['evaluation']['competency_scores'][0]['score']==3
    generated=client.post(path);assert generated.status_code==200,generated.text
    assert generated.json()['status']=='ready'
    assert client.post(path).json()['generated_at']==generated.json()['generated_at']
    assert reports.synthesize_report.await_count==1
    db=next(app.dependency_overrides[get_db]())
    saved=db.scalar(select(InterviewReport).where(InterviewReport.session_id==session_id))
    assert saved.overall_score==75 and saved.readiness_score is None
    from app.auth import current_identity,Identity
    app.dependency_overrides[current_identity]=lambda:Identity(user_id=other,display_name='Other')
    for method in ('get','post'):
        assert getattr(client,method)(path).status_code==404
    assert client.post(path+'/recover-evaluation').status_code==404
    db.close()

def test_report_provider_failure_preserves_scores_and_allows_retry(report_fixture,monkeypatch):
    client,_,_,session_id=report_fixture;path=f'/api/sessions/{session_id}/report'
    original=reports.synthesize_report
    monkeypatch.setattr(reports,'synthesize_report',AsyncMock(side_effect=AnalysisUnavailable('Synthetic quota')))
    assert client.post(path).status_code==503
    saved=client.get(path).json()
    assert saved['status']=='failed' and saved['metrics']['overall_score']==75 and saved['feedback'][0]['answer']=='I built the API'
    monkeypatch.setattr(reports,'synthesize_report',original)
    assert client.post(path).json()['status']=='ready'

def test_zero_answer_report_is_truthful_and_makes_no_model_call(interview,monkeypatch):
    client,_,_,session_id=interview;path=f'/api/sessions/{session_id}'
    client.post(path+'/interview/start');client.post(path+'/interview/end')
    generator=AsyncMock(side_effect=AssertionError('No assessable evidence should not invoke the model'))
    monkeypatch.setattr(reports,'synthesize_report',generator)
    report=client.post(path+'/report')
    assert report.status_code==200 and report.json()['status']=='ready'
    assert report.json()['metrics']['overall_score'] is None and report.json()['narrative']['strengths']==[]
    assert generator.await_count==0

def test_recover_finalised_pending_evaluation_never_reopens_answers(report_fixture,monkeypatch):
    client,_,_,session_id=report_fixture;path=f'/api/sessions/{session_id}'
    db=next(app.dependency_overrides[get_db]())
    turn=db.scalar(select(InterviewTurn).where(InterviewTurn.status=='answered'))
    db.execute(delete(TurnEvaluation).where(TurnEvaluation.turn_id==turn.id));db.commit()
    before=client.get(path+'/report').json()
    assert before['metrics']['coverage']['pending_evaluations']==1
    assessor=AsyncMock(return_value=(evaluation(),[]))
    monkeypatch.setattr(reports,'evaluate_answer',assessor)
    recovered=client.post(path+'/report/recover-evaluation')
    assert recovered.status_code==200,recovered.text
    assert recovered.json()['metrics']['coverage']['pending_evaluations']==0
    assert client.get(path).json()['status']=='ended_early'
    assert client.post(path+'/interview/advance').status_code==409
    assert client.post(path+'/report/recover-evaluation').status_code==200 and assessor.await_count==1
    assert client.get(path+'/report').json()['feedback'][0]['answer']=='I built the API'
    db.close()

def test_unexpired_report_operation_is_not_duplicated(report_fixture):
    client,_,_,session_id=report_fixture
    db=next(app.dependency_overrides[get_db]())
    row=db.scalar(select(InterviewReport).where(InterviewReport.session_id==session_id))
    row.status='generating';row.report_metadata={**row.report_metadata,'operation':{'token':'synthetic','kind':'generate','started_at':datetime.now(timezone.utc).isoformat()}}
    db.commit()
    assert client.post(f'/api/sessions/{session_id}/report').status_code==409
    assert reports.synthesize_report.await_count==0
    db.close()

def test_narrative_cannot_invent_question_references(monkeypatch):
    turns=[turn(1)];evaluations={'1':rated(3)};computed=metrics(turns,evaluations)
    async def provider(schema,instructions,data,validate,**kwargs):
        value=ReportNarrative(summary='Synthetic',strengths=[{'title':'Bad reference','explanation':'Not supported','turn_ids':['foreign-turn']}],
            weaknesses=[],preparation_plan=[])
        return validate(value),None,[]
    monkeypatch.setattr(reports,'structured',provider)
    with pytest.raises(ValueError,match='owned turn IDs'):
        asyncio.run(reports.synthesize_report(turns,evaluations,computed))

def test_narrative_input_is_selected_evidence_not_full_private_documents():
    turns,ratings=sufficient()
    computed=metrics(turns,ratings)
    data=reports.narrative_input(turns,ratings,computed)
    assert len(data['source_lines'])<=6
    assert 'resume_text' not in data and 'jd_text' not in data
    assert all(set(obj['turn_ids'])<=set(data['source_lines']) for obj in data['objectives'])


def test_narrative_schema_cannot_override_computed_scores():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ReportNarrative.model_validate({'summary':'Synthetic','strengths':[],'weaknesses':[],
            'preparation_plan':[],'overall_score':100,'readiness_score':100})

def test_report_recovery_failure_preserves_final_status_and_pending_count(report_fixture,monkeypatch):
    client,_,_,session_id=report_fixture;path=f'/api/sessions/{session_id}'
    db=next(app.dependency_overrides[get_db]())
    db.execute(delete(TurnEvaluation));db.commit()
    before=client.get(path+'/report').json()['feedback']
    monkeypatch.setattr(reports,'evaluate_answer',AsyncMock(side_effect=AnalysisUnavailable('Synthetic quota')))
    assert client.post(path+'/report/recover-evaluation').status_code==503
    after=client.get(path+'/report').json()
    assert after['metrics']['coverage']['pending_evaluations']==1
    assert after['feedback']==before and client.get(path).json()['status']=='ended_early'
    db.close()


def test_report_input_retains_candidate_denial_instead_of_only_grader_suggestion():
    t=turn(1);t['question']='Which NLP techniques did you implement?'
    t['answer']='I did not implement an NLP pipeline. I called an existing LLM API.'
    grades={'1':rated(2)}
    grades['1']['ideal_direction']='Describe tokenization steps you implemented.'
    data=reports.narrative_input([t],grades,metrics([t],grades))
    assert data['source_lines']['1']['accepted_answer_excerpt']==t['answer']
    assert 'ideal_direction' not in data['source_lines']['1']


def test_new_practice_actions_reject_assumed_past_implementation(monkeypatch):
    t=turn(1);grades={'1':rated(2)};computed=metrics([t],grades)
    async def provider(schema,instructions,data,validate,**kwargs):
        steps=[{'objective_id':obj['id'],'action':'Build a new small example for this topic.',
            'success_check':'Explain the result.','turn_ids':obj['turn_ids']} for obj in data['objectives']]
        steps[0]['action']='Describe the tokenization steps you applied in your project.'
        value=ReportNarrative(summary='Synthetic summary',strengths=[],weaknesses=[],preparation_plan=steps)
        return validate(value),None,[]
    monkeypatch.setattr(reports,'structured',provider)
    with pytest.raises(ValueError,match='prospective practice exercise'):
        asyncio.run(reports.synthesize_report([t],grades,computed))


def test_report_schema_repair_does_not_replay_large_rejected_json():
    import json,httpx
    from types import SimpleNamespace
    from pydantic import SecretStr
    from unittest.mock import patch
    from app.llm import structured
    payload={'summary':'Synthetic','strengths':[],'weaknesses':[],'preparation_plan':[]}
    bad={**payload,'weaknesses':[{'title':'Synthetic','explanation':'x'*100,'turn_ids':['1']}]*7}
    seen=[]
    async def respond(*args,**kwargs):
        seen.append(deepcopy(kwargs['json']))
        if len(seen)==1:
            return httpx.Response(400,json={'error':{'code':'json_validate_failed','failed_generation':json.dumps(bad)}})
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(payload)}}],'usage':{}})
    with patch('app.llm.get_settings',return_value=SimpleNamespace(groq_api_key=SecretStr('synthetic'),groq_model='synthetic')),patch('app.llm.httpx.AsyncClient') as factory:
        factory.return_value.__aenter__.return_value.post=AsyncMock(side_effect=respond)
        result,_,_=asyncio.run(structured(ReportNarrative,'Synthetic report',{},lambda v:v,purpose='interview',max_tokens=2400))
    assert result.summary=='Synthetic' and len(seen)==2
    assert not any(message['role']=='assistant' for message in seen[1]['messages'])
    assert 'weaknesses' in seen[1]['messages'][-1]['content']


def test_practice_step_inherits_known_objective_evidence_when_model_omits_it(monkeypatch):
    turns,ratings=sufficient()
    computed=metrics(turns,ratings)
    async def provider(schema,instructions,data,validate,**kwargs):
        value=ReportNarrative(summary='Synthetic',strengths=[],weaknesses=[],preparation_plan=[{
            'objective_id':obj['id'],'action':'Practise explaining one decision.',
            'success_check':'Name a decision and a constraint.','turn_ids':[],
            'evidence_summary':obj['why'],'review_topics':['Decision rationale','Constraints and alternatives']} for obj in data['objectives']])
        return validate(value),None,[]
    monkeypatch.setattr(reports,'structured',provider)
    output,_=asyncio.run(reports.synthesize_report(turns,ratings,computed))
    objectives={o['id']:o for o in reports.narrative_input(turns,ratings,computed)['objectives']}
    for step in output['preparation_plan']:
        objective=objectives[step['objective_id']]
        if objective['source']=='interview' and objective['turn_ids']:
            assert step['turn_ids']==objective['turn_ids'][:1]


def test_response_duration_is_display_only_and_does_not_invalidate_report(report_fixture):
    from app.models import InterviewLevel
    client,_,_,sid=report_fixture;path=f'/api/sessions/{sid}/report'
    generated=client.post(path).json()
    db=next(app.dependency_overrides[get_db]())
    turn=db.scalar(select(InterviewTurn).join(InterviewLevel).where(InterviewLevel.session_id==sid,InterviewTurn.status=='answered'))
    # Only simulate a duration correction; the existing accepted answer is unchanged.
    turn.response_duration_seconds=74.5;db.commit()
    result=client.get(path).json()
    assert result['feedback'][0]['response_duration_seconds']==74.5
    assert result['metrics']==generated['metrics']
    assert result['status']=='ready' and result['generated_at']==generated['generated_at']
    assert result['narrative']==generated['narrative']
    assert reports.synthesize_report.await_count==1
    db.close()


def test_one_answer_three_skips_reduces_overall_once_not_early_end():
    turns=[turn(i) for i in range(1,6)]
    for t in turns[1:4]:t['status']='skipped';t['answer']=None
    turns[4]['status']='unanswered_at_finalisation';turns[4]['answer']=None
    result=metrics(turns,{'1':rated(4)},status='ended_early')
    assert result['answer_quality_score']==100
    assert result['overall_score']==25
    assert result['skip_adjustment']['factor']==.25
    assert result['skip_adjustment']['explicit_skips']==3
    assert all(d['score_percent']==25 for d in result['competencies'])
    assert all(d['answer_quality_percent']==100 for d in result['competencies'])
    assert metrics(turns,{'1':rated(4)},status='completed')['overall_score']==25
    turns[4]['status']='asked'
    assert metrics(turns,{'1':rated(4)},status='ended_early')['overall_score']==25


def test_early_end_without_skips_does_not_reduce_score():
    turns=[turn(1),turn(2)];turns[1]['status']='unanswered_at_finalisation'
    assert metrics(turns,{'1':rated(3)},status='ended_early')['overall_score']==75
    assert metrics(turns,{'1':rated(3)},status='completed')['overall_score']==75


def test_one_answer_three_skips_scoring():
    turns=[turn(i) for i in range(1,5)]
    turns[0]['target_competencies']=['technical_knowledge','problem_solving','communication']
    for t in turns[1:]:t['status']='skipped'
    result=metrics(turns,{'1':rated(4,communication=3)},status='ended_early')
    assert result['answer_quality_score']==91.67
    assert result['overall_score']==22.92


def test_dimension_scores_average_to_overall_without_double_skip_penalty():
    from statistics import mean
    turns=[turn(i) for i in range(1,6)]
    turns[0]['target_competencies']=['technical_knowledge','problem_solving','communication']
    for t in turns[1:4]:t['status']='skipped'
    turns[4]['status']='unanswered_at_finalisation'
    result=metrics(turns,{'1':rated(4,communication=3)},status='ended_early')
    dims={d['key']:d for d in result['competencies']}
    assert dims['technical_knowledge']['score_percent']==25
    assert dims['problem_solving']['score_percent']==25
    assert dims['communication']['score_percent']==18.75
    assert dims['role_fit']['score_percent'] is None
    assert dims['technical_knowledge']['answer_quality_percent']==100
    assert dims['communication']['answer_quality_percent']==75
    assert round(mean(d['score_percent'] for d in dims.values() if d['score_percent'] is not None),2)==result['overall_score']==22.92
    assert result['skip_adjustment']['explicit_skips']==3


def test_all_dimensions_conclude_even_with_short_interview_and_pending_language():
    turns=[turn(1),turn(2),turn(3)]
    grades={'1':rated(3)}
    result=aggregate_report(turns,grades,[],[],80,'ended_early',communication={'1':{'score':3}})
    assert result['coverage']['assessed_dimensions']==7
    assert result['coverage']['pending_evaluations']==2
    assert result['coverage']['pending_communication']==2
    assert result['readiness']['score']==76 and result['readiness']['label']=='Interview Ready'
    assert result['readiness']['coverage_sufficient'] and result['readiness']['reasons']==[]


def test_unassessable_content_does_not_block_conclusion_when_dimensions_covered():
    turns,grades=sufficient(3)
    turns.append(turn(9,3));grades['9']={**rated(),'assessment_label':'Unassessable','competency_scores':[]}
    result=metrics(turns,grades)
    assert result['coverage']['unassessable']==1
    assert result['readiness']['score']==76 and result['readiness']['label']=='Interview Ready'
