"""Separate LLM roles, cumulative provenance, complete chunks and independent delivery."""
import asyncio,json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from uuid import uuid4
import httpx,pytest
from pydantic import SecretStr
from sqlalchemy import select
from fastapi import BackgroundTasks
from test_foundation import fixture
from test_interview import interview,evaluation,qdict
from app import llm,interview_ai as ai,answer_memory as memory,communication as comm,communication_jobs as jobs,interview_service as service,interview_routes
from app.answer_memory import MemoryUpdate,validate_update,source_chunks,store_update,memory_context
from app.fit import source_lines
from app.interview_budget import bound_interview_context
from app.database import get_db
from app.main import app
from app.models import InterviewSession,InterviewTurn,TurnEvaluation,InterviewReport


def update_for(answer,kind='experience',scope='example'):
    first=next(iter(source_lines(answer)))
    return {'summary':answer[:200],'facts':[{'scope':scope,'statement':answer[:180],'kind':kind,'evidence_ids':[first]}],
        'question_parts':[{'objective':'Explain the requested experience','status':'unavailable' if kind in ('no_experience','declined') else 'answered','evidence_ids':[first]}],
        'useful_next_angles':['Consider another relevant supported objective.']}


def test_key_routing_and_rate_pools_do_not_mix_credentials():
    calls=[];saved=dict(llm.rate_state);llm.rate_state.clear();llm.communication_rate_states.clear()
    async def respond(*args,**kw):
        calls.append(deepcopy(kw));communication=kw['headers']['Authorization']=='Bearer synthetic-communication'
        headers={'x-ratelimit-limit-tokens':'16000' if communication else '8000','x-ratelimit-remaining-tokens':'15000' if communication else '7500'}
        return httpx.Response(200,headers=headers,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(qdict(1,'example'))}}],'usage':{}})
    settings=SimpleNamespace(groq_api_key=SecretStr('synthetic-content'),groq_communication_api_key=SecretStr('synthetic-communication'),groq_model='content-model',groq_communication_model='communication-model')
    async def run():
        await llm.structured(ai.Question,'Question',{},lambda v:v,purpose='interview',max_tokens=500)
        await llm.structured(ai.Question,'Question',{},lambda v:v,purpose='interview',max_tokens=500,lane='communication')
    try:
        with patch('app.llm.get_settings',return_value=settings),patch('app.llm.httpx.AsyncClient') as factory:
            factory.return_value.__aenter__.return_value.post=AsyncMock(side_effect=respond)
            asyncio.run(run())
        assert [r['json']['model'] for r in calls]==['content-model','communication-model']
        assert calls[0]['headers']['Authorization']=='Bearer synthetic-content'
        assert calls[1]['headers']['Authorization']=='Bearer synthetic-communication'
        assert llm.rate_state['limit']==8000
        assert next(iter(llm.communication_rate_states.values()))['limit']==16000
    finally:
        llm.rate_state.clear();llm.rate_state.update(saved);llm.communication_rate_states.clear();llm.communication_rate_locks.clear()


def test_communication_key_falls_back_until_configured():
    settings=SimpleNamespace(groq_api_key=SecretStr('synthetic-fallback'),groq_model='same-model')
    seen=[];saved=dict(llm.rate_state);llm.rate_state.clear()
    async def respond(*args,**kw):
        seen.append(kw)
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(qdict(1,'example'))}}],'usage':{}})
    try:
        with patch('app.llm.get_settings',return_value=settings),patch('app.llm.httpx.AsyncClient') as factory:
            factory.return_value.__aenter__.return_value.post=AsyncMock(side_effect=respond)
            asyncio.run(llm.structured(ai.Question,'Question',{},lambda v:v,purpose='interview',max_tokens=500,lane='communication'))
        assert seen[0]['headers']['Authorization']=='Bearer synthetic-fallback' and seen[0]['json']['model']=='same-model'
    finally:llm.rate_state.clear();llm.rate_state.update(saved)


def test_memory_validation_rejects_foreign_evidence_and_distinguishes_omission():
    answer='I have not used PyTorch. I used TensorFlow for the classifier.'
    value=MemoryUpdate.model_validate(update_for(answer,'no_experience','PyTorch'))
    validate_update(value,answer)
    value.facts[0].evidence_ids=['S999']
    with pytest.raises(ValueError,match='source IDs'):validate_update(value,answer)
    value.facts=[];value.question_parts[0].status='not_provided';value.question_parts[0].evidence_ids=[]
    validate_update(value,answer)
    value.question_parts[0].status='unavailable'
    with pytest.raises(ValueError,match='status needs'):validate_update(value,answer)


