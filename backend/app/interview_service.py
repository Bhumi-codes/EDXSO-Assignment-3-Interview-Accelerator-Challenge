from copy import deepcopy
from datetime import datetime,timezone,timedelta
from uuid import uuid4,UUID
from fastapi import HTTPException
from sqlalchemy import select, null
from .models import InterviewSession,InterviewLevel,InterviewTurn,TurnEvaluation,SessionRequirement,RequirementMatch,InterviewReport
from .analysis_routes import owned
from .controller import BUDGETS,CHAIN_CAPS,permitted_action,filler_count,validate_question
from .interview_ai import generate_question,evaluate_answer
from .interview_schemas import Question
from .interview_coverage import competency_coverage
from .answer_memory import entry_for,store_update,memory_context,extract_batch,extract_chunks,merge_updates,source_chunks,digest
from .interview_budget import excerpt
from .communication import assess_communication,current_ratings,answer_digest
from .interview_prompts import LEVEL_NAMES,LEVEL_PURPOSES,PROMPT_VERSION
from .llm import AnalysisUnavailable,ModelValidationError,RequestSizeError

FINAL_STATUSES=('completed','ended_early')

def levels_for(db,session_id):
    return list(db.scalars(select(InterviewLevel).where(InterviewLevel.session_id==session_id).order_by(InterviewLevel.level_number)))

def all_turns(db,session_id):
    return list(db.scalars(select(InterviewTurn).join(InterviewLevel).where(InterviewLevel.session_id==session_id)
                          .order_by(InterviewLevel.level_number,InterviewTurn.turn_number)))

def level_and_turns(db,session_id):
    # Levels are created only on transition; unattempted placeholders exist only after finalisation.
    levels=levels_for(db,session_id)
    active=next((level for level in levels if level.status=='in_progress'),None)
    level=active or next((level for level in reversed(levels) if level.status!='not_attempted'),None)
    turns=list(db.scalars(select(InterviewTurn).where(InterviewTurn.level_id==level.id).order_by(InterviewTurn.turn_number))) if level else []
    return level,turns

def load_snapshot(db,session_id,include_report=False):
    """Short-lived read snapshot; discard before every provider await/write boundary."""
    return {'levels':levels_for(db,session_id),'turns':all_turns(db,session_id),
        'evaluations':list(db.scalars(select(TurnEvaluation).join(InterviewTurn).join(InterviewLevel).where(InterviewLevel.session_id==session_id))),
        'report':db.scalar(select(InterviewReport).where(InterviewReport.session_id==session_id)) if include_report else None}


def snapshot_level(snapshot):
    levels=snapshot['levels']
    active=next((l for l in levels if l.status=='in_progress'),None)
    return active or next((l for l in reversed(levels) if l.status!='not_attempted'),None)


def public_view(db,item):
    snapshot=load_snapshot(db,item.id)
    level=snapshot_level(snapshot);levels=snapshot['levels'];saved=snapshot['turns']
    turns=[t for t in saved if level and t.level_id==level.id]
    final=item.status in FINAL_STATUSES
    current=next((t for t in reversed(turns) if t.status=='asked'),None) if not final else None
    def history_row(t):
        return {'id':str(t.id),'question':t.question_text,'answer':t.submitted_answer_text,
            'raw_transcript':t.raw_transcript,'mode':t.answer_mode,'filler_count':t.filler_count,
            'response_duration_seconds':t.response_duration_seconds,
            'status':t.status,'number':t.turn_number,
            'level':next(l.level_number for l in levels if l.id==t.level_id)}
    histories=[history_row(t) for t in saved if t.status!='asked']
    number=level.level_number if level else 1
    evaluated_ids={e.turn_id for e in snapshot['evaluations']}
    phase=item.interview_state.get('phase','not_started')
    if phase=='screening_complete' and not final:
        phase='level_complete' # Legacy M3 attempts may continue into Competency.
    return {'session_id':str(item.id),'phase':item.status if final else phase,
        'status':item.status,'finalised':final,'level':number,'level_name':LEVEL_NAMES[number],
        'budget':BUDGETS[number],'turns_used':len(turns),'total_turns_used':len(saved),'total_budget':15,
        'processing':bool(item.interview_state.get('operation')),'error':item.interview_state.get('error'),
        'current_turn':{'id':str(current.id),'question_text':current.question_text,
            'raw_transcript':current.raw_transcript,'number':current.turn_number} if current else None,
        'history':histories,'levels':[
            {'number':n,'name':LEVEL_NAMES[n],'budget':BUDGETS[n],
             'status':next((l.status for l in levels if l.level_number==n),'not_started'),
             'history':[h for h in histories if h['level']==n]} for n in BUDGETS],
        'coverage':{'answered':sum(t.status=='answered' for t in saved),
            'skipped':sum(t.status=='skipped' for t in saved),
            'evaluated':len(evaluated_ids),
            'pending_evaluations':sum(t.status=='answered' and t.id not in evaluated_ids for t in saved)}}

