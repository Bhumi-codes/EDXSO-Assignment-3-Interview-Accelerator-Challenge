"""Latency changes retain the interview state machine and save boundaries."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from uuid import uuid4
import httpx,pytest
from fastapi import BackgroundTasks
from pydantic import SecretStr
from sqlalchemy import event
from sqlalchemy.orm import Session
from app import provider_http as transport,llm,memory_jobs as jobs,memory_archive,interview_service as service,interview_routes
from app.models import InterviewSession
from app.main import app
from app.database import get_db
from test_foundation import fixture
from test_interview import interview,qdict


def test_pool_reuses_connections_across_credentials_and_closes_on_shutdown(monkeypatch):
    requests=[]
    async def post(*args,**kwargs):
        requests.append(kwargs)
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':__import__('json').dumps(qdict(1,'example'))}}]})
    settings=SimpleNamespace(groq_api_key=SecretStr('synthetic-content'),groq_communication_api_key=SecretStr('synthetic-language'),groq_model='model',groq_communication_model=None)
    monkeypatch.setattr(llm,'get_settings',lambda:settings)
    with patch('app.provider_http.httpx.AsyncClient') as factory:
        client=factory.return_value.__aenter__.return_value;client.is_closed=False;client.post=AsyncMock(side_effect=post)
        async def run():
            async with transport.provider_lifespan():
                await llm.structured(service.Question,'Question',{},lambda q:q,purpose='interview',max_tokens=400)
                await llm.structured(service.Question,'Question',{},lambda q:q,purpose='interview',max_tokens=400,lane='communication')
                assert factory.call_count==1 and factory.return_value.__aexit__.await_count==0
            assert factory.return_value.__aexit__.await_count==1
            assert asyncio.get_running_loop() not in transport._clients
        asyncio.run(run())
    assert [r['headers']['Authorization'] for r in requests]==['Bearer synthetic-content','Bearer synthetic-language']
    assert not factory.call_args.kwargs.get('headers')


def test_standalone_clients_close_and_are_not_shared_across_event_loops():
    with patch('app.provider_http.httpx.AsyncClient') as factory:
        factory.return_value.__aenter__.return_value.is_closed=False
        async def run():
            async with transport.provider_lifespan():
                async with transport.provider_client() as first:
                    async with transport.provider_client() as second:assert first is second
            assert asyncio.get_running_loop() not in transport._clients
        asyncio.run(run());asyncio.run(run())
        assert factory.call_count==2 and factory.return_value.__aexit__.await_count==2
        async def standalone():
            async with transport.provider_client():pass
        asyncio.run(standalone())
        assert factory.call_count==3 and factory.return_value.__aexit__.await_count==3


def test_optional_rate_pacing_defers_without_sleeping_or_consuming_tokens(monkeypatch):
    state={'limit':8000,'remaining':100,'observed':__import__('time').monotonic()}
    sleep=AsyncMock();monkeypatch.setattr(llm.asyncio,'sleep',sleep)
    async def run():
        with pytest.raises(llm.AnalysisUnavailable,match='Optional'):
            await llm.reserve_tokens({'messages':[],'max_completion_tokens':500},state,optional=True)
    asyncio.run(run());sleep.assert_not_awaited();assert state['remaining']==100


def test_advance_never_awaits_optional_consolidation(interview,monkeypatch):
    client,_,_,sid=interview
    optional=AsyncMock(side_effect=AssertionError('Must not be on the question path'))
    monkeypatch.setattr(memory_archive,'consolidate',optional)
    response=client.post(f'/api/sessions/{sid}/interview/start')
    assert response.status_code==200 and response.json()['current_turn']
    optional.assert_not_awaited()


def prepare_job(interview):
    client,owner,_,sid=interview
    assert client.post(f'/api/sessions/{sid}/interview/start').status_code==200
    db=next(app.dependency_overrides[get_db]());item=db.get(InterviewSession,sid)
    item.interview_state={**item.interview_state,'answer_memory':{'version':'answer-memory-v1','entries':{str(i):{'answer_digest':str(i)} for i in range(8)}}}
    db.commit();return db,db.get(InterviewSession,sid),owner


def test_archive_is_queued_once_and_merges_without_overwriting_new_answer(interview,monkeypatch):
    db,item,owner=prepare_job(interview);bind=db.get_bind();sid=item.id;bg=BackgroundTasks()
    calls=[]
    async def consolidate(*args):
        calls.append(True)
        with Session(bind) as foreground:
            row=foreground.get(InterviewSession,sid);memory=deepcopy(row.interview_state['answer_memory'])
            memory['entries']['new-answer']={'answer_digest':'new'}
            row.interview_state={**row.interview_state,'answer_memory':memory,'operation':{'token':'foreground-operation'},'content_progress':{'latest':'saved'}}
            foreground.commit()
        return {'prefix':6,'groups':[],'status':'ready'},True
    monkeypatch.setattr(jobs,'consolidate',consolidate)
    jobs.queue_archive(db,item,bg);jobs.queue_archive(db,db.get(InterviewSession,sid),bg)
    assert len(bg.tasks)==1 and not calls
    asyncio.run(bg())
    db.expire_all();row=db.get(InterviewSession,sid)
    assert row.interview_state['operation']['token']=='foreground-operation'
    assert row.interview_state['content_progress']=={'latest':'saved'}
    assert row.interview_state['answer_memory']['entries']['new-answer']['answer_digest']=='new'
    assert row.interview_state['answer_memory']['archive']['prefix']==6
    assert row.interview_state['answer_memory']['archive_job']['status']=='ready'
    db.close()


def test_superseded_background_job_cannot_replace_newer_archive(interview,monkeypatch):
    db,item,_=prepare_job(interview);bind=db.get_bind();sid=item.id;bg=BackgroundTasks()
    async def consolidate(*args):
        with Session(bind) as foreground:
            row=foreground.get(InterviewSession,sid);memory=deepcopy(row.interview_state['answer_memory'])
            memory['archive_job']={'token':'newer-job','status':'running'};memory['archive']={'prefix':12,'groups':[]}
            row.interview_state={**row.interview_state,'answer_memory':memory};foreground.commit()
        return {'prefix':6,'groups':[]},True
    monkeypatch.setattr(jobs,'consolidate',consolidate)
    jobs.queue_archive(db,item,bg);asyncio.run(bg());db.expire_all();memory=db.get(InterviewSession,sid).interview_state['answer_memory']
    assert memory['archive']['prefix']==12 and memory['archive_job']['token']=='newer-job'
    db.close()


def test_failed_background_archive_preserves_ready_question(interview,monkeypatch):
    db,item,_=prepare_job(interview);sid=item.id;bg=BackgroundTasks()
    monkeypatch.setattr(jobs,'consolidate',AsyncMock(side_effect=RuntimeError('Synthetic provider failure')))
    jobs.queue_archive(db,item,bg);asyncio.run(bg());db.expire_all();row=db.get(InterviewSession,sid)
    assert row.interview_state['answer_memory']['archive_job']['status']=='deferred'
    assert service.public_view(db,row)['current_turn'] is not None
    assert not row.interview_state.get('error');db.close()


def test_view_and_context_reuse_reads_without_changing_results(interview):
    client,_,_,sid=interview;client.post(f'/api/sessions/{sid}/interview/start')
    db=next(app.dependency_overrides[get_db]());item=db.get(InterviewSession,sid);engine=db.get_bind();queries=[]
    def record(conn,cursor,statement,parameters,context,executemany):
        if statement.lstrip().upper().startswith('SELECT'):queries.append(statement)
    event.listen(engine,'before_cursor_execute',record)
    try:
        view=service.public_view(db,item);assert len(queries)==3 and view['current_turn']
        queries.clear();context=service.build_context(db,item,[],None);assert len(queries)==4
        snapshot=service.load_snapshot(db,sid,include_report=True);queries.clear()
        assert service.build_context(db,item,[],None,snapshot=snapshot)==context
        assert queries==[]
    finally:event.remove(engine,'before_cursor_execute',record);db.close()


def test_pool_closes_on_exception_and_nested_lifespan_does_not_close_early():
    with patch('app.provider_http.httpx.AsyncClient') as factory:
        factory.return_value.__aenter__.return_value.is_closed=False
        async def run():
            with pytest.raises(RuntimeError):
                async with transport.provider_lifespan():
                    async with transport.provider_lifespan():
                        assert factory.call_count==1
                    assert factory.return_value.__aexit__.await_count==0
                    raise RuntimeError('Synthetic shutdown')
            assert asyncio.get_running_loop() not in transport._clients
        asyncio.run(run());assert factory.return_value.__aexit__.await_count==1


def test_archive_rejects_changed_source_digest(interview,monkeypatch):
    db,item,_=prepare_job(interview);bind=db.get_bind();sid=item.id;bg=BackgroundTasks()
    async def consolidate(*args):
        with Session(bind) as foreground:
            row=foreground.get(InterviewSession,sid);memory=deepcopy(row.interview_state['answer_memory'])
            memory['entries']['0']['answer_digest']='changed'
            row.interview_state={**row.interview_state,'answer_memory':memory};foreground.commit()
        return {'prefix':6,'groups':[]},True
    monkeypatch.setattr(jobs,'consolidate',consolidate)
    jobs.queue_archive(db,item,bg);asyncio.run(bg());db.expire_all();memory=db.get(InterviewSession,sid).interview_state['answer_memory']
    assert 'archive' not in memory and memory['archive_job']['status']=='deferred'
    db.close()


def test_transient_provider_retry_reuses_the_same_open_client(monkeypatch):
    import json
    monkeypatch.setattr(llm,'get_settings',lambda:SimpleNamespace(groq_api_key=SecretStr('synthetic'),groq_communication_api_key=None,groq_model='model',groq_communication_model=None))
    monkeypatch.setattr(llm.asyncio,'sleep',AsyncMock())
    responses=[httpx.Response(503,json={}),httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(qdict(1,'example'))}}]})]
    with patch('app.provider_http.httpx.AsyncClient') as factory:
        client=factory.return_value.__aenter__.return_value;client.is_closed=False;client.post=AsyncMock(side_effect=responses)
        async def run():
            async with transport.provider_lifespan():
                result,_,_=await llm.structured(service.Question,'Generate',{},lambda q:q,purpose='interview',max_tokens=400)
                assert result.topic_key=='example' and client.post.await_count==2 and factory.call_count==1
        asyncio.run(run());assert factory.return_value.__aexit__.await_count==1
