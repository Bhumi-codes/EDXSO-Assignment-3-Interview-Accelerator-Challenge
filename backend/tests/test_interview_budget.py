"""Context budgeting preserves accepted data while bounding whole provider requests."""
from copy import deepcopy
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
import httpx
import pytest
from pydantic import SecretStr
from app.interview_budget import bound_interview_context,request_estimate,InputBudgetError
from app.interview_schemas import Question
from app.llm import structured,RequestSizeError
from test_interview import qdict,interview
from test_foundation import fixture

def large_context():
    return {'level':3,'current_answer_supplied_separately':True,'jd_text':'raw JD '*800,
        'conversation_history':[{'turn_id':str(i),'level':1 if i<4 else 2 if i<8 else 3,
            'topic_key':'evaluation','question':'What evidence informed that decision?',
            'answer':('earlier evidence and limitations '*130)+str(i)} for i in range(14)],
        'earlier_findings':[{'turn_id':str(i),'label':'Adequate','reason':'historical reasoning '*40} for i in range(14)],
        'source_lines':{'S001':'Full current answer with meaningful facts.'},
        'saved_question':{**qdict(15,'evaluation'),'generation_metadata':[{'unneeded':'telemetry '*800}]},
        'role_requirements':[{'key':'evaluation','label':'Evaluation','origin':'explicit'}],
        'candidate':{'skills':[{'value':'Python','origin':'explicit','excerpt':'Python'}]}}

def test_large_history_budget_preserves_current_answer_rubric_and_origin():
    original=large_context();snapshot=deepcopy(original)
    data,info=bound_interview_context(original,'Evaluate current answer',Question.model_json_schema(),1800,7000)
    assert info['context_mode']>0
    assert request_estimate('Evaluate current answer',Question.model_json_schema(),data,1800)<=7000
    assert data['source_lines']==original['source_lines']
    assert data['saved_question']['rubric']==original['saved_question']['rubric']
    assert 'generation_metadata' not in data['saved_question']
    assert data['candidate']['skills'][0]['origin']=='explicit'
    assert original==snapshot
    assert data['history_index'] and data['context_budget']['current_answer_preserved']

def test_generation_preserves_full_latest_answer_even_during_history_compaction():
    data=large_context();data.pop('source_lines');data.pop('saved_question')
    data['current_answer_supplied_separately']=False
    data['conversation_history'][-1]['answer']='Latest answer and a recall boundary. '*80
    latest=deepcopy(data['conversation_history'][-1])
    fitted,_=bound_interview_context(data,'Generate next question',Question.model_json_schema(),1800,7000)
    assert fitted['conversation_history'][-1]==latest

def test_short_context_is_not_unnecessarily_shortened():
    original={'level':1,'conversation_history':[{'question':'What did you do?','answer':'I built validation.'}]}
    result,info=bound_interview_context(original,'Brief instructions',Question.model_json_schema(),1000,7000)
    assert result==original and info['context_mode']==0

def test_answer_too_large_is_not_silently_truncated():
    original={'source_lines':{'S001':'A long complete accepted answer. '*3000},'saved_question':qdict(1,'ownership')}
    with pytest.raises(InputBudgetError):
        bound_interview_context(original,'Evaluate',Question.model_json_schema(),1800,7000)
    assert len(original['source_lines']['S001'])>6000