def priority_topics(item,level=1):
    if level==1:
        return ['background_and_role_fit','motivation_and_goals']
    usable=[r for r in item.fit_summary.get('requirements',[]) if r['category'] not in ('eligibility','qualification')]
    usable.sort(key=lambda r:-r['weight'])
    return [r['key'] for r in usable[:2]] or ['personal contribution','role motivation']

def coverage_for(item,level):
    coverage=item.interview_state.get('level_coverage',{}).get(str(level))
    if coverage is not None:return coverage
    if level==1:
        return {key:item.interview_state.get(key,[]) for key in ('attempted_topics','assessed_topics')}
    return {'attempted_topics':[],'assessed_topics':[]}

def busy_operation(item):
    op=item.interview_state.get('operation')
    return bool(op and datetime.now(timezone.utc)-datetime.fromisoformat(op['started_at'])<timedelta(minutes=8))

def require_operation(item,token):
    if item.status!='in_progress' or item.interview_state.get('operation',{}).get('token')!=token:
        raise HTTPException(409,'This interview was ended or a newer request took over. Refresh its saved history.')

def finalise(db,item,early):
    now=datetime.now(timezone.utc)
    item.status='ended_early' if early else 'completed'
    item.ended_at=now
    state=dict(item.interview_state)
    state.pop('operation',None)
    state.update(phase=item.status,error=None,finalised_at=now.isoformat())
    item.interview_state=state
    levels=levels_for(db,item.id)
    for level in levels:
        if level.status=='in_progress':
            level.status='ended_early' if early else 'completed'
            level.ended_at=now
    for number in BUDGETS:
        if not any(level.level_number==number for level in levels):
            db.add(InterviewLevel(session_id=item.id,level_number=number,question_budget=BUDGETS[number],
                                  status='not_attempted',started_at=null()))
    for turn in all_turns(db,item.id):
        if turn.status=='asked':
            turn.status='unanswered_at_finalisation'
    db.commit()

def end_interview(db,session_id,user_id):
    item=owned(db,session_id,user_id,True)
    if item.status in FINAL_STATUSES:
        return public_view(db,item) # idempotent end, never resumes or writes new evidence
    if item.status!='in_progress':
        raise HTTPException(409,'Start the interview before ending it.')
    finalise(db,item,True)
    return public_view(db,item)

def redo(db,session_id,user_id,request_id):
    source=owned(db,session_id,user_id,True)
    if source.status not in FINAL_STATUSES:
        raise HTTPException(409,'Finish or explicitly end this interview before creating a new attempt.')
    previous=db.scalar(select(InterviewSession).where(InterviewSession.user_id==user_id,InterviewSession.redo_request_id==request_id))
    if previous:
        if previous.source_session_id!=source.id:
            raise HTTPException(409,'Use a new request identifier for this source attempt.')
        return previous
    fit=deepcopy(source.fit_summary)
    attempt=InterviewSession(user_id=user_id,source_session_id=source.id,redo_request_id=request_id,
        title=(source.title[:140]+' · New attempt'),jd_text=source.jd_text,resume_text=source.resume_text,
        input_metadata=deepcopy(source.input_metadata),role_profile=deepcopy(source.role_profile),
        candidate_profile=deepcopy(source.candidate_profile),fit_summary=deepcopy(fit),job_fit_score=source.job_fit_score,
        configuration={k:deepcopy(v) for k,v in source.configuration.items() if k!='interview'},
        status='ready',interview_state={},processing_metadata={})
    db.add(attempt);db.flush()
    # Canonical requirement IDs belong to the new attempt, never to the source.
    source_requirements=list(db.scalars(select(SessionRequirement).where(SessionRequirement.session_id==source.id)))
    for requirement in source_requirements:
        new_id=uuid4()
        for entry in fit.get('requirements',[]):
            if entry['id']==str(requirement.id):entry['id']=str(new_id)
        db.add(SessionRequirement(id=new_id,session_id=attempt.id,key=requirement.key,label=requirement.label,
            category=requirement.category,importance=requirement.importance,origin=requirement.origin,
            evidence=deepcopy(requirement.evidence),scoring_weight=requirement.scoring_weight,include_in_fit=requirement.include_in_fit))
        db.flush()
        match=db.scalar(select(RequirementMatch).where(RequirementMatch.requirement_id==requirement.id))
        if match:
            db.add(RequirementMatch(requirement_id=new_id,match_status=match.match_status,
                resume_evidence=deepcopy(match.resume_evidence),reason=match.reason,
                preparation_note=match.preparation_note,probe_target=match.probe_target))
    attempt.fit_summary=deepcopy(fit)
    db.commit();db.refresh(attempt)
    return attempt

