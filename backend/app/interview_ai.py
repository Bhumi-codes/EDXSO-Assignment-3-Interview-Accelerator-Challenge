from typing import Literal
import re
from pydantic import create_model
from .llm import structured
from .interview_schemas import Question,Evaluation
from .controller import validate_question
from .fit import source_lines,excerpt_location
from .calibration import examples_for,trails_for_level
from .interview_prompts import question_prompt,LEVEL_PURPOSES
from .answer_memory import MemoryUpdate,validate_update,extract_chunks,merge_updates,source_chunks,MEMORY_POLICY

class ContentEvaluation(Evaluation):
    memory_update:MemoryUpdate

async def generate_question(context,topic,difficulty,action,previous):
    fields={'difficulty':(Literal[difficulty],...)}
    if topic is not None:fields['topic_key']=(Literal[topic],...)
    schema=create_model('ScopedQuestion',__base__=Question,**fields)
    result,_,metadata=await structured(schema,question_prompt(context.get('level',1)),
        {**context,'topic_hint':topic,'difficulty':difficulty,'permitted_action':action,
         'complete_interview_trails':trails_for_level(context.get('level',1))},
        lambda q:validate_question(q,topic,difficulty,previous),purpose='interview',max_tokens=1000)
    return result.model_dump(),metadata

async def evaluate_answer(context,question,answer,*,cache=None,progress=None):
    """LLM2: content assessment plus one memory update; never communication scoring."""
    targets=set(question['target_competencies'])-{'communication'}
    def validate(value):
        keys=[s.competency for s in value.competency_scores]
        if (value.assessment_label=='Unassessable' and keys) or (value.assessment_label!='Unassessable' and not keys) or len(set(keys))!=len(keys) or not set(keys)<=targets:
            raise ValueError('Score only unique saved content targets. Communication belongs exclusively to LLM1; Unassessable has no scores.')
        value.answer_evidence=[excerpt_location(e,answer)['excerpt'] for e in value.answer_evidence]
        if not value.answer_evidence:value.answer_evidence=[answer]
        if hasattr(value,'memory_update'):validate_update(value.memory_update,answer)
        return value
    compact={key:context[key] for key in ('level','session_memory','candidate','role_requirements') if key in context}
    terms=set(re.findall(r'[a-z0-9+#]{4,}',(question['question_text']+' '+question.get('topic_key','')).casefold()))
    def relevance(value):return len(terms & set(re.findall(r'[a-z0-9+#]{4,}',str(value).casefold())))
    if 'session_memory' in compact and compact['session_memory'].get('window_version')!='fixed-window-v1':
        m=compact['session_memory']
        compact['session_memory']={**m,'answers':sorted(m.get('answers',[]),key=relevance,reverse=True)[:1],
            'boundaries':sorted(m.get('boundaries',[]),key=relevance,reverse=True)[:6],
            'relevant_claims':sorted(m.get('relevant_claims',[]),key=relevance,reverse=True)[:2],'latest_update':None}
    if 'candidate' in compact:
        # Grading uses the saved question/rubric; only the most relevant resume
        # context is needed here. Question generation retains cumulative context.
        candidates=[(key,value) for key,values in compact['candidate'].items() for value in values]
        compact['candidate']={}
        for key,value in sorted(candidates,key=lambda pair:relevance(pair[1]),reverse=True)[:2]:
            compact['candidate'].setdefault(key,[]).append(value)
    compact['role_requirements']=sorted(compact.get('role_requirements',[]),key=relevance,reverse=True)[:4]
    spec={k:question[k] for k in ('question_text','topic_key','difficulty','target_competencies','rubric')}
    all_sources=source_lines(answer);metadata=[];combined=None
    if len(source_chunks(answer))>1:
        partial,calls=await extract_chunks(answer,spec,cache=cache,progress=progress);metadata.extend(calls)
        combined,calls=await merge_updates(partial,answer,spec);metadata.extend(calls)
        evidence_ids=list(dict.fromkeys(s for f in combined['facts'] for s in f['evidence_ids']))
        evidence_ids+=list(dict.fromkeys(s for p in combined['question_parts'] for s in p['evidence_ids'] if s not in evidence_ids))
        quotes={};size=0
        for key in evidence_ids:
            text=all_sources[key]
            if size+len(text)>1200:continue
            quotes[key]=text;size+=len(text)
        source_data={'complete_answer_memory':combined,'source_lines':quotes,'answer_processing':{'method':'all_chunks_then_consolidation','chunks':len(partial),'note':'Every chunk was examined against the same question. Consolidated claims retain original source IDs; quoted passages are a selected subset. Do not treat a local chunk omission as a whole-answer gap.'}}
    else:source_data={'source_lines':all_sources,'calibration_examples':examples_for('evaluation',level=context.get('level',1))}
    instructions=(
        'LLM2 evaluates CONTENT only against the saved rubric at this level: '+LEVEL_PURPOSES[context.get('level',1)]+'. '
        'Scores 0 no relevant demonstration, 1 major gaps, 2 partial, 3 adequate, 4 strong justified reasoning. '
        'Score only unique saved target competencies EXCEPT communication. LLM1 alone handles grammar, sentence structure, fillers and pauses. Never lower technical or confidence scores for delivery. '
        'Confidence is a supported position, personal contribution where applicable and consistency with earlier replies; honest uncertainty alone is not a weakness. Do not demand assertiveness, exact syntax or invented comparisons. '
        'Use Unassessable with no scores when an unsupported question premise prevents any fair assessment. If only some targets are assessable, score those only. An honest lack of relevant knowledge may establish a knowledge gap without lowering unrelated targets. '
        'Use the complete accepted answer or consolidated evidence from ALL its chunks. Cite current source IDs. Return specific reasons, strengths, improvements and ideal direction; do not invent results or penalise processing failures. Earlier statements retain their own references. '
        'Also return memory_update: extract the answer crux, facts and what each requested part actually established. '+MEMORY_POLICY+' '+' Rate saved rubric targets independently; weak technical reasoning does not establish weak ownership. Naming tools is insufficient where justification was requested. State evidence and missing explanations; no invented criteria, double penalties or penalising honest recall limits. Screening stays broad/easy; Competency leaves exhausted angles after one useful clarification; Deep Dive probes reasoning, scenarios or inconsistencies without repeating unavailable details, supplied facts or whole pipelines. A low score does not require another probe. Explain the next objective in action_reason.')
    schema=Evaluation if combined is not None else ContentEvaluation
    if combined is not None:instructions=instructions.replace('Also return memory_update: extract the answer crux, facts and what each requested part actually established. '+MEMORY_POLICY,'The complete_answer_memory was already extracted and validated from every answer chunk. Return only the content evaluation; do not re-extract memory.')
    result,_,calls=await structured(schema,instructions,
        {**compact,'saved_question':spec,**source_data},
        validate,purpose='interview',max_tokens=1400 if combined is not None else 1800)
    metadata.extend(calls)
    output=result.model_dump()
    if combined is not None:output['memory_update']=combined
    return output,metadata