def test_http_size_rejection_gets_one_smaller_retry():
    from app import llm
    original={'source_lines':{'S001':'The accepted answer.'},'current_answer_supplied_separately':True,
        'saved_question':qdict(1,'ownership'),
        'conversation_history':[{'turn_id':str(i),'question':'Explain that decision.','answer':'earlier context '*70} for i in range(6)]}
    success=httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(qdict(2,'ownership'))}}],'usage':{}})
    saved=dict(llm.rate_state);llm.rate_state.clear()
    try:
        with patch('app.llm.get_settings',return_value=SimpleNamespace(groq_api_key=SecretStr('synthetic'),groq_model='synthetic')),patch('app.llm.httpx.AsyncClient') as factory:
            requests=[]
            async def respond(*args,**kwargs):
                requests.append(deepcopy(kwargs['json']))
                return httpx.Response(413,json={'error':{'message':'Request too large'}}) if len(requests)==1 else success
            post=AsyncMock(side_effect=respond)
            factory.return_value.__aenter__.return_value.post=post
            _,_,telemetry=asyncio.run(structured(Question,'Generate one question',original,lambda v:v,purpose='interview',max_tokens=1800))
            assert post.await_count==2
            first,second=requests
            assert len(json.dumps(second))<len(json.dumps(first))
            first_data=json.loads(first['messages'][1]['content'])
            second_data=json.loads(second['messages'][1]['content'])
            assert first_data['source_lines']==second_data['source_lines']==original['source_lines']
            assert first_data['saved_question']['rubric']==second_data['saved_question']['rubric']
            assert any(item.get('request_size_retry') for item in telemetry)
    finally:
        llm.rate_state.clear();llm.rate_state.update(saved)

def test_interview_size_error_never_instructs_document_edits():
    from app import llm
    saved=dict(llm.rate_state);llm.rate_state.clear()
    try:
        with patch('app.llm.get_settings',return_value=SimpleNamespace(groq_api_key=SecretStr('synthetic'),groq_model='synthetic')),patch('app.llm.httpx.AsyncClient') as factory:
            factory.return_value.__aenter__.return_value.post=AsyncMock(return_value=httpx.Response(413))
            with pytest.raises(RequestSizeError) as failure:
                asyncio.run(structured(Question,'Question',large_context(),lambda v:v,purpose='interview',max_tokens=1800))
            assert 'Shorten' not in str(failure.value) and 'accepted answer is saved' in str(failure.value)
            assert factory.return_value.__aenter__.return_value.post.await_count<=2
    finally:
        llm.rate_state.clear();llm.rate_state.update(saved)

def test_size_error_keeps_accepted_answer_and_records_specific_stage(interview,monkeypatch):
    from app import interview_service as service
    from uuid import uuid4
    client,_,_,session_id=interview;path=f'/api/sessions/{session_id}/interview'
    view=client.post(path+'/start').json()
    monkeypatch.setattr(service,'evaluate_answer',AsyncMock(side_effect=RequestSizeError('Your accepted answer is saved. Provider input capacity exceeded.')))
    response=client.post(path+'/answer',json={'turn_id':view['current_turn']['id'],'submission_id':str(uuid4()),'text':'An accepted answer','mode':'text'})
    assert response.status_code==503 and 'documents' not in response.json()['detail']
    assert client.get(path).json()['history'][0]['answer']=='An accepted answer'