def build_context(db,item,turns,topic,exclude=None,*,snapshot=None):
    snapshot=snapshot or load_snapshot(db,item.id,include_report=True)
    active=snapshot_level(snapshot)
    level_number=active.level_number if active else 1
    saved=snapshot['turns']
    if exclude:
        position=next((i for i,t in enumerate(saved) if t.id==exclude),len(saved))
        saved=saved[:position] # Recovery must not see future answers or findings.
    history=[t for t in saved if t.status in ('answered','skipped')]
    numbers={l.id:l.level_number for l in snapshot['levels']}
    ids={t.id for t in saved}
    evaluations={str(e.turn_id):e for e in snapshot['evaluations'] if e.turn_id in ids}
    coverage_turns=[{'id':str(t.id),'level':numbers[t.level_id],'number':t.turn_number,'status':t.status,
        'target_competencies':t.question_spec.get('target_competencies',[]),'answer':t.submitted_answer_text,
        'mode':t.answer_mode,'raw_transcript':t.raw_transcript,'delivery_metrics':t.question_spec.get('delivery_metrics')} for t in saved]
    report=snapshot['report']
    language=current_ratings(coverage_turns,(report.report_metadata or {}).get('communication',{})) if report else {}
    dimensions=competency_coverage(coverage_turns,{key:{'assessment_label':e.assessment_label,'competency_scores':e.competency_scores} for key,e in evaluations.items()},language,level_number)
    fields=('education','experience','skills','achievements','certifications','projects') if level_number==1 else ('projects','experience','skills','claims_to_probe')
    return {'level':level_number,'level_purpose':LEVEL_PURPOSES[level_number],'competency_coverage':dimensions,
        'role_title':item.role_profile.get('title',{}),
        'role_requirements':[{k:r.get(k) for k in ('key','label','importance','origin','category')} for r in item.fit_summary.get('requirements',[])],
        'candidate':{k:[{'value':excerpt(f['value'],220),'origin':f.get('origin','unspecified'),'excerpt':excerpt(f.get('excerpt',''),220 if k=='projects' else 100)} for f in item.candidate_profile.get(k,[])[:6]] for k in fields},
        'job_fit_gaps':[{k:m[k] for k in ('requirement_key','status','reason','probe_target')} for m in item.fit_summary.get('matches',[]) if m['status']!='strong'][:6] if level_number>1 else [],
        'priority_topics':priority_topics(item,level_number),'attempted_topics':coverage_for(item,level_number).get('attempted_topics',[]),
        'asked_question_inventory':[{'ref':f'L{numbers[t.level_id]}Q{t.turn_number}','level':numbers[t.level_id],'question':t.question_text} for t in saved],
        'remaining_turns':BUDGETS[level_number]-len(turns),'followup_chain_cap':CHAIN_CAPS[level_number],
        'session_memory':memory_context(history,evaluations,item.interview_state,numbers,topic),
        'conversation_history_scope':'source-linked cumulative answer memory; no raw previous answers sent',
        'current_answer_supplied_separately':exclude is not None}


