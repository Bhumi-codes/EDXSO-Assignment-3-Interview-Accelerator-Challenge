"""Bound inference context; never alter saved text or truncate the accepted answer."""
from copy import deepcopy
import json
import re

class InputBudgetError(ValueError):
    def __init__(self,message,*,estimated_total_tokens=None,token_budget=None):
        super().__init__(message)
        self.estimated_total_tokens=estimated_total_tokens
        self.token_budget=token_budget

def estimate_tokens(value):
    # Conservative size estimate, not a model-specific tokenizer.
    return (len(json.dumps(value,ensure_ascii=False,separators=(',',':')).encode('utf-8'))+2)//3

def request_estimate(system,schema,data,max_tokens,extra_messages=()):
    return estimate_tokens({'messages':[{'role':'system','content':system},
        {'role':'user','content':json.dumps(data,ensure_ascii=False,separators=(',',':'))},*extra_messages],
        'response_format':{'type':'json_schema','json_schema':{'schema':schema}},
        'max_completion_tokens':max_tokens})+max_tokens

def excerpt(text,size):
    if len(text)<=size:return text
    marker=' [excerpt; full text saved] '
    available=max(0,size-len(marker))
    if not available:return text[:size]
    head=(available*2+2)//3;tail=available-head
    return text[:head]+marker+(text[-tail:] if tail else '')

