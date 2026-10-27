"""Fixed-budget retrieval windows over immutable, source-linked answer memory."""
from copy import deepcopy
import re
import unicodedata
from .interview_budget import estimate_tokens,excerpt,request_estimate,InputBudgetError

VERSION='fixed-window-v1'

def normal(value):
    return ' '.join(unicodedata.normalize('NFKC',str(value)).casefold().split())

def terms(value):
    return set(re.findall(r'[a-z0-9+#]{3,}',normal(value)))

def unique_facts(records):
    result={}
    for row in records:
        key=(normal(row.get('scope','')),row.get('kind'),normal(row.get('statement','')))
        if key not in result:result[key]={**deepcopy(row),'refs':[]}
        refs=row.get('refs') or [row.get('ref')]
        result[key]['refs']=list(dict.fromkeys(result[key]['refs']+[r for r in refs if r]))
    return list(result.values())

def select_memory(memory,budget,query=''):
    """Selection is repeatable from originals, never a summary of the last summary."""
    candidates=unique_facts(memory.get('boundaries',[])+memory.get('relevant_claims',[]))
    rows=memory.get('answers',[]);explicit_terms=terms(query);qterms=set(explicit_terms)
    if rows:qterms|=terms(rows[-1].get('summary',''))
    def rank(row):
        overlap=len(qterms & terms(str(row)))
        recent=max((i for i,r in enumerate(rows) if r.get('ref') in row.get('refs',[row.get('ref')])),default=-1)
        return len(explicit_terms & terms(str(row))),overlap,recent
    output={'version':VERSION,'total_answers':len(rows),'latest':None,'limits':[],'claims':[],
        'topic_ledger':[],'evidence':[],
        'retrieval_note':'Selected evidence only; omitted details remain unknown. Full owned answer records remain stored by reference. Limits override gaps and proposed follow-ups; hypothetical work is not completed experience.'}
    def add(field,value,cap=None):
        trial=deepcopy(output)
        if field=='latest':trial[field]=value
        else:trial[field].append(value)
        if estimate_tokens(trial)<=budget and (cap is None or estimate_tokens(trial[field])<=cap):
            output.clear();output.update(trial);return True
        return False
    if rows:
        r=rows[-1]
        add('latest',{'ref':r['ref'],'summary':excerpt(r.get('summary',r.get('objective','')),240),
            'assessment':r.get('assessment',r.get('status')),
            'strength':excerpt(' '.join(r.get('strengths',[])),110),'gap':excerpt(' '.join(r.get('gaps',[])),110)})
    limits=[r for r in candidates if r.get('kind') in ('uncertainty','no_experience','declined','hypothetical','contradiction','unavailable','contradicted')]
    facts=[r for r in candidates if r not in limits]
    def fact(row):return {'refs':row['refs'][-4:],'scope':excerpt(row.get('scope',''),70),'kind':row.get('kind'),'statement':excerpt(row.get('statement',''),240),**({'evidence_ids':row['evidence_ids'][:3]} if 'evidence_ids' in row else {})}
    # Fixed category allocations prevent one verbose topic consuming every slot.
    def limit_rank(row):
        explicit,overlap,recent=rank(row)
        if row.get('kind') in ('no_experience','declined'):
            # Stable earlier denials must not be displaced by many recent
            # missing-detail observations extracted under the same broad kind.
            return 3,explicit,-recent
        return (2 if row.get('kind') in ('unavailable','contradicted','contradiction') else 1),explicit,overlap
    selected_scopes=set()
    for r in sorted(limits,key=limit_rank,reverse=True):
        projected=fact(r);scope_key=(normal(r.get('scope','')),r.get('kind'))
        if scope_key in selected_scopes:continue
        if r.get('kind') in ('no_experience','declined'):
            global_limits=[v for v in output['limits'] if v['kind'] in ('no_experience','declined')]
            if estimate_tokens(global_limits+[projected])>int(budget*.2):continue
        if add('limits',projected,int(budget*.42)):selected_scopes.add(scope_key)
    for r in sorted(facts,key=rank,reverse=True):add('claims',fact(r),int(budget*.22))
    ledger={}
    for r in rows:
        key=normal(r.get('topic',r.get('objective','unknown')))
        entry=ledger.setdefault(key,{'topic':excerpt(r.get('topic',r.get('objective','unknown')),70),'refs':[],'states':[],'objectives':[]})
        entry['refs'].append(r['ref'])
        entry['objectives']+=list(dict.fromkeys(excerpt(p.get('objective',''),90) for p in r.get('question_parts',[])))
        entry['states']+=list(dict.fromkeys(p.get('status','unknown') for p in r.get('question_parts',[])))
    for r in reversed(list(ledger.values())):
        r['refs']=r['refs'][-4:];r['states']=list(dict.fromkeys(r['states']));r['objectives']=list(dict.fromkeys(r['objectives']))[-2:]
        add('topic_ledger',r,int(budget*.18))
    for r in sorted(rows,key=lambda r:(len(qterms & terms(str(r))),rows.index(r)),reverse=True):
        add('evidence',{'ref':r['ref'],'summary':excerpt(r.get('summary',r.get('objective','')),180),
            'strength':excerpt(' '.join(r.get('strengths',[])),90),'gap':excerpt(' '.join(r.get('gaps',[])),90)},int(budget*.2))
    output['selection']={'available_facts':len(candidates),'selected_facts':len(output['limits'])+len(output['claims']),'available_topics':len(ledger)}
    # Metadata is optional; never allow accounting itself to overflow the window.
    if estimate_tokens(output)>budget:output.pop('selection')
    return output

