"""Synthetic lifecycle checks; no paid or live model calls."""
from copy import deepcopy
from uuid import uuid4,UUID
from unittest.mock import AsyncMock
import asyncio
import pytest
from sqlalchemy import select
from test_foundation import fixture
from test_interview import interview,qdict,evaluation
from app.main import app
from app.database import get_db
from app.models import InterviewSession,InterviewLevel,InterviewTurn,TurnEvaluation,SessionRequirement,RequirementMatch
from app import interview_service as service
from app.llm import AnalysisUnavailable

def submit(client,path,view,text='I built the API',skip=False):
    return client.post(path+'/answer',json={'turn_id':view['current_turn']['id'],
        'submission_id':str(uuid4()),'text':text,'mode':'text','skip':skip})

def test_full_fifteen_turn_lifecycle_and_cross_level_context(interview):
    client,_,_,session_id=interview;path=f'/api/sessions/{session_id}/interview'
    view=client.post(path+'/start').json()
    for index in range(15):
        level=1 if index<4 else 2 if index<8 else 3
        assert view['level']==level
        # A refresh/retry does not create another question or consume budget.
        assert client.post(path+'/advance').json()['current_turn']['id']==view['current_turn']['id']
        result=submit(client,path,view,text=f'I built the API. Earlier unique claim {index}.')
        assert result.status_code==200,result.text
        view=result.json()
    assert view['finalised'] and view['status']=='completed' and view['current_turn'] is None
    assert view['total_turns_used']==15
    assert [len(level['history']) for level in view['levels']]==[4,4,7]
    assert view['coverage']=={'answered':15,'skipped':0,'evaluated':15,'pending_evaluations':0}
    assert service.generate_question.await_count==15 and service.evaluate_answer.await_count==15
    contexts=[call.args[0] for call in service.generate_question.call_args_list]
    assert contexts[4]['level']==2 and contexts[4]['remaining_turns']==4
    assert contexts[8]['level']==3 and contexts[8]['remaining_turns']==7
    assert 'Earlier unique claim 0' in str(contexts[8]['session_memory']['answers'])
    assert {turn['ref'][:2] for turn in contexts[8]['session_memory']['answers']}=={'L1','L2'}
    db=next(app.dependency_overrides[get_db]())
    rows=service.all_turns(db,session_id)
    assert [row.question_spec['difficulty'] for row in rows]==[1]*4+[2]*4+[3]*7
    for level in service.levels_for(db,session_id):
        group=[turn for turn in rows if turn.level_id==level.id]
        by_id={turn.id:turn for turn in group}
        for turn in group:
            depth=0;parent=turn
            while parent.parent_turn_id:
                depth+=1;parent=by_id[parent.parent_turn_id]
            assert depth<=service.CHAIN_CAPS[level.level_number]
    assert client.post(path+'/start').status_code==409
    assert client.post(path+'/advance').status_code==409
    assert client.post(path+'/end').json()['status']=='completed'
    db.close()

def test_failure_on_level_transition_retries_without_rescoring(interview,monkeypatch):
    client,_,_,session_id=interview;path=f'/api/sessions/{session_id}/interview'
    view=client.post(path+'/start').json()
    for _ in range(3):
        view=submit(client,path,view).json()
    generator=service.generate_question
    monkeypatch.setattr(service,'generate_question',AsyncMock(side_effect=AnalysisUnavailable('Synthetic quota')))
    assert submit(client,path,view).status_code==503
    saved=client.get(path).json()
    assert saved['level']==2 and saved['turns_used']==0 and saved['current_turn'] is None
    assert len(saved['levels'][0]['history'])==4 and saved['coverage']['evaluated']==4
    assert client.post(path+'/start').status_code==503 # same new level; no duplicate level
    monkeypatch.setattr(service,'generate_question',generator)
    recovered=client.post(path+'/advance').json()
    assert recovered['level']==2 and recovered['turns_used']==1
    assert service.evaluate_answer.await_count==4
    db=next(app.dependency_overrides[get_db]())
    assert len(service.levels_for(db,session_id))==2
    db.close()

def test_skips_consume_turns_but_have_no_invented_evaluation(interview):
    client,_,_,session_id=interview;path=f'/api/sessions/{session_id}/interview'
    view=client.post(path+'/start').json()
    for _ in range(15):
        response=submit(client,path,view,skip=True);assert response.status_code==200
        view=response.json()
    assert view['status']=='completed' and view['coverage']['skipped']==15
    assert view['coverage']['evaluated']==0 and service.evaluate_answer.await_count==0