def bound_interview_context(original,system,schema,max_tokens,budget,extra_messages=(),*,minimum_mode=0):
    if original.get('session_memory',{}).get('window_version')=='fixed-window-v1':
        from .memory_window import pack_request
        return pack_request(original,system,schema,max_tokens,budget,extra_messages)
    data=deepcopy(original)
    # Runtime generation telemetry and routing metadata are not assessment criteria.
    if 'saved_question' in data:
        question=data['saved_question']
        data['saved_question']={key:question[key] for key in
            ('question_text','topic_key','difficulty','target_competencies','rubric') if key in question}
    # A completed level cannot take a follow-up; the following level's generator
    # gets its own complete inventory. Do not spend the final evaluation budget on
    # routing-only question wording.
    if 'source_lines' in data and data.get('remaining_turns')==0:
        data.pop('asked_question_inventory',None)
    history=deepcopy(data.get('conversation_history',[]))
    # Generation needs the latest answer in full. Evaluation already supplies its
    # entire current answer separately as source_lines, which is never compacted.
    protected=history[-1:] if history and not data.get('current_answer_supplied_separately',False) and 'source_lines' not in data else []
    older=history[:-1] if protected else history
    subject=str(data.get('saved_question',{}).get('question_text',''))+' '+str(protected)
    terms=set(re.findall(r'[a-z0-9+#]{4,}',subject.lower()))
    def relevance(turn):
        return len(terms & set(re.findall(r'[a-z0-9+#]{4,}',str(turn).lower())))
    prior=deepcopy(data.get('relevant_older_history',[]))
    index=deepcopy(data.get('history_index',[]))
    # Link compact answer memory to existing question references. This preserves
    # explicit experience/recall boundaries without keyword-based routing rules.
    answer_memory={turn.get('question'):turn.get('answer',turn.get('answer_excerpt',''))
        for turn in [*index,*prior,*history] if turn.get('question')}
    removed=[]
    for mode in range(6):
        if mode:
            data.pop('jd_text',None) # structured, evidence-labelled requirements remain
            data.pop('level_purpose',None) # The level purpose is already in system instructions.
            if schema.get('title')=='ReportNarrative':
                # Report inputs are selected excerpts, not the protected current
                # answer used during grading. Retain every cited ID and denial.
                for key,record in data.get('source_lines',{}).items():
                    if not isinstance(record,dict):continue
                    for field,limit in (('question',180 if mode<3 else 120),('accepted_answer_excerpt',240 if mode<3 else 150),('assessment_reason',160 if mode<3 else 90)):
                        if field in record:record[field]=excerpt(str(original['source_lines'][key].get(field,'')),limit)
                    record['assessment_improvement']=[excerpt(str(v),120 if mode<3 else 75) for v in original['source_lines'][key].get('assessment_improvement',[])[:2 if mode<3 else 1]]
                    record.pop('saved_criteria',None)
                for record in data.get('objectives',[]):
                    for field,limit in (('why',200 if mode<3 else 100),('practice_task',100),('success_check',80)):
                        if field in record:record[field]=excerpt(str(record[field]),limit)

            if 'session_memory' in data:
                memory=data['session_memory'];memory.pop('policy',None)
                if mode>=3 and memory.get('latest_update'):
                    # The newest summary/statuses already occur in answers; facts
                    # occur in boundaries/relevant_claims. Avoid replaying the same
                    # extraction with full citations, angles and prose a second time.
                    memory['latest_update']={'summary':excerpt(memory['latest_update'].get('summary',''),130)}
                for entry in memory.get('answers',[]):
                    if 'summary' in entry:entry['summary']=excerpt(entry['summary'],200 if mode<3 else 130 if mode<5 else 90)
                    for field in ('strengths','gaps'):
                        entry[field]=[excerpt(str(v),100 if mode<5 else 65) for v in entry.get(field,[])[:1]]
                    for part in entry.get('question_parts',[]):part['objective']=excerpt(part['objective'],100 if mode<5 else 65)
                for fact in memory.get('boundaries',[]):
                    fact['statement']=excerpt(fact['statement'],160 if mode<3 else 110)
                    fact['scope']=excerpt(fact['scope'],70)
                memory['relevant_claims']=memory.get('relevant_claims',[])[:8 if mode<3 else 5 if mode<5 else 3]
                if mode>=5:
                    for entry in memory.get('answers',[]):
                        entry.pop('question_parts',None) # Unavailable/contradicted objectives also live in boundaries; other parts are summarised above.
            if 'competency_coverage' in data:
                data['competency_coverage'].pop('policy',None) # Same rules remain in system policy.
                # Preserve every missing/priority key and reservation flag; compact
                # repeated references before sacrificing conversation context.
                original_dimensions={d['key']:d for d in original['competency_coverage'].get('dimensions',[])}
                for dimension in data['competency_coverage']['dimensions']:
                    original_dimension=original_dimensions.get(dimension['key'],dimension)
                    for field in ('assessed_question_refs','attempted_question_refs'):
                        refs=original_dimension.get(field,[])
                        dimension[field]=refs[-2:]
                    if mode>=3:
                        dimension.pop('label',None)
                        dimension.pop('attempted_question_refs',None)
                        dimension['attempted_question_count']=len(original_dimension.get('attempted_question_refs',[]))

            if 'jd_text' not in removed:removed.append('duplicate_raw_jd')
            data['conversation_history_scope']='bounded recent exchanges, older index and selected excerpts; full text remains saved'
            recent_count={1:3,2:2,3:1,4:0,5:0}[mode]
            size={1:700,2:400,3:220,4:120,5:100}[mode]
            recent=older[-recent_count:] if recent_count else []
            omitted=older[:-recent_count] if recent_count else older
            data['conversation_history']=[{**turn,'answer':excerpt(turn.get('answer',''),size)} for turn in recent]+protected
            indexed=[{'turn_id':turn.get('turn_id'),'level':turn.get('level'),'topic_key':turn.get('topic_key'),
                'question':excerpt(turn.get('question',''),120 if mode<3 else 65),
                'answer_excerpt':excerpt(turn.get('answer',''),160 if mode<3 else 65)} for turn in omitted]
            data['history_index']=indexed+[
                {**turn,'question':excerpt(turn.get('question',''),120 if mode<3 else 65),
                 'answer_excerpt':excerpt(turn.get('answer_excerpt',''),160 if mode<3 else 65)}
                for turn in index]
            candidates=omitted+prior
            chosen=sorted(candidates,key=relevance,reverse=True)[:(2 if mode==1 else 1 if mode<4 else 0)]
            data['relevant_older_history']=[{**turn,'answer':excerpt(turn.get('answer',''),500 if mode==1 else 250)} for turn in chosen]
            data['earlier_findings']=[{key:excerpt(value,100) if isinstance(value,str) and key=='reason' else value
                for key,value in finding.items()} for finding in original.get('earlier_findings',[])[-(4 if mode==1 else 2):]]
            for key,findings in data.get('candidate',{}).items():
                data['candidate'][key]=[{**finding,'value':excerpt(finding.get('value',''),220 if mode<3 else 120),
                    'excerpt':excerpt(finding.get('excerpt',''),120 if key=='projects' else 80 if mode<3 else 40)} for finding in findings[:(6 if mode<3 else 3)]]
            data['job_fit_gaps']=[{key:excerpt(value,120) if isinstance(value,str) else value for key,value in gap.items()}
                for gap in original.get('job_fit_gaps',[])[:(4 if mode<3 else 2)]]
            if mode>=2:
                for key in ('complete_interview_trails','calibration_examples'):
                    if key in data:
                        data.pop(key)
                        if key not in removed:removed.append(key)
            if mode>=3:
                requirements=[{key:value for key,value in r.items() if key!='id'} for r in original.get('role_requirements',[])]
                data['role_requirements']=sorted(requirements,key=lambda item:relevance(item),reverse=True)[:8]
            if mode>=4:
                # Preserve question objectives and project scope before optional broad profiles.
                for key,findings in data.get('candidate',{}).items():
                    data['candidate'][key]=findings[:3 if key=='projects' else 1]
                data['role_requirements']=data.get('role_requirements',[])[:4]
                data['job_fit_gaps']=data.get('job_fit_gaps',[])[:1]
                # The protected question inventory already identifies past objectives.
                # Drop the redundant ID-only answer index rather than the question wording.
                data['history_index']=[] if data.get('asked_question_inventory') else [
                    {key:value for key,value in row.items() if key in ('turn_id','level','topic_key')}
                    for row in data['history_index']]
                data['earlier_findings']=[]
                if data.get('asked_question_inventory'):
                    data['asked_question_inventory']=[{**entry,**({'answer_excerpt':excerpt(answer_memory[entry['question']],110 if mode==4 else 80)} if entry.get('question') in answer_memory else {})}
                        for entry in original['asked_question_inventory']]
            if mode==5:
                # Final bounded fallback retains every prior objective and its
                # answer memory, plus the entire latest answer and saved rubric.
                for entry in data.get('asked_question_inventory',[]):
                    entry['question']=excerpt(entry.get('question',''),140)
                for key in ('history_index','relevant_older_history','earlier_findings','job_fit_gaps'):
                    data.pop(key,None)
                data['role_requirements']=data.get('role_requirements',[])[:3]
                data['competency_coverage']={key:value for key,value in data.get('competency_coverage',{}).items()
                    if key in ('assessed_dimensions','unassessed_dimensions','priority_dimensions','reserve_for_unassessed','remaining_interview_questions')}
                if not data['competency_coverage']:data.pop('competency_coverage',None)
            data['context_budget']={'mode':mode,'omitted_optional_fields':removed,
                'history_text_shortened':True,'current_answer_preserved':True,
                'note':'Omitted text is unknown; do not claim to have read it. Ask a necessary clarification.'}
        if not any(key in original for key in ('conversation_history','history_index','relevant_older_history','earlier_findings')):
            for key in ('conversation_history','history_index','relevant_older_history','earlier_findings'):
                data.pop(key,None)
            if 'session_memory' in original:data['conversation_history_scope']='source-linked cumulative memory; original answers remain saved'
        if mode>=5 and 'session_memory' in data:
            data['context_budget']={'mode':mode,'note':'Omitted text is unknown; original answers remain saved.'}
            data.pop('conversation_history_scope',None)
            data.pop('current_answer_supplied_separately',None)
        estimate=request_estimate(system,schema,data,max_tokens,extra_messages)
        if estimate<=budget and mode>=minimum_mode:
            return data,{'context_mode':mode,'estimated_total_tokens':estimate,'token_budget':budget,
                         'input_characters':len(json.dumps(data,ensure_ascii=False,separators=(',',':')))}
    raise InputBudgetError('Current answer and required assessment data do not fit the available provider budget.',estimated_total_tokens=estimate,token_budget=budget)