def test_llm2_assesses_content_and_extracts_memory_without_communication(monkeypatch):
    answer='I have not used PyTorch. I used TensorFlow and Keras for my classifier.'
    captured={}
    async def provider(schema,instructions,data,validate,**kwargs):
        captured.update(data)
        assert 'LLM1 alone handles' in instructions
        assert 'accepted_answer' not in data and 'aligned_internal_pauses' not in data
        value=schema.model_validate({**evaluation(),'answer_evidence':['S001'],'memory_update':update_for(answer,'no_experience','PyTorch')})
        return validate(value),None,[]
    monkeypatch.setattr(ai,'structured',provider)
    value,_=asyncio.run(ai.evaluate_answer({'level':2,'session_memory':{'answers':[],'boundaries':[],'relevant_claims':[]}},qdict(1,'framework'),answer))
    assert value['memory_update']['facts'][0]['kind']=='no_experience'
    assert ' '.join(captured['source_lines'].values())==answer
    assert all(s['competency']!='communication' for s in value['competency_scores'])


def test_cumulative_memory_survives_levels_and_never_replays_raw_history(interview,monkeypatch):
    client,owner,other,sid=interview;path=f'/api/sessions/{sid}/interview'
    async def assess(context,question,answer,**kwargs):
        kind='no_experience' if 'not used PyTorch' in answer else 'hypothetical' if 'would' in answer else 'experience'
        return {**evaluation(),'answer_evidence':[answer],'memory_update':update_for(answer,kind,'PyTorch' if kind=='no_experience' else 'project')},[]
    monkeypatch.setattr(service,'evaluate_answer',AsyncMock(side_effect=assess))
    view=client.post(path+'/start').json()
    answers=['I have not used PyTorch.','I would compare two classifiers in a future experiment.','I implemented input validation.','I checked held-out accuracy.','I documented the result.']
    for answer in answers:
        response=client.post(path+'/answer',json={'turn_id':view['current_turn']['id'],'submission_id':str(uuid4()),'text':answer,'mode':'text'})
        assert response.status_code==200,response.text
        view=response.json()
    context=service.generate_question.call_args.args[0]
    assert 'conversation_history' not in context and 'history_index' not in context and 'jd_text' not in context
    cumulative=context['session_memory']
    assert len(cumulative['answers'])==5
    assert {r['ref'][:2] for r in cumulative['answers']}=={'L1','L2'}
    assert any(f['kind']=='no_experience' and 'PyTorch' in f['statement'] for f in cumulative['boundaries'])
    assert any(f['kind']=='hypothetical' for f in cumulative['boundaries'])
    db=next(app.dependency_overrides[get_db]());item=db.get(InterviewSession,sid)
    assert len(item.interview_state['answer_memory']['entries'])==5
    assert [t.submitted_answer_text for t in service.all_turns(db,sid) if t.status=='answered']==answers
    before=deepcopy(item.interview_state['answer_memory'])
    assert client.post(path+'/advance').status_code==200
    db.expire_all();assert db.get(InterviewSession,sid).interview_state['answer_memory']==before
    db.close()


def test_legacy_memory_backfill_is_idempotent_and_does_not_regrade(interview,monkeypatch):
    client,owner,_,sid=interview;path=f'/api/sessions/{sid}/interview'
    view=client.post(path+'/start').json()
    client.post(path+'/answer',json={'turn_id':view['current_turn']['id'],'submission_id':str(uuid4()),'text':'I have not used PyTorch.','mode':'text'})
    db=next(app.dependency_overrides[get_db]());item=db.get(InterviewSession,sid)
    row=db.scalar(select(TurnEvaluation).join(InterviewTurn).where(InterviewTurn.status=='answered'))
    before=(row.assessment_label,deepcopy(row.competency_scores),row.reasoning)
    state=dict(item.interview_state);state.pop('answer_memory',None);state['operation']={'token':'backfill','started_at':'2026-10-27T00:00:00+00:00'};item.interview_state=state;db.commit()
    async def batch(records):return {r['ref']:update_for(r['answer'],'no_experience','PyTorch') for r in records},[]
    extractor=AsyncMock(side_effect=batch);monkeypatch.setattr(service,'extract_batch',extractor)
    asyncio.run(service.ensure_answer_memory(db,item,'backfill'))
    asyncio.run(service.ensure_answer_memory(db,item,'backfill'))
    assert extractor.await_count==1 and len(item.interview_state['answer_memory']['entries'])==1
    assert (row.assessment_label,row.competency_scores,row.reasoning)==before
    assert db.scalar(select(InterviewTurn.submitted_answer_text).where(InterviewTurn.status=='answered'))=='I have not used PyTorch.'
    db.close()