def deep_generation_context(count=9):
    from app.interview_coverage import competency_coverage
    from app.calibration import trails_for_level
    history=[]
    for i in range(count):
        history.append({'turn_id':str(i),'level':1 if i<4 else 2 if i<8 else 3,
            'topic_key':'topic-'+str(i),'status':'answered',
            'question':f'In example {i}, describe a concrete framework implementation, the architecture, training process and evaluation decisions you made, explaining which choices were your own and why they suited that project rather than another approach.',
            'answer':'I have not used PyTorch in a project. I used TensorFlow and Keras and can discuss that experience.' if i==5 else 'I worked on input validation, compared evaluation results and documented limitations. '+('The team shared implementation tasks and reviewed results together. '*6)})
    history[-1]['answer']='I have not built a model with that framework. My experience is with a different library; I can explain that work and its limitations.'
    turns=[{'id':t['turn_id'],'level':t['level'],'number':i+1,'status':'answered','target_competencies':['role_fit']} for i,t in enumerate(history)]
    grades={t['id']:{'assessment_label':'Adequate','competency_scores':[{'competency':'role_fit','score':3}]} for t in turns}
    return {'level':3,'level_purpose':'Challenging Deep Dive','remaining_turns':7-max(0,count-8),'permitted_action':'new_topic','difficulty':3,'topic_hint':None,
        'conversation_history':history,'current_answer_supplied_separately':False,
        'asked_question_inventory':[{'ref':f'L{t["level"]}Q{i+1}','level':t['level'],'question':t['question']} for i,t in enumerate(history)],
        'candidate':{'projects':[{'value':name+' project with model evaluation and a documented contribution.','origin':'explicit','excerpt':('The project includes preprocessing, regularization and evaluation. '*5)+'Tools: '+tools} for name,tools in [('Tabular predictor','Python and scikit-learn'),('Document service','Python and Pydantic'),('Image classifier','TensorFlow and Keras')]],
            'skills':[{'value':'Python and Java','origin':'explicit','excerpt':'Python, Java and TensorFlow'}]},
        'role_requirements':[{'id':str(i),'key':'requirement-'+str(i),'label':'Relevant classification, evaluation, backend integration and collaboration requirement '+str(i),'origin':'explicit','importance':'required','category':'skill'} for i in range(14)],
        'earlier_findings':[{'turn_id':str(i),'label':'Adequate','reason':'The candidate explained the contribution but acknowledged a limited comparison. '*3} for i in range(count)],
        'competency_coverage':competency_coverage(turns,grades,{},3),
        'complete_interview_trails':trails_for_level(3),'jd_text':'Detailed job description. '*80}


@pytest.mark.parametrize('count',range(9,15))
def test_full_deep_dive_policy_fits_with_coverage_and_preserves_prior_answer_memory(count):
    from app.interview_prompts import question_prompt
    from app.llm import INTERVIEW_SYSTEM_PREFIX
    from pydantic import create_model
    from typing import Literal
    original=deep_generation_context(count);before=deepcopy(original)
    schema=create_model('ScopedQuestion',__base__=Question,difficulty=(Literal[3],...))
    fitted,info=bound_interview_context(original,INTERVIEW_SYSTEM_PREFIX+question_prompt(3),schema.model_json_schema(),1200,7000)
    assert info['estimated_total_tokens']<=7000
    assert fitted['conversation_history'][-1]==original['conversation_history'][-1]
    assert len(fitted['asked_question_inventory'])==count
    assert fitted['competency_coverage']['unassessed_dimensions']==original['competency_coverage']['unassessed_dimensions']
    # The earlier framework denial must remain available at the strongest compaction.
    memories=[entry.get('answer_excerpt','') for entry in fitted.get('asked_question_inventory',[])]+[entry.get('answer_excerpt','') for entry in fitted.get('history_index',[])]+[entry.get('answer','') for entry in fitted.get('conversation_history',[])]
    assert any('not used PyTorch' in answer for answer in memories)
    assert len(fitted['candidate']['projects'])==3
    assert 'TensorFlow' in fitted['candidate']['projects'][2]['excerpt']
    assert original==before


def test_interview_schema_repair_does_not_replay_large_rejected_output():
    from app.llm import INTERVIEW_SYSTEM_PREFIX
    from app.interview_prompts import question_prompt
    from app import llm
    original=deep_generation_context()
    result_question={**qdict(10,'new-topic'),'difficulty':3}
    saved=dict(llm.rate_state);llm.rate_state.clear()
    requests=[]
    async def respond(*args,**kwargs):
        requests.append(deepcopy(kwargs['json']))
        if len(requests)==1:return httpx.Response(400,json={'error':{'code':'json_validate_failed','failed_generation':json.dumps({'invalid':'x'*5000})}})
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(result_question)}}],'usage':{}})
    try:
        with patch('app.llm.get_settings',return_value=SimpleNamespace(groq_api_key=SecretStr('synthetic'),groq_model='synthetic')),patch('app.llm.httpx.AsyncClient') as factory:
            factory.return_value.__aenter__.return_value.post=AsyncMock(side_effect=respond)
            result,_,_=asyncio.run(structured(Question,question_prompt(3),original,lambda q:q,purpose='interview',max_tokens=1200))
        assert result.question_text==result_question['question_text'] and len(requests)==2
        assert not any(message['role']=='assistant' for message in requests[1]['messages'])
        restored=json.loads(requests[1]['messages'][1]['content'])
        assert restored['conversation_history'][-1]==original['conversation_history'][-1]
    finally:
        llm.rate_state.clear();llm.rate_state.update(saved)


