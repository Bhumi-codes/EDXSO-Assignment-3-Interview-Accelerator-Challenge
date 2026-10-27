from uuid import uuid4
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import select
from test_foundation import fixture
from app.main import app
from app.database import get_db
from app.models import InterviewSession,InterviewTurn,TurnEvaluation
from app import interview_service as service
from app import interview_routes
from app.controller import permitted_action,filler_count,validate_question
from app.interview_schemas import Question
from app.llm import AnalysisUnavailable

def qdict(number,topic):
    return {'question_text':f'What was your personal contribution in example {number}?',
        'topic_key':topic,'difficulty':1,'target_competencies':['role_fit','communication'],
        'rubric':{'adequate_criteria':['Specific ownership and evidence'],'useful_evidence':['A concrete example'],'misconceptions':['Team work alone establishes ownership']}}
def evaluation():
    return {'assessment_label':'Adequate','competency_scores':[{'competency':'role_fit','score':3}],
        'reasoning':'Synthetic assessment','answer_evidence':['I built the API'],'strengths':['Ownership'],
        'improvements':['Add measurement'],'ideal_direction':'Explain tradeoffs','recommended_action':'deepen','action_reason':'Explore reasoning'}

@pytest.fixture
def interview(fixture,monkeypatch):
    client,owner,other,session_id=fixture
    # Isolate existing lifecycle tests from optional report-provider work.
    from app import report_routes
    monkeypatch.setattr(interview_routes,'queue_report',lambda *args:False)
    monkeypatch.setattr(report_routes,'queue_report',lambda *args:False)
    db=next(app.dependency_overrides[get_db]())
    row=db.get(InterviewSession,session_id);row.status='ready';db.commit();db.close()
    async def gen(context,topic,difficulty,action,previous):
        return {**qdict(len(previous)+1,topic or 'personal contribution'),'difficulty':difficulty},[]
    async def assess(*args,**kwargs):
        return evaluation(),[]
    monkeypatch.setattr(service,'generate_question',AsyncMock(side_effect=gen))
    monkeypatch.setattr(service,'evaluate_answer',AsyncMock(side_effect=assess))
    # Independent language calls are exercised explicitly in dedicated tests.
    from app import communication_jobs,answer_memory
    monkeypatch.setattr(communication_jobs,'assess_communication',AsyncMock(side_effect=AnalysisUnavailable('Synthetic language quota')))
    async def memories(records):
        return {r['ref']:{'summary':'Saved answer: '+r['answer'][:280],'facts':[], 'question_parts':[], 'useful_next_angles':[]} for r in records},[]
    monkeypatch.setattr(service,'extract_batch',AsyncMock(side_effect=memories))
    async def chunk_memories(answer,question,**kwargs):
        return [{'summary':'Saved answer: '+answer[:280],'facts':[],'question_parts':[],'useful_next_angles':[]}],[]
    async def merge_memories(updates,*args):return updates[0],[]
    monkeypatch.setattr(service,'extract_chunks',AsyncMock(side_effect=chunk_memories))
    monkeypatch.setattr(service,'merge_updates',AsyncMock(side_effect=merge_memories))
    return fixture

def test_controller_all_level_budgets_and_chains():
    for level,budget,cap in [(1,4,1),(2,4,1),(3,7,2)]:
        assert permitted_action(level,budget,0,0,'deepen','Detailed answer')=='level_complete'
        assert permitted_action(level,1,cap,0,'deepen','Detailed answer')=='new_topic'
        assert permitted_action(level,budget-1,0,1,'deepen','Detailed answer')=='new_topic'
        assert permitted_action(level,1,0,0,'deepen','Detailed answer')=='deepen'

def test_fillers_and_duplicate_questions():
    assert filler_count(None) is None
    assert filler_count('Um, I used SQL. Uh, like a join. erm.')==3
    assert filler_count('Unlike other options, I liked it.')==0
    q=Question.model_validate(qdict(1,'ownership'))
    with pytest.raises(ValueError):
        validate_question(q,'ownership',1,[q.question_text])

