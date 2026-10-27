"""Evidence coverage, specific guidance and asynchronous final report regressions."""
import asyncio
from copy import deepcopy
from uuid import uuid4
from unittest.mock import AsyncMock
import pytest
from fastapi import BackgroundTasks
from sqlalchemy import select
from test_foundation import fixture
from test_interview import interview,evaluation,qdict
from test_reports import report_fixture,turn,rated,metrics,sufficient
from app.main import app
from app.database import get_db
from app.models import InterviewSession,InterviewReport,InterviewTurn,TurnEvaluation
from app.interview_coverage import competency_coverage
from app.interview_schemas import Evaluation
from app.report_schemas import ReportNarrative
from app.interview_budget import bound_interview_context
from app.llm import AnalysisUnavailable
from app import interview_service as interviews, interview_routes, report_service as reports, report_routes


def guidance(turns,evaluations,metrics):
    first=next(iter(evaluations),None)
    return {'summary':'Saved evidence identifies a metric-selection gap.',
        'strengths':[], 'weaknesses':[{'title':'Metric selection','explanation':'The cited answer did not justify the metric.','turn_ids':[first]}] if first else [],
        'preparation_plan':[{'objective_id':o['id'],'evidence_summary':o['why'],
            'review_topics':['Precision and recall','Class imbalance','Decision threshold selection'],
            'action':'Compare two thresholds on a small imbalanced validation set and explain the resulting precision and recall.',
            'success_check':'Calculate precision and recall and justify a threshold for the stated error costs.','turn_ids':o['turn_ids']} for o in metrics['priorities']]},[]


def test_coverage_requires_actual_targeted_assessment_not_attempts_or_score_invention():
    turns=[turn(1),turn(2),turn(3),turn(4)]
    turns[0]['target_competencies']=['technical_knowledge']
    turns[1]['status']='skipped';turns[1]['answer']=None
    turns[2]['target_competencies']=['confidence']
    turns[3]['target_competencies']=['role_fit']
    grades={'1':{'assessment_label':'Insufficient','competency_scores':[{'competency':'technical_knowledge','score':0}]},
        '2':rated(4),'3':{'assessment_label':'Unassessable','competency_scores':[]},
        '4':{'assessment_label':'Adequate','competency_scores':[{'competency':'depth','score':4}]}}
    c=competency_coverage(turns,grades,{},2)
    assert c['assessed_dimensions']==['technical_knowledge']
    assert 'confidence' in c['unassessed_dimensions'] and 'depth' in c['unassessed_dimensions']
    assert 'confidence' in c['priority_dimensions']
    assert len(c['dimensions'])==7
    assert c['dimensions'][1]['assessed_question_refs']==['L1Q1']


def test_unassessable_evaluation_can_leave_scores_empty_and_cannot_fabricate_coverage(monkeypatch):
    from app import interview_ai
    async def provider(schema,instructions,data,validate,**kwargs):
        value={**evaluation(),'assessment_label':'Unassessable','competency_scores':[],'answer_evidence':['S001'],'memory_update':{'summary':'The candidate did not claim the assumed experience.','facts':[],'question_parts':[],'useful_next_angles':[]}}
        return validate(schema.model_validate(value)),None,[]
    monkeypatch.setattr(interview_ai,'structured',provider)
    result,_=asyncio.run(interview_ai.evaluate_answer({'level':2},qdict(1,'unsupported'),'I did not claim that experience.'))
    assert result['competency_scores']==[] and result['assessment_label']=='Unassessable'


def test_later_question_opportunities_are_reserved_for_missing_dimensions(interview):
    client,_,_,sid=interview;path=f'/api/sessions/{sid}/interview'
    view=client.post(path+'/start').json()
    for _ in range(9):
        reply=client.post(path+'/answer',json={'turn_id':view['current_turn']['id'],'submission_id':str(uuid4()),'text':'I built the API','mode':'text'})
        assert reply.status_code==200,reply.text
        view=reply.json()
    context,topic,level,action,_=interviews.generate_question.await_args.args
    assert level==3 and action=='new_topic' and topic is None
    coverage=context['competency_coverage']
    assert coverage['reserve_for_unassessed'] and coverage['remaining_interview_questions']==6
    assert coverage['assessed_dimensions']==['role_fit']
    assert 'confidence' in coverage['priority_dimensions']
    assert any(d['label']=='Confidence — clarity and ownership' for d in coverage['dimensions'])