def save_content_evaluation(db,item,turn,evaluation,calls,version):
    value=deepcopy(evaluation);update=value.pop('memory_update',None)
    if update:store_update(item,turn,update)
    db.add(TurnEvaluation(turn_id=turn.id,**value,evaluation_metadata={'calls':calls,'version':version,'memory_version':'answer-memory-v1' if update else None}))
    progress=dict(item.interview_state.get('content_progress',{}));progress.pop(str(turn.id),None)
    item.interview_state={**item.interview_state,'content_progress':progress}


def progress_for(item,turn):
    value=item.interview_state.get('content_progress',{}).get(str(turn.id),{})
    return value.get('chunks',{}) if value.get('answer_digest')==digest(turn.submitted_answer_text) else {}


def chunk_progress(db,session_id,user_id,turn,token):
    async def save(key,value):
        item=owned(db,session_id,user_id,True);require_operation(item,token)
        all_progress=deepcopy(item.interview_state.get('content_progress',{}))
        old=all_progress.get(str(turn.id),{})
        chunks=old.get('chunks',{}) if old.get('answer_digest')==digest(turn.submitted_answer_text) else {}
        all_progress[str(turn.id)]={'answer_digest':digest(turn.submitted_answer_text),'chunks':{**chunks,key:value}}
        item.interview_state={**item.interview_state,'content_progress':all_progress};db.commit()
    return save


async def ensure_answer_memory(db,item,token,exclude=None):
    """Backfill only missing content memories, with saved progress and no regrading."""
    pending=[t for t in all_turns(db,item.id) if t.status=='answered' and t.id!=exclude and t.submitted_answer_text and not entry_for(t,item.interview_state)]
    while pending:
        first=pending[0]
        if len(source_chunks(first.submitted_answer_text))>1:
            cache=progress_for(item,first);db.commit()
            parts,_=await extract_chunks(first.submitted_answer_text,first.question_spec,cache=cache,progress=chunk_progress(db,item.id,item.user_id,first,token))
            update,_=await merge_updates(parts,first.submitted_answer_text,first.question_spec)
            item=owned(db,item.id,item.user_id,True);require_operation(item,token);store_update(item,first,update)
            remaining=dict(item.interview_state.get('content_progress',{}));remaining.pop(str(first.id),None)
            item.interview_state={**item.interview_state,'content_progress':remaining};db.commit();pending.pop(0)
            continue
        batch=[];size=0
        for turn in pending:
            if len(batch)>=3 or batch and size+len(turn.submitted_answer_text)>3000:break
            if len(source_chunks(turn.submitted_answer_text))>1:break
            batch.append(turn);size+=len(turn.submitted_answer_text)
        records=[{'ref':str(t.id),'question':t.question_text,'rubric':t.question_spec['rubric'],'answer':t.submitted_answer_text} for t in batch]
        db.commit();updates,_=await extract_batch(records)
        item=owned(db,item.id,item.user_id,True);require_operation(item,token)
        for turn in batch:store_update(item,turn,updates[str(turn.id)])
        db.commit();pending=pending[len(batch):]

def start(db,session_id,user_id):
    item=owned(db,session_id,user_id,True)
    if item.status not in ('ready','in_progress'):
        raise HTTPException(409,'Complete document analysis before starting. Finalised attempts cannot reopen.')
    level,turns=level_and_turns(db,item.id)
    if not level:
        db.add(InterviewLevel(session_id=item.id,level_number=1,question_budget=4,started_at=datetime.now(timezone.utc)))
        item.interview_state={'phase':'screening','priority_topics':priority_topics(item),'attempted_topics':[],'assessed_topics':[],'level_coverage':{}}
        item.started_at=datetime.now(timezone.utc)
    item.configuration={**item.configuration,'interview':{'version':'lifecycle-v1','budgets':[4,4,7],
        'chain_caps':[1,1,2],'stt':'whisper-large-v3-turbo','tts':'browser local speech synthesis'}}
    item.status='in_progress'
    db.commit()