@pytest.mark.parametrize('count',[0,2,5,10])
def test_early_end_is_permanent_and_histories_remain_read_only(interview,count):
    client,_,_,session_id=interview;path=f'/api/sessions/{session_id}/interview'
    view=client.post(path+'/start').json()
    for _ in range(count):view=submit(client,path,view).json()
    unanswered=view['current_turn']['id']
    ended=client.post(path+'/end')
    assert ended.status_code==200
    result=ended.json()
    assert result['finalised'] and result['status']=='ended_early'
    assert result['coverage']['answered']==count
    assert result['current_turn'] is None
    assert any(row['id']==unanswered and row['status']=='unanswered_at_finalisation' for row in result['history'])
    assert client.post(path+'/end').json()==result
    for endpoint in ('start','advance'):
        assert client.post(path+'/'+endpoint).status_code==409
    assert client.post(path+'/answer',json={'turn_id':unanswered,'submission_id':str(uuid4()),'text':'New answer','mode':'text'}).status_code==409
    assert client.post(path+'/turns/'+unanswered+'/transcribe?format=wav',content=b'RIFFsynthetic').status_code==409
    assert client.post(f'/api/sessions/{session_id}/documents',json={'jd_text':'Changed JD long enough','resume_text':'Changed resume long enough'}).status_code==409
    db=next(app.dependency_overrides[get_db]())
    levels=service.levels_for(db,session_id)
    assert len(levels)==3
    assert all(level.started_at is None for level in levels if level.status=='not_attempted')
    assert db.get(InterviewSession,session_id).ended_at is not None
    db.close()

def test_ending_after_failed_evaluation_keeps_pending_answer(interview,monkeypatch):
    client,_,_,session_id=interview;path=f'/api/sessions/{session_id}/interview'
    view=client.post(path+'/start').json()
    monkeypatch.setattr(service,'evaluate_answer',AsyncMock(side_effect=AnalysisUnavailable('Synthetic quota')))
    assert submit(client,path,view).status_code==503
    result=client.post(path+'/end').json()
    assert result['coverage']['answered']==1 and result['coverage']['pending_evaluations']==1
    assert result['coverage']['evaluated']==0 and result['history'][0]['answer']=='I built the API'
    assert client.post(path+'/advance').status_code==409

def test_late_generation_cannot_write_after_early_end(interview,monkeypatch):
    client,owner,_,session_id=interview;path=f'/api/sessions/{session_id}/interview'
    view=client.post(path+'/start').json()
    async def late(context,topic,difficulty,action,previous):
        db=next(app.dependency_overrides[get_db]())
        service.end_interview(db,session_id,owner);db.close()
        return {**qdict(2,topic or 'other'),'difficulty':difficulty},[]
    monkeypatch.setattr(service,'generate_question',late)
    assert submit(client,path,view).status_code==409
    saved=client.get(path).json()
    assert saved['status']=='ended_early' and saved['current_turn'] is None
    assert saved['total_turns_used']==1

def test_replayed_answer_across_transition_is_idempotent(interview):
    client,_,_,session_id=interview;path=f'/api/sessions/{session_id}/interview'
    view=client.post(path+'/start').json()
    for _ in range(3):view=submit(client,path,view).json()
    body={'turn_id':view['current_turn']['id'],'submission_id':str(uuid4()),'text':'I built the API','mode':'text'}
    first=client.post(path+'/answer',json=body)
    assert first.json()['level']==2
    calls=service.generate_question.await_count
    assert client.post(path+'/answer',json=body).json()['current_turn']==first.json()['current_turn']
    assert service.generate_question.await_count==calls

def test_redo_has_separate_snapshots_new_requirement_ids_and_no_answers(interview):
    client,owner,_,session_id=interview;path=f'/api/sessions/{session_id}'
    db=next(app.dependency_overrides[get_db]())
    source=db.get(InterviewSession,session_id)
    source.jd_text='Synthetic role requires Python and SQL'
    source.resume_text='Synthetic candidate built an API'
    req_id=uuid4()
    source.fit_summary={'requirements':[{'id':str(req_id),'key':'python','label':'Python','category':'skill','importance':'required','origin':'explicit','weight':3}],'matches':[]}
    source.role_profile={'title':{'value':'Synthetic engineer'}}
    source.candidate_profile={'skills':[{'value':'Python','origin':'explicit','excerpt':'Python'}]}
    source.job_fit_score=75
    db.add(SessionRequirement(id=req_id,session_id=session_id,key='python',label='Python',category='skill',
        importance='required',origin='explicit',evidence=[],scoring_weight=3,include_in_fit=True))
    db.flush()
    db.add(RequirementMatch(requirement_id=req_id,match_status='partial',resume_evidence=[],reason='Synthetic',preparation_note='Practise',probe_target='Ownership'))
    db.commit()
    client.post(path+'/interview/start');client.post(path+'/interview/end')
    key={'request_id':str(uuid4())}
    created=client.post(path+'/redo',json=key)
    assert created.status_code==201,created.text
    value=created.json();new_id=value['id']
    assert new_id!=str(session_id) and value['source_session_id']==str(session_id) and value['status']=='ready'
    assert value['jd_text']=='Synthetic role requires Python and SQL' and value['job_fit_score']==75
    assert value['fit_summary']['requirements'][0]['id']!=str(req_id)
    assert client.post(path+'/redo',json=key).json()['id']==new_id
    fresh=client.get(f'/api/sessions/{new_id}/interview').json()
    assert fresh['history']==[] and fresh['phase']=='not_started'
    db.expire_all()
    assert db.get(InterviewSession,session_id).fit_summary['requirements'][0]['id']==str(req_id)
    new_req=db.scalar(select(SessionRequirement).where(SessionRequirement.session_id==UUID(new_id)))
    assert new_req is not None and db.scalar(select(RequirementMatch).where(RequirementMatch.requirement_id==new_req.id))
    assert client.post(f'/api/sessions/{new_id}/interview/start').status_code==200
    assert client.get(path+'/interview').json()['status']=='ended_early'
    db.close()

