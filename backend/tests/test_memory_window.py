import asyncio,json
from copy import deepcopy
from unittest.mock import AsyncMock
import pytest
from app.memory_window import select_memory,unique_facts,VERSION
from app.interview_budget import bound_interview_context,request_estimate,estimate_tokens,InputBudgetError
from app.interview_prompts import question_prompt
from app.interview_schemas import Question
from app.llm import INTERVIEW_SYSTEM_PREFIX
from app import memory_archive as archive


def memory(count):
    return {'window_version':VERSION,'answers':[{'ref':f'L3Q{i}','topic':f'objective {i%12}',
        'summary':f'The candidate explained supported objective {i} and its limitations. '*5,
        'assessment':'Partial','strengths':['A supported contribution.'],'gaps':['Validation was not established.'],
        'question_parts':[{'objective':'Explain the rationale and evidence.','status':'partial'}]} for i in range(count)],
        'boundaries':[{'ref':f'L3Q{i}','scope':f'project {i%12}','kind':'hypothetical' if i%2 else 'uncertainty',
            'statement':f'Proposed work for objective {i}; no measured result is claimed. '*3} for i in range(count)],
        'relevant_claims':[{'ref':f'L3Q{i}','scope':f'project {i%12}','kind':'knowledge','statement':f'Explains the evaluation principle for objective {i}. '*4} for i in range(count)],
        'latest_update':{'summary':'Duplicated latest extraction. '*100,'facts':[{'statement':'Duplicate fact.'}]*20}}


@pytest.mark.parametrize('count',[15,60,180])
@pytest.mark.parametrize('budget',[5000,7000])
def test_complete_request_is_bounded_as_interview_history_grows(count,budget):
    context={'level':3,'difficulty':3,'permitted_action':'new_topic','session_memory':memory(count),
        'role_title':{'value':'AI Engineer'},'role_requirements':[{'key':str(i),'label':'Classification evaluation and deployment','origin':'explicit'} for i in range(20)],
        'candidate':{'projects':[{'value':f'Project {i}','origin':'explicit','excerpt':'TensorFlow and evaluation. '*10} for i in range(20)]},
        'asked_question_inventory':[{'ref':f'L3Q{i}','question':f'Explain objective {i} and its evidence.'} for i in range(count)],
        'complete_interview_trails':['Example teaching conversation. '*200]}
    before=deepcopy(context);system=INTERVIEW_SYSTEM_PREFIX+question_prompt(3);schema=Question.model_json_schema()
    packed,info=bound_interview_context(context,system,schema,1000,budget)
    assert request_estimate(system,schema,packed,1000)<=budget-160
    assert info['memory_tokens']<=1450 and packed['session_memory']['total_answers']==count
    assert packed['session_memory']['latest']['ref']==f'L3Q{count-1}'
    assert 'latest_update' not in packed['session_memory'] and context==before
    assert 'complete_interview_trails' not in packed or request_estimate(system,schema,packed,1000)<=budget-160


def test_relevant_old_denial_and_latest_hypothesis_survive_selection():
    value=memory(60)
    value['boundaries'].append({'ref':'L1Q1','scope':'PyTorch','kind':'no_experience','statement':'Has never used PyTorch.'})
    value['boundaries'].append({'ref':'L3Q59','scope':'PyTorch','kind':'hypothetical','statement':'The proposed PyTorch experiment is hypothetical, not completed work.'})
    packed=select_memory(value,1450,'PyTorch')
    assert any(r['kind']=='no_experience' and 'L1Q1' in r['refs'] for r in packed['limits'])
    assert any(r['kind']=='hypothetical' and 'L3Q59' in r['refs'] for r in packed['limits'])


def test_python_dedup_keeps_conflicts_scopes_and_hypotheticals_distinct():
    rows=[{'ref':'L1Q1','scope':'project A','kind':'experience','statement':'Used TensorFlow.'},
        {'ref':'L2Q1','scope':'project A','kind':'experience','statement':'Used TensorFlow.'},
        {'ref':'L2Q2','scope':'project B','kind':'experience','statement':'Used TensorFlow.'},
        {'ref':'L2Q3','scope':'project A','kind':'hypothetical','statement':'Used TensorFlow.'},
        {'ref':'L2Q4','scope':'project A','kind':'no_experience','statement':'Did not use TensorFlow.'}]
    result=unique_facts(rows)
    assert len(result)==4 and result[0]['refs']==['L1Q1','L2Q1']