def test_long_content_reads_every_source_chunk_and_consolidates_once(monkeypatch):
    answer=' '.join(f'Segment {i} explains validation and a documented limitation.' for i in range(210))
    seen=[];stages=[]
    async def provider(schema,instructions,data,validate,**kwargs):
        bounded,info=bound_interview_context(data,llm.INTERVIEW_SYSTEM_PREFIX+instructions,schema.model_json_schema(),kwargs['max_tokens'],7000)
        assert info['estimated_total_tokens']<=7000
        if schema is memory.MemoryUpdate:
            if 'source_lines' in data:
                stages.append('chunk');seen.extend(data['source_lines'])
                ids=list(data['source_lines']);base=update_for(answer)
                base['summary']='A partial discussion of validation.'
                base['facts']=[{'scope':'validation','statement':'A validation procedure is described.','kind':'knowledge','evidence_ids':[ids[0],ids[-1]]}]
                base['question_parts'][0]['evidence_ids']=[ids[0]]
            else:
                stages.append('merge');base=deepcopy(data['partial_updates'][0])
                ids=list(dict.fromkeys(s for part in data['partial_updates'] for f in part['facts'] for s in f['evidence_ids']))
                base['facts'][0]['evidence_ids']=[ids[0],ids[-1]]
            return validate(schema.model_validate(base)),None,[]
        stages.append('assessment')
        assert schema is ai.Evaluation and 'memory_update' not in schema.model_fields
        assert data['answer_processing']['chunks']>1 and 'complete_answer_memory' in data
        value={**evaluation(),'answer_evidence':[next(iter(data['source_lines']))]}
        if 'memory_update' in schema.model_fields:value['memory_update']=data['complete_answer_memory']
        return validate(schema.model_validate(value)),None,[]
    monkeypatch.setattr(ai,'structured',provider);monkeypatch.setattr(memory,'structured',provider)
    value,_=asyncio.run(ai.evaluate_answer({'level':2},qdict(1,'validation'),answer))
    assert len(seen)==len(set(seen)) and set(seen)==set(source_lines(answer))
    assert stages.count('chunk')>=4 and stages.count('assessment')==1 and 'merge' in stages
    assert value['memory_update']['facts'] and value['competency_scores']


def test_failed_chunk_resumes_saved_progress_without_reprocessing_earlier_part(monkeypatch):
    answer=('A complete statement about validation. '*220);cache={};seen=[];fail=True
    async def provider(schema,instructions,data,validate,**kwargs):
        nonlocal fail
        seen.append(data['part'])
        if data['part']==2 and fail:fail=False;raise RuntimeError('Synthetic quota')
        ids=list(data['source_lines']);value=update_for(answer);value['facts'][0]['evidence_ids']=[ids[0]];value['question_parts'][0]['evidence_ids']=[ids[0]]
        return validate(schema.model_validate(value)),None,[]
    async def save(key,value):cache[key]=value
    monkeypatch.setattr(memory,'structured',provider)
    with pytest.raises(RuntimeError):asyncio.run(memory.extract_chunks(answer,qdict(1,'validation'),cache=cache,progress=save))
    values,_=asyncio.run(memory.extract_chunks(answer,qdict(1,'validation'),cache=cache,progress=save))
    assert seen.count(1)==1 and len(values)==len(source_chunks(answer))