def test_specific_preparation_retains_evidence_and_fits_the_provider_budget(monkeypatch):
    turns,grades=sufficient(1)
    for t in turns:
        t['question']='How would you select an evaluation metric for an imbalanced classifier?'
        t['answer']='I used accuracy. I am not sure how to choose a threshold or compare false positives with false negatives.'
        grades[t['id']]['reasoning']='The answer names accuracy but does not account for class imbalance or error costs.'
        grades[t['id']]['improvements']=['Compare precision and recall under class imbalance.','Justify threshold selection using false-positive and false-negative costs.']
    computed=metrics(turns,grades)
    async def provider(schema,instructions,data,validate,**kwargs):
        bounded,info=bound_interview_context(data,instructions,schema.model_json_schema(),kwargs['max_tokens'],7000)
        assert info['estimated_total_tokens']<=7000
        assert all('assessment_improvement' in v for v in bounded['source_lines'].values())
        assert any('class imbalance' in o['why'] for o in data['objectives'])
        output,_=guidance(turns,grades,computed)
        return validate(ReportNarrative.model_validate(output)),None,[]
    monkeypatch.setattr(reports,'structured',provider)
    output,_=asyncio.run(reports.synthesize_report(turns,grades,computed))
    assert all(len(step['review_topics'])>=2 and step['evidence_summary'] for step in output['preparation_plan'])
    assert all(step['turn_ids'] for step in output['preparation_plan'])


def test_saved_scores_are_available_while_narrative_runs_and_queue_is_idempotent(report_fixture):
    client,owner,_,sid=report_fixture
    db=next(app.dependency_overrides[get_db]());item=db.get(InterviewSession,sid)
    before=client.get(f'/api/sessions/{sid}/report').json()
    tasks=BackgroundTasks()
    assert reports.queue_report(db,item,tasks)
    pending=reports.public_report(db,item)
    assert pending['processing'] and pending['metrics']==before['metrics'] and pending['narrative'] is None
    assert not reports.queue_report(db,item,BackgroundTasks())
    asyncio.run(tasks())
    db.expire_all();ready=reports.public_report(db,db.get(InterviewSession,sid))
    assert ready['status']=='ready' and ready['feedback']==before['feedback']
    assert ready['metrics']==before['metrics'] and not ready['processing']
    assert reports.synthesize_report.await_count==1
    db.close()


def test_ending_automatically_generates_once_and_failure_can_be_retried(interview,monkeypatch):
    client,_,_,sid=interview;path=f'/api/sessions/{sid}'
    monkeypatch.setattr(interview_routes,'queue_report',reports.queue_report)
    monkeypatch.setattr(report_routes,'queue_report',reports.queue_report)
    synth=AsyncMock(side_effect=AnalysisUnavailable('Synthetic quota'))
    monkeypatch.setattr(reports,'synthesize_report',synth)
    view=client.post(path+'/interview/start').json()
    client.post(path+'/interview/answer',json={'turn_id':view['current_turn']['id'],'submission_id':str(uuid4()),'text':'I built the API','mode':'text'})
    assert client.post(path+'/interview/end').status_code==200
    failed=client.get(path+'/report').json()
    assert failed['status']=='failed' and failed['metrics']['overall_score']==75
    assert failed['feedback'][0]['answer']=='I built the API'
    client.post(path+'/report/ensure');client.post(path+'/interview/end')
    assert synth.await_count==1 # Reload/end replay must not burn provider quota.
    synth.side_effect=guidance
    retried=client.post(path+'/report')
    assert retried.status_code==200 and retried.json()['status']=='ready'
    assert retried.json()['feedback']==failed['feedback']
    assert retried.json()['metrics']==failed['metrics']


def test_natural_completion_also_queues_report_and_never_invents_skipped_scores(interview,monkeypatch):
    client,_,_,sid=interview;path=f'/api/sessions/{sid}'
    monkeypatch.setattr(interview_routes,'queue_report',reports.queue_report)
    synth=AsyncMock(side_effect=AssertionError('No model needed for skipped-only evidence'))
    monkeypatch.setattr(reports,'synthesize_report',synth)
    view=client.post(path+'/interview/start').json()
    for _ in range(15):
        response=client.post(path+'/interview/answer',json={'turn_id':view['current_turn']['id'],'submission_id':str(uuid4()),'text':'[skipped]','mode':'text','skip':True})
        assert response.status_code==200,response.text
        view=response.json()
    report=client.get(path+'/report').json()
    assert view['finalised'] and report['status']=='ready' and report['metrics']['overall_score']==0
    assert all(d['score_percent'] is None for d in report['metrics']['competencies'])
    assert synth.await_count==0

def test_preparation_merges_same_topic_across_levels_without_changing_score_units():
    turns=[turn(1,2,'evaluation_metrics'),turn(2,3,'evaluation_metrics')]
    grades={'1':rated(1),'2':rated(1)}
    result=metrics(turns,grades,requirements=[{'key':'evaluation_metrics','label':'Evaluation metrics','origin':'explicit','importance':'required','category':'skill'}],matches=[{'requirement_key':'evaluation_metrics','status':'partial'}])
    plans=[o for o in result['priorities'] if o['title']=='Evaluation metrics']
    assert len(plans)==1 and set(plans[0]['turn_ids'])=={'1','2'}
    assert result['coverage']['evidence_units']==2
    assert result['overall_score']==25