def accept_answer(db,session_id,user_id,body):
    item=owned(db,session_id,user_id,True)
    turn=next((t for t in all_turns(db,item.id) if t.id==body.turn_id),None)
    if not turn:raise HTTPException(404,'Question not found.')
    if turn.status!='asked':
        if turn.status in ('answered','skipped') and turn.question_spec.get('submission_id')==str(body.submission_id):
            return True
        raise HTTPException(409,'This answer is locked and cannot be replaced.')
    if item.status!='in_progress':
        raise HTTPException(409,'This attempt is finalised and cannot accept answers.')
    level,turns=level_and_turns(db,item.id)
    if turn.level_id!=level.id:
        raise HTTPException(409,'Answer only the current level question.')
    if busy_operation(item):
        raise HTTPException(409,'Processing is underway. Retry accepted work after it finishes.')
    if body.mode=='voice' and turn.raw_transcript is None and not body.skip:
        raise HTTPException(422,'Record and transcribe this answer before submitting in voice mode.')
    if not body.skip and not body.text.strip():
        raise HTTPException(422,'Enter an answer or explicitly skip.')
    state=dict(item.interview_state);state.pop('operation',None);item.interview_state=state
    turn.submitted_answer_text=None if body.skip else body.text.strip()
    turn.answer_mode=None if body.skip else body.mode
    if body.mode=='text':
        turn.raw_transcript=None;turn.response_duration_seconds=None
        turn.question_spec={k:v for k,v in turn.question_spec.items() if k!='delivery_metrics'}
    turn.filler_count=filler_count(turn.raw_transcript) if body.mode=='voice' and not body.skip else None
    turn.status='skipped' if body.skip else 'answered'
    turn.answered_at=datetime.now(timezone.utc)
    turn.question_spec={**turn.question_spec,'submission_id':str(body.submission_id)}
    db.commit()
    return False