def test_idempotent_start_accepted_answer_and_no_coaching_leak(interview):
    client,_,_,session_id=interview;path=f'/api/sessions/{session_id}/interview'
    first=client.post(path+'/start').json()
    assert client.post(path+'/start').json()['current_turn']['id']==first['current_turn']['id']
    assert service.generate_question.await_count==1
    body={'turn_id':first['current_turn']['id'],'submission_id':str(uuid4()),'text':'I built the API','mode':'text'}
    accepted=client.post(path+'/answer',json=body)
    assert accepted.status_code==200
    repeated=client.post(path+'/answer',json=body)
    assert repeated.status_code==200 and repeated.json()['turns_used']==2
    assert service.evaluate_answer.await_count==1
    assert 'competency_scores' not in accepted.text and 'ideal_direction' not in accepted.text
    replaced=client.post(path+'/answer',json={**body,'submission_id':str(uuid4()),'text':'Replacement'})
    assert replaced.status_code==409

def test_screening_budget_skip_and_chain_caps(interview):
    client,_,_,session_id=interview;path=f'/api/sessions/{session_id}/interview'
    view=client.post(path+'/start').json()
    for _ in range(4):
        response=client.post(path+'/answer',json={'turn_id':view['current_turn']['id'],'submission_id':str(uuid4()),'text':'I built the API','mode':'text'})
        assert response.status_code==200
        view=response.json()
    assert view['level']==2 and view['turns_used']==1 and view['current_turn'] is not None
    assert view['levels'][0]['status']=='completed' and len(view['levels'][0]['history'])==4
    assert client.post(path+'/advance').json()['turns_used']==1
    db=next(app.dependency_overrides[get_db]())
    turns=service.all_turns(db,session_id)
    assert turns[1].parent_turn_id==turns[0].id and turns[2].parent_turn_id is None
    db.close()

def test_failed_generation_preserves_evaluation_and_retries_without_rescoring(interview,monkeypatch):
    client,_,_,session_id=interview;path=f'/api/sessions/{session_id}/interview'
    view=client.post(path+'/start').json()
    real=service.generate_question
    monkeypatch.setattr(service,'generate_question',AsyncMock(side_effect=AnalysisUnavailable('Synthetic quota')))
    result=client.post(path+'/answer',json={'turn_id':view['current_turn']['id'],'submission_id':str(uuid4()),'text':'I built the API','mode':'text'})
    assert result.status_code==503
    saved=client.get(path).json()
    assert saved['history'][0]['answer']=='I built the API' and saved['current_turn'] is None
    monkeypatch.setattr(service,'generate_question',real)
    assert client.post(path+'/advance').status_code==200
    assert service.evaluate_answer.await_count==1

def test_transcription_is_saved_separately_and_voice_cannot_be_spoofed(interview,monkeypatch):
    client,_,_,session_id=interview;path=f'/api/sessions/{session_id}/interview'
    view=client.post(path+'/start').json();turn=view['current_turn']['id']
    body={'turn_id':turn,'submission_id':str(uuid4()),'text':'I built the API','mode':'voice'}
    assert client.post(path+'/answer',json=body).status_code==422
    monkeypatch.setattr(interview_routes,'transcribe_audio',AsyncMock(return_value={'text':'Um I built the API','duration':4.0}))
    assert client.post(path+'/turns/'+turn+'/transcribe?format=wav',content=b'RIFFsynthetic').status_code==200
    answer=client.post(path+'/answer',json=body)
    assert answer.status_code==200
    history=answer.json()['history'][0]
    assert history['raw_transcript']=='Um I built the API'
    assert history['answer']=='I built the API' and history['filler_count']==1
    assert history['response_duration_seconds']==4.0

def test_other_account_cannot_access_interview_or_transcribe(interview):
    from app.auth import current_identity,Identity
    client,_,other,session_id=interview;path=f'/api/sessions/{session_id}/interview'
    turn=client.post(path+'/start').json()['current_turn']['id']
    app.dependency_overrides[current_identity]=lambda:Identity(user_id=other,display_name='Other synthetic')
    assert client.get(path).status_code==404
    assert client.post(path+'/start').status_code==404
    assert client.post(path+'/turns/'+turn+'/transcribe?format=wav',content=b'RIFFsynthetic').status_code==404

def test_failed_transcription_does_not_consume_another_turn(interview,monkeypatch):
    client,_,_,session_id=interview;path=f'/api/sessions/{session_id}/interview'
    turn=client.post(path+'/start').json()['current_turn']['id']
    monkeypatch.setattr(interview_routes,'transcribe_audio',AsyncMock(side_effect=AnalysisUnavailable('No speech detected')))
    assert client.post(path+'/turns/'+turn+'/transcribe?format=wav',content=b'RIFFsynthetic').status_code==503
    current=client.get(path).json()
    assert current['turns_used']==1 and current['current_turn']['id']==turn and not current['history']

