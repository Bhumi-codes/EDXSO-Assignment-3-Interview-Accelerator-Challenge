import asyncio
from copy import deepcopy
from app.delivery import repetition_observations,delivery_adjustment
from app.pause_detection import internal_gaps,align_gaps,measure_pauses
from app import communication as comm

def voice(text='A clear answer',pauses=None):
    return {'id':'test','status':'answered','answer':text,'raw_transcript':text,'mode':'voice',
        'delivery_metrics':{'status':'measured','pauses':pauses or []}}

def gap(seconds,aligned=True):
    return {'id':'pause-1','duration_seconds':seconds,'aligned':aligned,'before':'I chose it because','after':'it suited the data'}

def test_four_occurrences_and_normal_fillers_do_not_deduct():
    for text in ['um uh erm basically','basically '*4]:
        assert delivery_adjustment(voice(text),[],[])['total_deduction_points']==0

def test_each_repeated_expression_costs_two_points_and_content_repetition_not_penalised():
    t=voice('basically '*5+'um '*7+'Python '*8);original=deepcopy(t)
    result=delivery_adjustment(t,[],[])
    assert result['filler_deduction_points']==4
    assert result['repetition']['repeated_words']['python']==8
    assert 'python' not in result['penalised_expressions']
    assert t==original

def test_ambiguous_like_requires_context_confirmation():
    t=voice('I like Python. I like SQL. I like models. I like testing. I like APIs.')
    assert delivery_adjustment(t,[],[])['filler_deduction_points']==0
    assert delivery_adjustment(t,['like'],[])['filler_deduction_points']==2

def test_strict_pause_thresholds_no_stacking_or_uncertain_penalties():
    for seconds,points in [(6,0),(6.01,2),(25,2),(25.01,5)]:
        assert delivery_adjustment(voice(pauses=[gap(seconds)]),[],['pause-1'])['pause_deduction_points']==points
    assert delivery_adjustment(voice(pauses=[gap(30)]),[],[])['pause_deduction_points']==0
    assert delivery_adjustment(voice(pauses=[gap(30,False)]),[],['pause-1'])['pause_deduction_points']==0
    t=voice(pauses=[gap(30)]);t['mode']='text'
    assert delivery_adjustment(t,[],['pause-1'])['pause_deduction_points']==0

def test_internal_gaps_exclude_start_and_end_and_require_reliable_word_alignment():
    gaps=internal_gaps([(4,7),(15,18),(45,48)])
    assert [p['duration_seconds'] for p in gaps]==[8,27]
    words=[{'start':6,'end':7,'word':'because'},{'start':15,'end':16,'word':'it'},
        {'start':17,'end':18,'word':'using'},{'start':45,'end':46,'word':'metrics'}]
    assert all(p['aligned'] for p in align_gaps(gaps,words))
    assert not any(p['aligned'] for p in align_gaps(gaps,[]))
    assert measure_pauses(b'not audio',[])['status']=='unavailable'

def test_language_and_delivery_scored_once_without_mutation(monkeypatch):
    async def provider(schema,instructions,data,validate,**kw):
        assert 'Do not deduct from this base score' in instructions
        value=schema(score=4,grammar='Clear grammar.',sentence_structure='Clear structure.',fillers='Basically repeats five times.',
            deduction_examples=[],unfinished_pause_ids=['pause-1'],pause_checks=[{'id':'pause-1','classification':'unfinished','reason':'The clause resumes.'}],pause_reasoning='The because-clause resumes after the gap.')
        return validate(value),None,[]
    monkeypatch.setattr(comm,'structured',provider)
    t=voice('basically '*5,pauses=[gap(26)]);before=deepcopy(t)
    rating=asyncio.run(comm.assess_communication(t))
    assert rating['base_language_score']==4 and rating['score']==3.72 # 100 - 2 - 5 = 93%
    assert t==before

def test_invented_pause_ids_or_unproven_expression_rejected(monkeypatch):
    import pytest
    async def provider(schema,instructions,data,validate,**kw):
        value=schema(score=4,grammar='Clear.',sentence_structure='Clear.',fillers='None.',deduction_examples=[],unfinished_pause_ids=['invented'])
        with pytest.raises(ValueError,match='aligned'):validate(value)
        value.unfinished_pause_ids=[];value.repetitive_expressions=['basically']
        with pytest.raises(ValueError,match='five'):validate(value)
        value.repetitive_expressions=[]
        return validate(value),None,[]
    monkeypatch.setattr(comm,'structured',provider)
    assert asyncio.run(comm.assess_communication(voice()))['score']==4

def test_legacy_ratings_preserved():
    t=voice();t.pop('delivery_metrics');rating={'version':'communication-language-v2','answer_digest':comm.answer_digest(t),'score':2}
    assert comm.current_ratings([t],{'test':rating})=={'test':rating}


def test_provider_schema_requires_every_delivery_field():
    schema=comm.CommunicationRating.model_json_schema()
    assert set(schema['required'])==set(schema['properties'])
    assert not any('default' in value for value in schema['properties'].values())


def test_saved_delivery_ratings_reweighted_without_mutating_history_or_calling_model():
    t=voice('basically '*5,pauses=[gap(26)])
    rating={'version':comm.VERSION,'answer_digest':comm.answer_digest(t),'score':3,
        'base_language_score':4,'delivery':{'penalised_expressions':{'basically':5},
        'confirmed_unfinished_pauses':[gap(26)]}}
    cache={'test':rating};original=deepcopy((t,cache))
    updated=comm.current_ratings([t],cache)['test']
    assert updated['score']==3.72
    assert updated['delivery']['filler_deduction_points']==2
    assert updated['delivery']['pause_deduction_points']==5
    assert (t,cache)==original
    assert delivery_adjustment(voice('basically '*12),[],[])['filler_deduction_points']==2