async def advance(db,session_id,user_id):
    item=owned(db,session_id,user_id,True)
    if item.status!='in_progress':
        raise HTTPException(409,'Finalised attempts cannot resume. Start a new attempt instead.')
    level,turns=level_and_turns(db,item.id)
    if not level:raise HTTPException(409,'Start the interview first.')
    if any(t.status=='asked' for t in turns):
        return public_view(db,item)
    if busy_operation(item):
        raise HTTPException(409,'Accepted work is processing. Refresh shortly; stalled processing can be retried after eight minutes.')
    token=str(uuid4())
    item.interview_state={**item.interview_state,'error':None,'error_code':None,'error_stage':None,'error_diagnostics':{},'operation':{'token':token,'started_at':datetime.now(timezone.utc).isoformat()}}
    db.commit()
    stage='evaluation'
    try:
        last=turns[-1] if turns else None
        evaluated=db.scalar(select(TurnEvaluation).where(TurnEvaluation.turn_id==last.id)) if last else None
        stage='memory'
        await ensure_answer_memory(db,item,token,exclude=last.id if last and not evaluated else None)
        item=owned(db,session_id,user_id,True);require_operation(item,token)
        stage='evaluation'
        if last and last.status=='answered' and not evaluated:
            context=build_context(db,item,turns,last.question_spec['topic_key'],last.id)
            answer,spec=last.submitted_answer_text,deepcopy(last.question_spec)
            spec.pop('delivery_metrics',None)
            db.commit()
            if len(source_chunks(answer))>1:
                evaluation,metadata=await evaluate_answer(context,spec,answer,cache=progress_for(item,last),progress=chunk_progress(db,session_id,user_id,last,token))
            else:evaluation,metadata=await evaluate_answer(context,spec,answer)
            item=owned(db,session_id,user_id,True);require_operation(item,token)
            save_content_evaluation(db,item,last,evaluation,metadata,'evaluation-v6-content-memory')
            db.commit()
        item=owned(db,session_id,user_id,True);require_operation(item,token)
        level,turns=level_and_turns(db,item.id)
        last=turns[-1] if turns else None
        evaluated=db.scalar(select(TurnEvaluation).where(TurnEvaluation.turn_id==last.id)) if last else None
        stage='memory'
        await ensure_answer_memory(db,item,token)
        item=owned(db,session_id,user_id,True);require_operation(item,token)
        coverage=coverage_for(item,level.level_number)
        attempted=list(coverage.get('attempted_topics',[]));assessed=list(coverage.get('assessed_topics',[]))
        if last:
            topic=last.question_spec['topic_key']
            if topic not in attempted:attempted.append(topic)
            if evaluated and evaluated.assessment_label!='Unassessable' and topic not in assessed:assessed.append(topic)
        coverage={'attempted_topics':attempted,'assessed_topics':assessed}
        item.interview_state={**item.interview_state,'level_coverage':{**item.interview_state.get('level_coverage',{}),str(level.level_number):coverage},
                              **coverage}
        uncovered=[topic for topic in priority_topics(item,level.level_number) if topic not in attempted]
        depth=0;parent=last;by_id={t.id:t for t in turns}
        while parent and parent.parent_turn_id:
            depth+=1;parent=by_id[parent.parent_turn_id]
        recommendation=evaluated.recommended_action if evaluated else 'new_topic'
        action=permitted_action(level.level_number,len(turns),depth,len(uncovered),recommendation)
        item.interview_state={**item.interview_state,'last_action':action}
        if action=='level_complete':
            level.status='completed';level.ended_at=datetime.now(timezone.utc)
            if level.level_number==3:
                finalise(db,item,False)
                return public_view(db,item)
            number=level.level_number+1
            level=InterviewLevel(session_id=item.id,level_number=number,question_budget=BUDGETS[number],
                                 status='in_progress',started_at=datetime.now(timezone.utc))
            db.add(level);db.flush()
            item.interview_state={**item.interview_state,'phase':{2:'competency',3:'deep_dive'}[number],
                                  'attempted_topics':[],'assessed_topics':[]}
            turns=[];last=None;evaluated=None;action='new_topic'
            db.commit() # A failure generating the first question can retry this same new level.
        followup=bool(last) and action!='new_topic'
        topic=last.question_spec['topic_key'] if followup else None
        difficulty=level.level_number
        snapshot=load_snapshot(db,item.id,include_report=True)
        context=build_context(db,item,turns,topic,snapshot=snapshot)
        if followup and context['competency_coverage']['reserve_for_unassessed']:
            # Reserve scarce later opportunities; the model still selects the topic.
            action='new_topic';followup=False;topic=None
            item.interview_state={**item.interview_state,'last_action':action}
            context=build_context(db,item,turns,topic,snapshot=snapshot)
        context['routing_feedback']={'recommended_action':recommendation,
            'reason':evaluated.action_reason if evaluated else None,'permitted_action':action}
        previous=[t.question_text for t in snapshot['turns']]
        level_id=level.id;parent_id=last.id if followup else None;number=len(turns)+1
        db.commit() # No write transaction while waiting on the provider.
        stage='next_question'
        question,metadata=await generate_question(context,topic,difficulty,action,previous)
        # Defence at persistence boundary as well as inside the model adapter.
        validate_question(Question.model_validate(question),topic,difficulty,previous)
        item=owned(db,session_id,user_id,True);require_operation(item,token)
        db.add(InterviewTurn(level_id=level_id,turn_number=number,parent_turn_id=parent_id,
            question_text=question['question_text'],question_spec={**question,'generation_metadata':metadata,'action':action,
            'responds_to_turn_id':str(last.id) if last else None,'generator_version':PROMPT_VERSION}))
        db.commit()
    except Exception as exc:
        db.rollback()
        item=owned(db,session_id,user_id,True)
        message=('Your accepted answer is saved. The next question could not be prepared; retry processing.'
                 if stage=='next_question' else 'Your accepted answer is saved. Interview memory could not be updated; retry processing.' if stage=='memory' else 'Your accepted answer is saved. Evaluation did not finish; retry processing.')
        if item.status=='in_progress' and item.interview_state.get('operation',{}).get('token')==token:
            item.interview_state={**item.interview_state,'error':str(exc) if isinstance(exc,RequestSizeError) else message,'error_stage':stage,
                'error_code':'request_size' if isinstance(exc,RequestSizeError) else 'model_validation' if isinstance(exc,(ModelValidationError,ValueError)) else 'provider_or_processing',
                'error_diagnostics':getattr(exc,'diagnostics',{})}
            db.commit()
        if isinstance(exc,HTTPException):raise
        if isinstance(exc,AnalysisUnavailable) and not isinstance(exc,ModelValidationError):
            message=str(exc).replace('Analysis quota is temporarily exhausted. Your documents are saved; retry after the provider limit resets.',
                'Groq quota paused processing. Accepted answers and completed evaluations are saved. Retry after the limit resets.')
        raise HTTPException(503,message) from None
    finally:
        db.rollback()
        item=owned(db,session_id,user_id,True)
        if item.interview_state.get('operation',{}).get('token')==token:
            state=dict(item.interview_state);state.pop('operation',None);item.interview_state=state;db.commit()
    return public_view(db,item)