def test_llm1_reads_all_answer_parts_and_python_deducts_delivery_only_once(monkeypatch):
    answer=('A clear explanation of validation and its limits. '*190)+' basically '*5
    pauses=[{'id':f'p{i}','duration_seconds':26 if i==0 else 8,'aligned':True,'before':'I chose it because','after':'it suited the data'} for i in range(18)]
    turn={'id':'voice','status':'answered','answer':answer,'raw_transcript':answer,'mode':'voice','delivery_metrics':{'status':'measured','pauses':pauses}}
    seen=[];classified=[]
    async def provider(schema,instructions,data,validate,**kwargs):
        assert kwargs['lane']=='communication'
        assert not any(k in data for k in ('question','rubric','candidate','jd_text','session_memory','source_lines','raw_transcript_for_filler_observation_only'))
        local=data['aligned_internal_pauses'];classified.extend(p['id'] for p in local)
        checks=[{'id':p['id'],'classification':'unfinished','reason':'The because clause resumes.'} for p in local]
        if schema is comm.PauseBatch:return validate(schema(pause_checks=checks)),None,[]
        seen.append(data['accepted_answer'])
        value=schema(score=4,grammar='Clear grammar.',sentence_structure='Coherent structure.',fillers='Python counts the expressions.',pause_checks=checks,unfinished_pause_ids=[p['id'] for p in local],deduction_examples=[])
        return validate(value),None,[]
    monkeypatch.setattr(comm,'structured',provider)
    result=asyncio.run(comm.assess_communication(turn))
    assert ''.join(seen)==answer and len(seen)>1
    assert len(classified)==len(set(classified))==18
    assert result['base_language_score']==4 and result['score']==3.72
    assert result['delivery']['filler_deduction_points']==2 and result['delivery']['pause_deduction_points']==5


def test_communication_job_runs_after_content_response_and_preserves_memory(interview,monkeypatch):
    client,owner,_,sid=interview
    db=next(app.dependency_overrides[get_db]());service.start(db,sid,owner)
    view=asyncio.run(service.advance(db,sid,owner))
    from app.interview_schemas import AnswerInput
    service.accept_answer(db,sid,owner,AnswerInput(turn_id=view['current_turn']['id'],submission_id=uuid4(),text='I built the API',mode='text'))
    next_view=asyncio.run(service.advance(db,sid,owner))
    assessor=AsyncMock(return_value={'score':4,'version':comm.VERSION,'answer_digest':comm.answer_digest({'answer':'I built the API','raw_transcript':None,'mode':'text'})})
    monkeypatch.setattr(jobs,'assess_communication',assessor)
    tasks=BackgroundTasks();interview_routes.completed_view(next_view,db,sid,owner,tasks)
    assert next_view['current_turn'] and assessor.await_count==0
    before=deepcopy(db.get(InterviewSession,sid).interview_state['answer_memory'])
    asyncio.run(tasks());db.expire_all()
    assert assessor.await_count==1
    assert db.get(InterviewSession,sid).interview_state['answer_memory']==before
    assert len(db.scalar(select(InterviewReport).where(InterviewReport.session_id==sid)).report_metadata['communication'])==1
    db.close()


def test_full_interview_memory_and_latest_answer_fit_actual_role_prompts(monkeypatch):
    context={'level':3,'remaining_turns':1,'followup_chain_cap':2,
        'session_memory':{'version':'answer-memory-v1','answers':[
            {'ref':f'L3Q{i}','summary':'The candidate explains a supported contribution and identifies the remaining limitations.',
             'assessment':'Partial','strengths':['A specific contribution was identified.'],'gaps':['The validation comparison was not justified.'],
             'question_parts':[{'objective':'Explain the implementation and its evaluation','status':'partial'}]} for i in range(15)],
            'boundaries':[{'ref':f'L3Q{i}','scope':'documented project '+str(i),'kind':'uncertainty','statement':'Exact hyperparameter values are unavailable without reviewing the notebook; no systematic comparison is claimed.'} for i in range(15)],
            'relevant_claims':[{'ref':f'L3Q{i}','scope':'classifier','kind':'experience','statement':'The classifier used TensorFlow and Keras with a documented validation result.'} for i in range(10)],'latest_update':{'summary':'The newest answer and its qualifications. '*10,'facts':[{'scope':'supported implementation','statement':'A detailed supported claim with a source-linked qualification. '*5,'kind':'knowledge','evidence_ids':['S001']} for _ in range(6)],'question_parts':[],'useful_next_angles':['Ask an available missing objective.']}},
        'candidate':{'projects':[{'value':'Documented project '+str(i),'origin':'explicit','excerpt':'Python, validation and a specifically documented technology.'} for i in range(3)]},
        'role_requirements':[{'key':str(i),'label':'Relevant technical and behavioural requirement '+str(i),'origin':'explicit','importance':'required','category':'skill'} for i in range(12)],
        'asked_question_inventory':[{'ref':f'L3Q{i}','question':f'For objective {i}, what evidence justified the implementation decision and its validation?'} for i in range(15)]}
    answer='I implemented validation and checked the results. '+('I would verify an alternative before claiming that this approach is better. '*16)
    seen=[]
    async def provider(schema,instructions,data,validate,**kwargs):
        bounded,info=bound_interview_context(data,llm.INTERVIEW_SYSTEM_PREFIX+instructions,schema.model_json_schema(),kwargs['max_tokens'],7000)
        assert info['estimated_total_tokens']<=7000
        assert len(bounded['session_memory']['boundaries'])==(15 if schema.__name__=='ScopedQuestion' else 6)
        assert 'conversation_history' not in bounded
        seen.append(schema.__name__)
        if schema.__name__=='ScopedQuestion':return validate(schema.model_validate({**qdict(16,'new-scope'),'difficulty':3})),None,[]
        assert bounded['source_lines']==data['source_lines']
        return validate(schema.model_validate({**evaluation(),'answer_evidence':['S001'],'memory_update':update_for(answer)})),None,[]
    monkeypatch.setattr(ai,'structured',provider)
    asyncio.run(ai.generate_question(context,None,3,'new_topic',[]))
    asyncio.run(ai.evaluate_answer(context,qdict(1,'validation'),answer))
    assert seen==['ScopedQuestion','ContentEvaluation']


