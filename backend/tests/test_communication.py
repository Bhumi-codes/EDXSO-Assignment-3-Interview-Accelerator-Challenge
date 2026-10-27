from copy import deepcopy
from unittest.mock import AsyncMock
from app.communication import VERSION,answer_digest,current_ratings
from app.report_scoring import aggregate_report
from app import report_service as reports
from test_reports import report_fixture,turn,rated
from test_interview import interview,evaluation,qdict
from test_foundation import fixture


def language(t,score):
    return {'score':score,'grammar':'Understandable grammar.','sentence_structure':'Clear sentence structure.',
        'fillers':'No disruptive pattern established.','deduction_examples':[],
        'version':VERSION,'answer_digest':answer_digest(t)}


def test_every_answer_counts_equally_even_without_communication_target():
    turns=[turn(1),turn(2,parent=1),turn(3)]
    for t in turns:t['target_competencies']=['technical_knowledge']
    ratings={t['id']:rated(1) for t in turns}
    original=deepcopy((turns,ratings))
    cache={t['id']:language(t,score) for t,score in zip(turns,[4,4,1])}
    result=aggregate_report(turns,ratings,[],[],80,'completed',communication=cache)
    dims={d['key']:d for d in result['competencies']}
    assert dims['communication']['score_percent']==75 # (4+4+1)/3, not chain weighting
    assert dims['communication']['assessed_units']==3
    assert dims['technical_knowledge']['score_percent']==25
    assert result['coverage']['pending_communication']==0
    assert (turns,ratings)==original


def test_pending_not_zero_and_skip_adjusts_completed_assessment_only():
    turns=[turn(1),turn(2),turn(3)];turns[-1]['status']='skipped'
    result=aggregate_report(turns,{},[],[],80,'completed',communication={'1':language(turns[0],4)})
    assert result['communication']['pending_answers']==1
    assert next(d for d in result['competencies'] if d['key']=='communication')['score_percent']==50
    assert next(d for d in result['competencies'] if d['key']=='communication')['answer_quality_percent']==100
    assert result['skip_adjustment']['assessed_answers']==1
    assert result['skip_adjustment']['factor']==.5
    assert not result['readiness']['coverage_sufficient']


def test_cache_invalidates_changed_answer_and_policy():
    t=turn(1);cache={'1':language(t,4)}
    assert current_ratings([t],cache)==cache
    t['answer']='Different answer'
    assert current_ratings([t],cache)=={}


def test_communication_only_update_preserves_history_and_other_ratings(report_fixture,monkeypatch):
    client,_,_,sid=report_fixture;path=f'/api/sessions/{sid}/report'
    before=client.get(path).json()
    monkeypatch.setattr(reports,'assess_communication',AsyncMock(side_effect=lambda t:language(t,4)))
    response=client.post(path+'/communication')
    assert response.status_code==200,response.text
    after=response.json()
    assert after['feedback']==before['feedback']
    assert after['attempt_status']==before['attempt_status']=='ended_early'
    for b,a in zip(before['metrics']['competencies'],after['metrics']['competencies']):
        if b['key']!='communication':assert a==b
    assert after['metrics']['communication']['assessed_answers']==1
    assert after['metrics']['communication']['pending_answers']==0
    assert client.post(path+'/communication').status_code==200
    assert reports.assess_communication.await_count==1


def test_communication_failure_retains_history_and_retry(report_fixture,monkeypatch):
    client,_,_,sid=report_fixture;path=f'/api/sessions/{sid}/report'
    before=client.get(path).json()['feedback']
    monkeypatch.setattr(reports,'assess_communication',AsyncMock(side_effect=RuntimeError('quota')))
    assert client.post(path+'/communication').status_code==503
    after=client.get(path).json()
    assert after['feedback']==before
    assert after['metrics']['communication']['pending_answers']==1