def test_current_answer_is_not_shortened_to_fit_memory():
    source={'S001':'Current answer evidence. '*80}
    data={'level':2,'session_memory':memory(60),'saved_question':{'question_text':'Explain validation.','rubric':{'adequate_criteria':['Evidence']}},'source_lines':source}
    packed,info=bound_interview_context(data,'Assess the current answer.',Question.model_json_schema(),1000,7000)
    assert packed['source_lines']==source and info['estimated_total_tokens']<=7000
    with pytest.raises(InputBudgetError):bound_interview_context({**data,'source_lines':{'S001':'irreducible '*20000}},'Assess.',Question.model_json_schema(),1000,7000)


def test_repair_messages_are_included_in_total_budget():
    data={'level':3,'session_memory':memory(60)}
    extra=[{'role':'user','content':'Correct the allowed schema fields. '*20}]
    packed,info=bound_interview_context(data,'Generate a question.',Question.model_json_schema(),1000,5000,extra)
    assert request_estimate('Generate a question.',Question.model_json_schema(),packed,1000,extra)==info['estimated_total_tokens']<=4840


def test_consolidation_is_occasional_cached_and_nonblocking(monkeypatch):
    calls=[]
    async def provider(schema,instructions,data,validate,**kwargs):
        calls.append(data)
        return validate(schema.model_validate({'groups':[]})),None,[]
    monkeypatch.setattr(archive,'structured',provider)
    initial=memory(14)
    result,changed=asyncio.run(archive.consolidate(initial))
    assert changed and 1<=len(calls)<=2 and all(len(c['facts'])<=12 for c in calls)
    count=len(calls)
    again,changed=asyncio.run(archive.consolidate(initial,result))
    assert not changed and len(calls)==count and again==result
    async def unavailable(*args,**kwargs):raise RuntimeError('Synthetic quota')
    monkeypatch.setattr(archive,'structured',unavailable)
    result,changed=asyncio.run(archive.consolidate(initial))
    assert changed and result['status']=='deferred'
    assert asyncio.run(archive.consolidate(initial,result))[1] is False
    assert select_memory(initial,1200)['latest'] is not None


def test_small_memory_needs_no_extra_llm_call(monkeypatch):
    provider=AsyncMock();monkeypatch.setattr(archive,'structured',provider)
    assert asyncio.run(archive.consolidate(memory(3)))==({},False)
    provider.assert_not_awaited()


def test_semantic_grouping_preserves_all_source_refs_and_never_rewrites_claims():
    rows=[{'ref':'L1Q1','refs':['L1Q1'],'scope':'A','kind':'uncertainty','statement':'Cannot recall layers.'},
        {'ref':'L2Q1','refs':['L2Q1'],'scope':'A','kind':'uncertainty','statement':'The layer sizes cannot be recalled.'}]
    before=deepcopy(rows)
    result=archive.apply_archive(rows,{'groups':[[archive.fact_id(r) for r in rows]]})
    assert len(result)==1 and set(result[0]['refs'])=={'L1Q1','L2Q1'} and result[0]['statement'] in [r['statement'] for r in rows]
    assert rows==before


def test_explicit_experience_denial_survives_unrelated_latest_topic():
    value=memory(180)
    value['boundaries'].append({'ref':'L1Q1','scope':'framework experience','kind':'no_experience','statement':'Has no hands-on PyTorch experience.'})
    selected=select_memory(value,1450,'scikit-learn regression validation')
    assert any(r['kind']=='no_experience' and 'L1Q1' in r['refs'] for r in selected['limits'])


def test_many_recent_missing_detail_records_do_not_displace_old_experience_limit():
    value=memory(15)
    value['boundaries']=[{'ref':'L3Q14','scope':scope,'kind':'no_experience','statement':'No actual metric or code detail was provided. '*3} for scope in ('metrics','code','knowledge') for _ in range(3)]
    value['boundaries'].append({'ref':'L1Q1','scope':'PyTorch','kind':'no_experience','statement':'Has never worked on a PyTorch project.'})
    selected=select_memory(value,1450,'')
    assert any('L1Q1' in r['refs'] for r in selected['limits'])