def test_new_communication_credential_does_not_wait_for_content_rate_lock():
    settings=SimpleNamespace(groq_api_key=SecretStr('content-lock-test'),groq_communication_api_key=SecretStr('communication-lock-test'),groq_model='content',groq_communication_model='communication')
    response=httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(qdict(1,'example'))}}],'usage':{}})
    async def run():
        await llm.rate_lock.acquire()
        try:
            return await asyncio.wait_for(llm.structured(ai.Question,'Question',{},lambda v:v,purpose='interview',max_tokens=500,lane='communication'),timeout=1)
        finally:llm.rate_lock.release()
    try:
        with patch('app.llm.get_settings',return_value=settings),patch('app.llm.httpx.AsyncClient') as factory:
            factory.return_value.__aenter__.return_value.post=AsyncMock(return_value=response)
            result,_,_=asyncio.run(run())
        assert result.topic_key=='example'
    finally:llm.communication_rate_states.clear();llm.communication_rate_locks.clear()


def test_chunk_boundaries_remain_in_cumulative_memory_after_consolidation():
    answer='I have not used PyTorch. I used TensorFlow for the classifier.'
    turn=SimpleNamespace(id=uuid4(),level_id='level',turn_number=1,status='answered',question_text='What did you implement?',question_spec={'topic_key':'classifier'},submitted_answer_text=answer)
    chunk=update_for(answer,'no_experience','PyTorch')
    combined={'summary':'The candidate describes a TensorFlow classifier.','facts':[],'question_parts':[],'useful_next_angles':[]}
    item=SimpleNamespace(interview_state={'content_progress':{str(turn.id):{'answer_digest':memory.digest(answer),'chunks':{'0':chunk}}}})
    store_update(item,turn,combined)
    projected=memory_context([turn],{},item.interview_state,{'level':2})
    assert any(f['kind']=='no_experience' and 'PyTorch' in f['statement'] for f in projected['boundaries'])
    assert item.interview_state['answer_memory']['entries'][str(turn.id)]['parts']['0']==chunk


def test_communication_scheduler_failure_does_not_break_saved_content_response(interview,monkeypatch):
    client,_,_,sid=interview;path=f'/api/sessions/{sid}/interview'
    view=client.post(path+'/start').json()
    monkeypatch.setattr(interview_routes,'queue_communication',lambda *args,**kwargs:(_ for _ in ()).throw(RuntimeError('Synthetic scheduling failure')))
    result=client.post(path+'/answer',json={'turn_id':view['current_turn']['id'],'submission_id':str(uuid4()),'text':'I built the API','mode':'text'})
    assert result.status_code==200 and result.json()['current_turn']
    assert result.json()['history'][0]['answer']=='I built the API'