def test_real_speech_adapter_rejects_silence_and_bad_formats():
    import asyncio,httpx
    from types import SimpleNamespace
    from pydantic import SecretStr
    from unittest.mock import patch
    from app.speech import transcribe_audio
    settings=SimpleNamespace(groq_api_key=SecretStr('synthetic'),groq_stt_model='synthetic')
    with patch('app.speech.get_settings',return_value=settings):
        with pytest.raises(AnalysisUnavailable,match='Unsupported'):
            asyncio.run(transcribe_audio(b'<html>','answer.webm'))
        with patch('app.speech.httpx.AsyncClient') as factory:
            factory.return_value.__aenter__.return_value.post=AsyncMock(return_value=httpx.Response(200,json={'text':'hallucinated speech','duration':2,'segments':[{'no_speech_prob':.99}]}))
            with pytest.raises(AnalysisUnavailable,match='No clear speech'):
                asyncio.run(transcribe_audio(b'RIFFsynthetic','answer.wav'))

def test_evaluation_scores_only_saved_targets_and_cites_actual_answer(monkeypatch):
    import asyncio
    import app.interview_ai as ai
    from app.interview_schemas import Evaluation
    q=qdict(1,'ownership')
    async def provider(schema,instructions,data,validate,**kwargs):
        value=schema.model_validate({**evaluation(),'memory_update':{'summary':'Personal API contribution described.','facts':[],'question_parts':[],'useful_next_angles':[]}})
        value.answer_evidence=[]
        checked=validate(value)
        return checked,None,[]
    monkeypatch.setattr(ai,'structured',provider)
    value,_=asyncio.run(ai.evaluate_answer({},q,'I built the API'))
    assert value['answer_evidence']==['I built the API']
    async def invalid_provider(schema,instructions,data,validate,**kwargs):
        value=schema.model_validate({**evaluation(),'memory_update':{'summary':'Personal API contribution described.','facts':[],'question_parts':[],'useful_next_angles':[]}})
        value.competency_scores[0].competency='technical_knowledge'
        validate(value)
    monkeypatch.setattr(ai,'structured',invalid_provider)
    with pytest.raises(ValueError):
        asyncio.run(ai.evaluate_answer({},q,'I built the API'))

def test_process_local_token_pacing_is_bounded():
    import asyncio
    from unittest.mock import patch
    from app import llm
    previous=dict(llm.rate_state)
    llm.rate_state.update(limit=8000,remaining=0,observed=0)
    try:
        with patch('app.llm.time.monotonic',return_value=0),patch('app.llm.asyncio.sleep',new_callable=AsyncMock) as sleep:
            asyncio.run(llm.reserve_tokens({'messages':[],'max_completion_tokens':1800}))
            assert sleep.await_count==1 and 0<sleep.await_args.args[0]<=45
    finally:
        llm.rate_state.clear();llm.rate_state.update(previous)



def test_validation_error_identifies_next_question_without_blame_on_documents(interview,monkeypatch):
    from app.llm import ModelValidationError
    client,_,_,session_id=interview;path=f'/api/sessions/{session_id}/interview'
    view=client.post(path+'/start').json()
    monkeypatch.setattr(service,'generate_question',AsyncMock(side_effect=ModelValidationError('ScopedQuestion')))
    result=client.post(path+'/answer',json={'turn_id':view['current_turn']['id'],'submission_id':str(uuid4()),'text':'I built the API','mode':'text'})
    assert result.status_code==503
    assert 'next question' in result.json()['detail']
    assert 'documents' not in result.json()['detail']
    assert client.get(path).json()['history'][0]['answer']=='I built the API'


def test_selected_evidence_is_not_overwritten_by_full_answer(monkeypatch):
    import asyncio
    import app.interview_ai as ai
    from app.interview_schemas import Evaluation
    async def provider(schema,instructions,data,validate,**kwargs):
        value=schema.model_validate({**evaluation(),'memory_update':{'summary':'Personal API contribution described.','facts':[],'question_parts':[],'useful_next_angles':[]}})
        value.answer_evidence=['S001']
        return validate(value),None,[]
    monkeypatch.setattr(ai,'structured',provider)
    result,_=asyncio.run(ai.evaluate_answer({},qdict(1,'ownership'),'I built the API. I tested it.'))
    assert result['answer_evidence']==['I built the API.']


@pytest.mark.parametrize('question',[
 'In the character classification project, which normalization method did you apply and why was it needed?',
 'Which image normalization method did you apply and what was the reason for choosing it?',
])
def test_one_method_with_linked_rationale_is_not_a_validation_failure(question):
    q=Question.model_validate(qdict(1,'preprocessing'))
    q.question_text=question
    validate_question(q,'preprocessing',1,[])