def test_language_prompt_excludes_technical_context_and_rejects_punctuation_deduction(monkeypatch):
    import asyncio
    import pytest
    from app import communication as comm
    async def provider(schema,instructions,data,validate,**kwargs):
        assert 'technical correctness' in instructions
        assert 'punctuation and sentence boundaries are produced by STT' in instructions
        assert 'jd_text' not in data and 'question' not in data and 'rubric' not in data
        bad=schema(score=2,grammar='Missing punctuation makes this unclear.',sentence_structure='Otherwise clear.',fillers='None.',deduction_examples=[data['accepted_answer']])
        with pytest.raises(ValueError,match='Do not penalise punctuation'):validate(bad)
        good=schema(score=4,grammar='Meaning is grammatically clear.',sentence_structure='Coherent explanation.',fillers='No disruptive pattern.',deduction_examples=[])
        return validate(good),None,[]
    monkeypatch.setattr(comm,'structured',provider)
    t=turn(1);t['answer']='I do not know pie torch, but I can explain my own work.'
    assert asyncio.run(comm.assess_communication(t))['score']==4


def test_summary_is_independent_of_pending_communication_and_cached(report_fixture,monkeypatch):
    client,_,_,sid=report_fixture;path=f'/api/sessions/{sid}/report'
    monkeypatch.setattr(reports,'assess_communication',AsyncMock(side_effect=RuntimeError('Communication unavailable')))
    before=client.get(path).json()
    assert before['metrics']['communication']['pending_answers']==1
    response=client.post(path)
    assert response.status_code==200,response.text
    assert response.json()['status']=='ready'
    assert response.json()['narrative'] is not None
    assert response.json()['metrics']['communication']['pending_answers']==1
    assert response.json()['feedback']==before['feedback']
    assert client.post(path).json()['generated_at']==response.json()['generated_at']
    assert reports.assess_communication.await_count==0
    assert reports.synthesize_report.await_count==1


def test_fresh_full_interview_automatically_scores_all_fifteen_answers(interview,monkeypatch):
    from uuid import uuid4
    from app import interview_service as service
    client,_,_,sid=interview;path=f'/api/sessions/{sid}'
    scorer=AsyncMock(side_effect=lambda t,**kwargs:language(t,4))
    async def questions(context,topic,difficulty,action,previous):
        question=qdict(len(previous)+1,topic or 'ownership')
        question.update(difficulty=difficulty,target_competencies=['role_fit'])
        return question,[]
    monkeypatch.setattr(service,'generate_question',AsyncMock(side_effect=questions))
    from app import communication_jobs
    monkeypatch.setattr(communication_jobs,'assess_communication',scorer)
    view=client.post(path+'/interview/start').json()
    for _ in range(15):
        response=client.post(path+'/interview/answer',json={'turn_id':view['current_turn']['id'],
            'submission_id':str(uuid4()),'text':'I do not know pie torch, but I can explain my own work.','mode':'text'})
        assert response.status_code==200,response.text
        view=response.json()
    assert view['status']=='completed'
    assert scorer.await_count==15
    report=client.get(path+'/report').json()
    assert report['metrics']['communication']['assessed_answers']==15
    assert report['metrics']['communication']['pending_answers']==0
    assert next(d for d in report['metrics']['competencies'] if d['key']=='communication')['score_percent']==100
    assert len(report['feedback'])==15
    assert client.get(path+'/report/pdf').status_code==200


def test_automatic_communication_failure_does_not_block_next_question(interview,monkeypatch):
    from uuid import uuid4
    client,_,_,sid=interview;path=f'/api/sessions/{sid}'
    view=client.post(path+'/interview/start').json()
    response=client.post(path+'/interview/answer',json={'turn_id':view['current_turn']['id'],
        'submission_id':str(uuid4()),'text':'My accepted answer is preserved.','mode':'text'})
    assert response.status_code==200,response.text
    assert response.json()['current_turn']['number']==2
    assert client.post(path+'/interview/end').status_code==200
    report=client.get(path+'/report').json()
    assert report['metrics']['communication']['pending_answers']==1
    assert report['feedback'][0]['answer']=='My accepted answer is preserved.'