def pack_request(original,system,schema,max_tokens,budget,extra_messages=()):
    """Measure every addition against the COMPLETE wire request plus output reserve."""
    safety=160;ceiling=budget-safety
    data={k:deepcopy(original[k]) for k in ('level','difficulty','topic_hint','permitted_action','remaining_turns','followup_chain_cap','saved_question','source_lines','complete_answer_memory','answer_processing') if k in original}
    base=request_estimate(system,schema,data,max_tokens,extra_messages)
    if base>ceiling:raise InputBudgetError('Required current-answer evidence exceeds request capacity; chunk processing is required.',estimated_total_tokens=base,token_budget=budget)
    query=str(original.get('saved_question',{}).get('question_text',''))+' '+str(original.get('topic_hint') or '')
    available=ceiling-base
    memory_budget=min(1450,max(200,int(available*.55)))
    selected=select_memory(original.get('session_memory',{}),memory_budget,query)
    def add(key,value):
        trial={**data,key:value}
        if request_estimate(system,schema,trial,max_tokens,extra_messages)<=ceiling:data[key]=value;return True
        return False
    add('session_memory',selected)
    coverage=original.get('competency_coverage',{})
    add('competency_coverage',{k:v for k,v in coverage.items() if k in ('assessed_dimensions','unassessed_dimensions','priority_dimensions','reserve_for_unassessed','remaining_interview_questions')})
    add('role_title',original.get('role_title',{}))
    context_terms=terms(query+' '+str(selected.get('latest','')))
    def relevance(value):return len(context_terms & terms(value))
    # Keep stage examples lowest priority; their size never displaces answer evidence.
    requirements=sorted(original.get('role_requirements',[]),key=relevance,reverse=True)
    for row in requirements:
        add('role_requirements',data.get('role_requirements',[])+[{k:(excerpt(v,160) if isinstance(v,str) else v) for k,v in row.items() if k in ('key','label','origin','importance','category')}])
    inventory=original.get('asked_question_inventory',[])
    for row in reversed(inventory[-4:]):
        add('asked_question_inventory',[{'ref':row.get('ref'),'level':row.get('level'),'question':excerpt(row.get('question',''),130)}]+data.get('asked_question_inventory',[]))
    candidates=[(key,row) for key,rows in original.get('candidate',{}).items() for row in rows]
    for key,row in sorted(candidates,key=lambda p:relevance(p[1]),reverse=True):
        profile=deepcopy(data.get('candidate',{}));profile.setdefault(key,[]).append({k:excerpt(str(v),180) for k,v in row.items() if k in ('value','origin','excerpt')})
        add('candidate',profile)
    for key in ('routing_feedback','job_fit_gaps','priority_topics','complete_interview_trails','calibration_examples'):
        if key in original:add(key,deepcopy(original[key]))
    total=request_estimate(system,schema,data,max_tokens,extra_messages)
    return data,{'context_mode':6,'memory_window':VERSION,'estimated_total_tokens':total,'token_budget':budget,'output_reservation':max_tokens,
        'memory_tokens':estimate_tokens(data.get('session_memory',{})),'safety_tokens':safety,'input_characters':len(str(data))}