def test_words_do_not_override_the_models_routing_recommendation():
    answer="I don't know why that assumption was made; I can explain the implementation."
    assert permitted_action(1,1,0,0,'deepen',answer)=='deepen'

def test_model_can_choose_a_new_objective_without_repeating_a_name(monkeypatch):
    import asyncio
    import app.interview_ai as ai
    captured={}
    async def provider(schema,instructions,data,validate,**kwargs):
        captured.update(data)
        value=qdict(2,'generalization')
        value['question_text']='What do the training and held-out results suggest about generalization?'
        parsed=schema.model_validate(value)
        return validate(parsed),None,[]
    monkeypatch.setattr(ai,'structured',provider)
    context={'conversation_history':[{'question':'Explain image normalization.','answer':'I cannot recall the formula, but can discuss generalization: 86% training and 83% validation/test.'}]}
    question,_=asyncio.run(ai.generate_question(context,None,1,'new_topic',[]))
    assert question['topic_key']=='generalization'
    assert captured['conversation_history']==context['conversation_history']
    assert captured['topic_hint'] is None

def test_current_answer_need_not_repeat_previous_project_or_focus(monkeypatch):
    import asyncio
    import app.interview_ai as ai
    from app.interview_schemas import Evaluation
    async def provider(schema,instructions,data,validate,**kwargs):
        value=schema.model_validate({**evaluation(),'memory_update':{'summary':'Personal API contribution described.','facts':[],'question_parts':[],'useful_next_angles':[]}})
        value.answer_evidence=['S001']
        return validate(value),None,[]
    monkeypatch.setattr(ai,'structured',provider)
    context={'conversation_history':[{'question':'Explain your classification project.','answer':'I normalized the images.'}]}
    result,_=asyncio.run(ai.evaluate_answer(context,qdict(2,'generalization'),'Validation and test accuracy were both 83%.'))
    assert result['answer_evidence']==['Validation and test accuracy were both 83%.']

def test_short_session_provides_all_saved_history_without_cross_session_leak(interview):
    from app.models import InterviewLevel
    client,owner,other,session_id=interview
    db=next(app.dependency_overrides[get_db]())
    item=db.get(InterviewSession,session_id)
    item.candidate_profile={'skills':[
        {'value':'Python','origin':'explicit','excerpt':'Python'},
        {'value':'Language processing','origin':'inferred','excerpt':'Calls an LLM API'},
        {'value':'Unspecified provenance','excerpt':''}]}
    level=InterviewLevel(session_id=session_id,level_number=1,question_budget=4);db.add(level);db.flush()
    for number in range(1,5):
        db.add(InterviewTurn(level_id=level.id,turn_number=number,question_text=f'Question {number}',question_spec={'topic_key':f'topic-{number}'},status='answered',submitted_answer_text=f'Unique answer {number}: '+('details '*80)))
    unrelated=InterviewSession(user_id=other,title='Other synthetic session')
    db.add(unrelated);db.flush()
    other_level=InterviewLevel(session_id=unrelated.id,level_number=1,question_budget=4);db.add(other_level);db.flush()
    db.add(InterviewTurn(level_id=other_level.id,turn_number=1,question_text='Private other question',question_spec={'topic_key':'other'},status='answered',submitted_answer_text='PRIVATE OTHER ANSWER'))
    db.commit()
    _,turns=service.level_and_turns(db,session_id)
    context=service.build_context(db,item,turns,None)
    assert context['conversation_history_scope']=='source-linked cumulative answer memory; no raw previous answers sent'
    assert [(skill['value'],skill['origin']) for skill in context['candidate']['skills']]==[
        ('Python','explicit'),('Language processing','inferred'),('Unspecified provenance','unspecified')]
    assert len(context['session_memory']['answers'])==4
    assert all(t['status']=='memory_pending' for t in context['session_memory']['answers'])
    assert 'conversation_history' not in context
    assert turns[0].submitted_answer_text.startswith('Unique answer 1')
    assert 'PRIVATE OTHER ANSWER' not in str(context)
    db.close()