@pytest.mark.parametrize('size',[20,40,80,140])
def test_excerpt_limit_includes_the_shortening_marker(size):
    from app.interview_budget import excerpt
    text='A source beginning. '+('middle '*100)+' A source ending.'
    result=excerpt(text,size)
    assert len(result)<=size
    assert text==('A source beginning. '+('middle '*100)+' A source ending.')


def test_provider_size_retry_uses_compact_context_when_guessed_target_cannot_fit():
    from app import llm
    from app.interview_prompts import question_prompt
    original=deep_generation_context(14)
    system=llm.INTERVIEW_SYSTEM_PREFIX+question_prompt(3)
    _,first=bound_interview_context(original,system,Question.model_json_schema(),1200,7000)
    _,minimum=bound_interview_context(original,system,Question.model_json_schema(),1200,7000,minimum_mode=5)
    assert minimum['estimated_total_tokens']>int(first['estimated_total_tokens']*.85)
    success={**qdict(15,'new-objective'),'difficulty':3}
    saved=dict(llm.rate_state);llm.rate_state.clear();requests=[]
    async def respond(*args,**kwargs):
        requests.append(deepcopy(kwargs['json']))
        if len(requests)==1:return httpx.Response(413,json={'error':{'message':'Request too large'}})
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(success)}}],'usage':{}})
    try:
        with patch('app.llm.get_settings',return_value=SimpleNamespace(groq_api_key=SecretStr('synthetic'),groq_model='synthetic')),patch('app.llm.httpx.AsyncClient') as factory:
            factory.return_value.__aenter__.return_value.post=AsyncMock(side_effect=respond)
            result,_,calls=asyncio.run(structured(Question,question_prompt(3),original,lambda q:q,purpose='interview',max_tokens=1200))
        assert result.topic_key=='new-objective' and len(requests)==2
        assert len(json.dumps(requests[1]))<len(json.dumps(requests[0]))
        second=json.loads(requests[1]['messages'][1]['content'])
        assert second['conversation_history'][-1]==original['conversation_history'][-1]
        assert len(second['asked_question_inventory'])==14
        assert any(call.get('request_size_retry') and call['context_mode']==5 for call in calls)
    finally:
        llm.rate_state.clear();llm.rate_state.update(saved)


def test_preflight_failure_records_only_numeric_budget_diagnostics():
    from app import llm
    original={'source_lines':{'S001':'Private complete accepted answer. '*3000},'saved_question':qdict(1,'ownership')}
    saved=dict(llm.rate_state);llm.rate_state.clear()
    try:
        with patch('app.llm.get_settings',return_value=SimpleNamespace(groq_api_key=SecretStr('synthetic'),groq_model='synthetic')),patch('app.llm.httpx.AsyncClient') as factory:
            with pytest.raises(RequestSizeError) as failure:
                asyncio.run(structured(Question,'Evaluate',original,lambda q:q,purpose='interview',max_tokens=1800))
        diagnostics=failure.value.diagnostics
        assert diagnostics['stage']=='preflight' and diagnostics['estimated_total_tokens']>diagnostics['token_budget']
        assert diagnostics['output_reservation']==1800 and diagnostics['schema']=='Question'
        assert 'Private complete accepted answer' not in json.dumps(diagnostics)
        assert not factory.called
    finally:
        llm.rate_state.clear();llm.rate_state.update(saved)