def test_later_chunks_receive_earlier_hypothetical_qualifications(monkeypatch):
    answer='This is only a proposed future experiment. '+('I would evaluate alternative models carefully. '*150)
    seen=[]
    async def provider(schema,instructions,data,validate,**kwargs):
        seen.append(data)
        ids=list(data['source_lines'])
        value={'summary':'Proposed future comparison, not completed work.',
            'facts':[{'scope':'future experiment','statement':'Would compare alternative models, not completed work.','kind':'hypothetical','evidence_ids':[ids[0]]}],
            'question_parts':[],'useful_next_angles':[]}
        return validate(schema.model_validate(value)),None,[]
    monkeypatch.setattr(memory,'structured',provider)
    asyncio.run(memory.extract_chunks(answer,qdict(1,'validation')))
    assert len(seen)>1 and seen[0]['earlier_part_context']['qualifications']==[]
    assert all(any(f['kind']=='hypothetical' for f in d['earlier_part_context']['qualifications']) for d in seen[1:])
    assert all(set(f['evidence_ids'])<=set(source_lines(answer)) for d in seen for f in d['earlier_part_context']['qualifications'])


def test_typed_answer_assesses_language_and_repetition_without_audio(monkeypatch):
    answer='basically '*5+'I explained my contribution clearly.'
    turn={'id':'typed','status':'answered','answer':answer,'mode':'text','raw_transcript':None,
        'delivery_metrics':{'pauses':[{'id':'stale','duration_seconds':30,'aligned':True}]}}
    async def provider(schema,instructions,data,validate,**kwargs):
        assert data['aligned_internal_pauses']==[] and data['answer_mode']=='text'
        assert data['expression_observations']['eligible_expressions']['basically']==5
        value=comm.CommunicationRating(score=4,grammar='Clear grammar.',sentence_structure='Coherent sentences.',
            fillers='Repeated redundant basically.',pause_checks=[],repetitive_expressions=['basically'],unfinished_pause_ids=[],
            pause_reasoning='No audio for typed input.',deduction_examples=[])
        return validate(value),None,[]
    monkeypatch.setattr(comm,'structured',provider)
    result=asyncio.run(comm.assess_communication(turn))
    assert result['score']==3.92 and result['delivery']['filler_deduction_points']==2
    assert result['delivery']['pause_deduction_points']==0
    assert result['delivery']['pause_measurement_status']=='not_applicable'


def test_valid_memory_summary_has_bounded_format_tolerance_without_truncation():
    answer='I implemented validation.'
    value=update_for(answer)
    value['summary']='A supported contribution and its qualifications. '*10
    saved=validate_update(MemoryUpdate.model_validate(value),answer)
    assert len(saved.summary)>320 and saved.summary==value['summary']
    assert MemoryUpdate.model_validate({**value,'summary':'x'*601}).summary=='x'*601
    with pytest.raises(ValueError):MemoryUpdate.model_validate({**value,'summary':''})


def test_model_validation_diagnostics_preserve_schema_paths_without_source_text(monkeypatch):
    invalid={**update_for('I implemented validation.'),'summary':''}
    async def respond(*args,**kwargs):
        return httpx.Response(400,json={'error':{'code':'json_validate_failed','failed_generation':json.dumps(invalid)}})
    settings=SimpleNamespace(groq_api_key=SecretStr('synthetic-content'),groq_communication_api_key=None,groq_model='test',groq_communication_model=None)
    monkeypatch.setattr(llm,'get_settings',lambda:settings)
    with patch('app.llm.httpx.AsyncClient') as factory:
        factory.return_value.__aenter__.return_value.post=AsyncMock(side_effect=respond)
        with pytest.raises(llm.ModelValidationError) as caught:
            asyncio.run(llm.structured(MemoryUpdate,'Extract memory',{},lambda v:v,purpose='interview',max_tokens=500))
    assert caught.value.diagnostics['schema']=='MemoryUpdate'
    assert caught.value.diagnostics['fields']==[{'path':['summary'],'type':'string_too_short'}]
    assert 'xxxx' not in json.dumps(caught.value.diagnostics)


def test_long_supported_memory_objectives_and_citations_are_not_format_errors():
    answer=' '.join('Supported statement number '+str(i)+'.' for i in range(8))
    ids=list(source_lines(answer))
    value=update_for(answer)
    value['question_parts']=[{'objective':'Explain preprocessing decisions, alternatives and validation evidence. '*4,'status':'answered','evidence_ids':ids}]
    value['facts'][0]['statement']='Supported explanation. '*20
    value['facts'][0]['evidence_ids']=ids
    saved=validate_update(MemoryUpdate.model_validate(value),answer)
    assert len(saved.question_parts[0].objective)>140 and len(saved.facts[0].evidence_ids)>3
    with pytest.raises(ValueError):validate_update(MemoryUpdate.model_validate({**value,'facts':[{**value['facts'][0],'evidence_ids':['S999']}]}),answer)