def test_long_session_context_indexes_all_owned_answers_without_replaying_raw_text(interview):
    from app.models import InterviewLevel
    client,owner,other,session_id=interview
    db=next(app.dependency_overrides[get_db]())
    item=db.get(InterviewSession,session_id)
    level=InterviewLevel(session_id=session_id,level_number=1,question_budget=4);db.add(level);db.flush()
    for number in range(1,5):
        body=('baseline claim ' if number in (1,4) else 'different subject ')*300
        db.add(InterviewTurn(level_id=level.id,turn_number=number,question_text=f'Question {number}',question_spec={'topic_key':str(number)},status='answered',submitted_answer_text=body))
    db.commit();_,turns=service.level_and_turns(db,session_id)
    context=service.build_context(db,item,turns,None)
    assert len(context['session_memory']['answers'])==4
    assert len(context['asked_question_inventory'])==4
    assert 'history_index' not in context and 'relevant_older_history' not in context
    assert turns[0].submitted_answer_text.startswith('baseline claim')
    db.close()


@pytest.mark.parametrize('words,valid',[(2,False),(3,True),(60,True),(61,False)])
def test_question_word_boundaries_replace_character_cap(words,valid):
    q=Question.model_validate({**qdict(1,'ownership'),'question_text':' '.join(['implementation']*words)})
    if valid:
        validate_question(q,'ownership',1,[])
    else:
        with pytest.raises(ValueError,match='3 to 60 words'):
            validate_question(q,'ownership',1,[])

def test_long_answer_is_accepted_and_saved_without_truncation(interview):
    client,_,_,session_id=interview
    path=f'/api/sessions/{session_id}/interview'
    turn=client.post(path+'/start').json()['current_turn']
    text='I implemented and tested the validation pipeline. '*180
    assert len(text)>6000
    response=client.post(path+'/answer',json={'turn_id':turn['id'],'submission_id':str(uuid4()),'text':text,'mode':'text'})
    assert response.status_code==200
    assert response.json()['history'][0]['answer']==text.strip()
    payload=service.generate_question.call_args.args[0]
    assert payload['routing_feedback']['reason']=='Explore reasoning'

def test_long_transcript_and_duration_are_not_answer_caps():
    import asyncio
    import httpx
    from unittest.mock import patch
    from types import SimpleNamespace
    from pydantic import SecretStr
    from app.speech import transcribe_audio
    settings=SimpleNamespace(groq_api_key=SecretStr('synthetic'),groq_stt_model='synthetic')
    text='A complete spoken answer. '*300
    with patch('app.speech.get_settings',return_value=settings),patch('app.speech.httpx.AsyncClient') as factory:
        factory.return_value.__aenter__.return_value.post=AsyncMock(return_value=httpx.Response(200,json={'text':text,'duration':240,'segments':[]}))
        result=asyncio.run(transcribe_audio(b'OggSsynthetic','answer.ogg'))
    assert result['text']==text.strip()
    assert result['duration']==240

def test_complete_teaching_trails_are_in_actual_generation_payload(monkeypatch):
    import asyncio
    import app.interview_ai as ai
    captured={}
    async def provider(schema,instructions,data,validate,**kwargs):
        captured.update(data)
        return validate(schema.model_validate(qdict(1,'ownership'))),None,[]
    monkeypatch.setattr(ai,'structured',provider)
    asyncio.run(ai.generate_question({'conversation_history':[]},None,1,'new_topic',[]))
    assert 'calibration_examples' not in captured  # only the Screening trail teaches generation
    trails=captured['complete_interview_trails']
    assert len(trails)==1
    for trail in trails:
        assert len(trail['turns'])==5
        assert all(pair['level']==1 for pair in trail['turns'])
        assert all(pair.get('q') and pair.get('a') and pair.get('next') for pair in trail['turns'])
        assert all(3<=len(pair['q'].split())<=60 for pair in trail['turns'])
        assert len({pair['q'] for pair in trail['turns']})==len(trail['turns'])


def test_screening_evaluation_does_not_receive_higher_level_examples(monkeypatch):
    import asyncio
    import app.interview_ai as ai
    from app.interview_schemas import Evaluation
    captured={}
    async def provider(schema,instructions,data,validate,**kwargs):
        captured.update(data)
        value=schema.model_validate({**evaluation(),'memory_update':{'summary':'Personal API contribution described.','facts':[],'question_parts':[],'useful_next_angles':[]}})
        value.answer_evidence=['S001']
        return validate(value),None,[]
    monkeypatch.setattr(ai,'structured',provider)
    asyncio.run(ai.evaluate_answer({},qdict(1,'ownership'),'I built the API'))
    assert captured['calibration_examples']
    assert all(example['level']==1 for example in captured['calibration_examples'])