def test_other_owner_cannot_end_or_redo_and_active_redo_rejected(interview):
    from app.auth import current_identity,Identity
    client,_,other,session_id=interview;path=f'/api/sessions/{session_id}'
    client.post(path+'/interview/start')
    assert client.post(path+'/redo',json={'request_id':str(uuid4())}).status_code==409
    app.dependency_overrides[current_identity]=lambda:Identity(user_id=other,display_name='Other')
    assert client.post(path+'/interview/end').status_code==404
    assert client.post(path+'/redo',json={'request_id':str(uuid4())}).status_code==404

def test_duplicate_question_from_earlier_level_rejected_before_persistence(interview,monkeypatch):
    client,_,_,session_id=interview;path=f'/api/sessions/{session_id}/interview'
    view=client.post(path+'/start').json();original=view['current_turn']['question_text']
    for _ in range(3):view=submit(client,path,view).json()
    async def duplicate(context,topic,difficulty,action,previous):
        return {**qdict(9,topic or 'new'),'difficulty':difficulty,'question_text':original},[]
    monkeypatch.setattr(service,'generate_question',duplicate)
    assert submit(client,path,view).status_code==503
    saved=client.get(path).json()
    assert saved['level']==2 and saved['turns_used']==0

def test_new_level_uses_its_own_prompt_and_teaching_examples(monkeypatch):
    import app.interview_ai as ai
    captured=[]
    async def provider(schema,instructions,data,validate,**kwargs):
        captured.append((instructions,data))
        return validate(schema.model_validate({**qdict(len(captured),'ownership'),'difficulty':data['difficulty']})),None,[]
    monkeypatch.setattr(ai,'structured',provider)
    for level in (1,2,3):
        asyncio.run(ai.generate_question({'level':level,'conversation_history':[]},None,level,'new_topic',[]))
    assert 'LEVEL 1' in captured[0][0] and 'first-round' in captured[0][0]
    assert 'LEVEL 2' in captured[1][0] and 'Competency' in captured[1][0]
    assert 'LEVEL 3' in captured[2][0] and 'Deep Dive' in captured[2][0]
    assert all(example['level']==2 for example in captured[1][1]['complete_interview_trails'])
    assert all(example['level']==3 for example in captured[2][1]['complete_interview_trails'])


def test_late_evaluation_cannot_write_after_early_end(interview,monkeypatch):
    client,owner,_,session_id=interview;path=f'/api/sessions/{session_id}/interview'
    view=client.post(path+'/start').json()
    async def late(*args):
        db=next(app.dependency_overrides[get_db]())
        service.end_interview(db,session_id,owner);db.close()
        return evaluation(),[]
    monkeypatch.setattr(service,'evaluate_answer',late)
    assert submit(client,path,view).status_code==409
    saved=client.get(path).json()
    assert saved['status']=='ended_early' and saved['coverage']['pending_evaluations']==1
    assert saved['coverage']['evaluated']==0

def test_late_transcription_cannot_change_finalised_history(interview,monkeypatch):
    from app import interview_routes
    client,owner,_,session_id=interview;path=f'/api/sessions/{session_id}/interview'
    turn=client.post(path+'/start').json()['current_turn']['id']
    async def late(*args):
        db=next(app.dependency_overrides[get_db]())
        service.end_interview(db,session_id,owner);db.close()
        return {'text':'A transcript arriving after finalisation','duration':2}
    monkeypatch.setattr(interview_routes,'transcribe_audio',late)
    assert client.post(path+'/turns/'+turn+'/transcribe?format=wav',content=b'RIFFsynthetic').status_code==409
    saved=client.get(path).json()
    assert saved['status']=='ended_early' and saved['history'][0]['raw_transcript'] is None
