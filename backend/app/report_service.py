from copy import deepcopy
from datetime import datetime,timezone,timedelta
import hashlib
import json
import re
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
import logging
from .analysis_routes import owned
from .models import InterviewReport,InterviewTurn,TurnEvaluation,InterviewLevel
from .interview_service import FINAL_STATUSES,all_turns,levels_for,build_context,save_content_evaluation
from .interview_prompts import LEVEL_PURPOSES
from .interview_ai import evaluate_answer
from .report_scoring import aggregate_report,POLICY_VERSION
from .report_schemas import ReportNarrative
from .communication import assess_communication,current_ratings,VERSION as COMMUNICATION_VERSION
from .fit import excerpt_location
from .llm import structured,AnalysisUnavailable,ModelValidationError

NARRATIVE_VERSION="report-guidance-v4-specific-preparation"
REPORT_SYNTHESIS_PROMPT="Write final preparation guidance from SAVED assessments, accepted answers and computed results only. Never invent, recalculate or restate numeric scores/readiness bands; Python owns them.\nReturn a 2-3 sentence summary, at most four evidence-linked strengths and four weaknesses, and one step for EVERY supplied objective in rank order.\nEach preparation step needs: objective_id; evidence_summary explaining the particular observed gap or missing evidence; 2-5 distinct concrete review_topics; a NEW practical exercise in action; an observable, testable success_check; turn_ids belonging to that objective. Keep fields concise. Avoid broad advice such as review ML or practise Python. Example only: a metric-choice gap may lead to precision/recall, class imbalance and threshold selection, an exercise comparing thresholds, and a check justifying one using error costs. Select topics from this candidate's actual evidence, not this example.\nCite only supplied source_lines keys. Every strength/weakness must cite an answer. Missing document/coverage evidence is NOT inability: put it in preparation, not weaknesses. Empty supported-insight lists are valid.\nAccepted answers establish what the candidate claims; question premises and grader suggestions do not prove experience. Respect denials and honest limits. API use is not proof of training or custom NLP; a hypothetical proposal is not completed work. Do not invent technologies, metrics, figures or hiring likelihood. Exercises are prospective: never ask for steps you used/applied/implemented when not claimed. Treat unsupported question premises as limitations.\nConfidence means a supported position, clear contribution and consistent follow-ups; honest uncertainty alone is not weakness. Never infer personality, accent or emotion. Acknowledge limited selected evidence and prompted improvement. Do not turn the report into another interview or ask the candidate to change saved answers."

def final_owned(db,session_id,user_id,lock=False):
    item=owned(db,session_id,user_id,lock)
    if item.status not in FINAL_STATUSES:
        raise HTTPException(409,'Report feedback is available only after this interview is completed or explicitly ended.')
    return item

def report_row(db,session_id):
    return db.scalar(select(InterviewReport).where(InterviewReport.session_id==session_id))

def fresh_operation(report):
    op=report.report_metadata.get('operation') if report else None
    return bool(op and datetime.now(timezone.utc)-datetime.fromisoformat(op['started_at'])<timedelta(minutes=8))

def evidence(db,item):
    levels={level.id:level.level_number for level in levels_for(db,item.id)}
    rows=all_turns(db,item.id)
    evaluations={str(e.turn_id):e for e in db.scalars(select(TurnEvaluation).join(InterviewTurn)
        .join(InterviewLevel).where(InterviewLevel.session_id==item.id))}
    turns=[{'id':str(t.id),'level':levels[t.level_id],'number':t.turn_number,'question':t.question_text,
        'answer':t.submitted_answer_text,'raw_transcript':t.raw_transcript,'status':t.status,
        'parent_turn_id':str(t.parent_turn_id) if t.parent_turn_id else None,
        'topic_key':t.question_spec.get('topic_key',''),'target_competencies':t.question_spec.get('target_competencies',[]),
        'mode':t.answer_mode,'filler_count':t.filler_count,'delivery_metrics':t.question_spec.get('delivery_metrics'),'response_duration_seconds':t.response_duration_seconds,'rubric':t.question_spec.get('rubric',{})} for t in rows]
    data={key:{field:getattr(value,field) for field in ('assessment_label','competency_scores','reasoning',
        'answer_evidence','strengths','improvements','ideal_direction')} for key,value in evaluations.items()}
    report=report_row(db,item.id)
    language=current_ratings(turns,(report.report_metadata or {}).get('communication',{})) if report else {}
    metrics=aggregate_report(turns,data,item.fit_summary.get('requirements',[]),item.fit_summary.get('matches',[]),item.job_fit_score,item.status,communication=language)
    # Duration is display-only metadata; adding it must not invalidate saved summaries.
    scoring_turns=[{k:v for k,v in turn.items() if k!='response_duration_seconds' and (k!='delivery_metrics' or v is not None)} for turn in turns]
    fingerprint=hashlib.sha256(json.dumps({'turns':scoring_turns,'evaluations':data,'fit':item.job_fit_score,
        'requirements':item.fit_summary,'status':item.status,'policy':POLICY_VERSION,'guidance':NARRATIVE_VERSION,'communication':language},sort_keys=True,default=str).encode()).hexdigest()
    return turns,data,metrics,fingerprint

def public_report(db,item):
    turns,evaluations,metrics,fingerprint=evidence(db,item)
    report=report_row(db,item.id)
    current=bool(report and report.report_metadata.get('evidence_digest')==fingerprint and report.status=='ready')
    feedback=[]
    for turn in turns:
        evaluation=deepcopy(evaluations.get(turn['id']))
        if evaluation:
            # Source excerpts remain tied to this accepted answer.
            checked=[]
            for quote in evaluation['answer_evidence']:
                try:checked.append(excerpt_location(quote,turn['answer'] or '')['excerpt'])
                except ValueError:pass
            evaluation['answer_evidence']=checked
        feedback.append({**turn,'evaluation':evaluation})
    return {'session_id':str(item.id),'title':item.title,'attempt_status':item.status,
        'status':'ready' if current else report.status if report and report.status!='ready' else 'stale' if report else 'not_generated',
        'processing':fresh_operation(report),'error':report.report_metadata.get('error') if report else None,
        'generated_at':report.generated_at.isoformat() if current and report.generated_at else None,
        'metrics':metrics,'feedback':feedback,
        'narrative':{'summary':report.summary,'strengths':report.strengths,'weaknesses':report.weaknesses,
                     'preparation_plan':report.preparation_plan} if current else None}

def store_metrics(report,metrics):
    report.overall_score=metrics['overall_score']
    report.competency_summary={'dimensions':metrics['competencies'],'evidence_units':metrics['evidence_units']}
    report.coverage_summary=metrics['coverage']
    report.readiness_label=metrics['readiness']['label'];report.readiness_score=metrics['readiness']['score']

def create_or_get(db,item):
    report=report_row(db,item.id)
    if not report:
        report=InterviewReport(session_id=item.id)
        db.add(report);db.flush()
    return report

def start_operation(report,kind):
    if fresh_operation(report):raise HTTPException(409,'Report processing is already running. Refresh shortly; stalled work can be retried after eight minutes.')
    token=str(uuid4())
    report.status='generating'
    report.report_metadata={**report.report_metadata,'error':None,
        'operation':{'token':token,'kind':kind,'started_at':datetime.now(timezone.utc).isoformat()}}
    return token

def check_operation(report,token):
    if not report or report.report_metadata.get('operation',{}).get('token')!=token:
        raise HTTPException(409,'A newer report request took over. Refresh the saved report.')

def finish_metadata(report,token,**fields):
    check_operation(report,token)
    metadata={**report.report_metadata,**fields};metadata.pop('operation',None);report.report_metadata=metadata

def narrative_input(turns,evaluations,metrics):
    by_id={turn['id']:turn for turn in turns}
    # Keep enough cited evidence for the top priorities and representative strengths.
    selected=[]
    for objective in metrics['priorities']:
        for turn_id in objective['turn_ids'][:1]:
            if turn_id in evaluations and turn_id not in selected:selected.append(turn_id)
    for objective in metrics['priorities']:
        for turn_id in objective['turn_ids'][1:2]:
            if turn_id in evaluations and turn_id not in selected:selected.append(turn_id)
    ranked=sorted(turns,key=lambda turn:max((entry.get('score',0) for entry in evaluations.get(turn['id'],{}).get('competency_scores',[])),default=0),reverse=True)
    for turn in ranked:
        if turn['id'] in evaluations and turn['id'] not in selected:selected.append(turn['id'])
    selected=selected[:6]
    source={}
    for turn_id in selected:
        turn=by_id[turn_id];evaluation=evaluations[turn_id]
        answer=turn.get('answer') or ''
        answer_context=answer if len(answer)<=360 else answer[:220]+' [middle omitted; full answer saved] '+answer[-100:]
        source[turn_id]={'reference':f"Level {turn['level']} question {turn['number']}",
            'question':turn['question'][:300],'assessment':evaluation['assessment_label'],
            'accepted_answer_excerpt':answer_context,
            'assessment_reason':evaluation['reasoning'][:260],
            'assessment_improvement':evaluation['improvements'][:3],
            'saved_criteria':turn.get('rubric',{}).get('adequate_criteria',[])[:3]}
    objectives=[{k:objective[k] for k in ('id','title','source','why','rank','turn_ids','practice_task','success_check')}
        for objective in metrics['priorities']]
    # Only references actually supplied to the narrative model may be returned.
    for objective in objectives:
        objective['turn_ids']=[key for key in objective['turn_ids'] if key in source]
        for key,limit in (('title',100),('why',450),('practice_task',180),('success_check',110)):
            objective[key]=objective[key][:limit]
    return {'source_lines':source,'objectives':objectives,
        'computed_results':{'overall_score':metrics['overall_score'],
            'competencies':[{k:d[k] for k in ('key','score_percent','assessed_units')} for d in metrics['competencies']],
            'readiness':metrics['readiness']['label'],'coverage_sufficient':metrics['readiness']['coverage_sufficient']},
        'scope_note':'Evidence is a selected subset. Full question feedback remains available separately. Never invent omitted details.'}

async def synthesize_report(turns,evaluations,metrics):
    data=narrative_input(turns,evaluations,metrics)
    valid_turns=set(data['source_lines']);objectives={obj['id']:obj for obj in data['objectives']}
    def validate(value):
        for insight in value.strengths+value.weaknesses:
            if len(set(insight.turn_ids))!=len(insight.turn_ids) or not set(insight.turn_ids)<=valid_turns:
                raise ValueError('Cite only unique supplied owned turn IDs')
        ids=[step.objective_id for step in value.preparation_plan]
        if len(set(ids))!=len(ids) or not set(ids)<=set(objectives):
            raise ValueError('Use only unique supplied preparation objective IDs')
        if set(ids)!=set(objectives):
            raise ValueError('Provide one practice step for each supplied preparation objective')
        for step in value.preparation_plan:
            # A practice task is a NEW exercise, not an assumption about past work.
            # This general output check never selects an interview topic or library.
            retrospective=r"\byou(?:['’]ve)?(?:\s+(?:have|had|previously|actually|personally|specifically)){0,3}\s+(?:used|applied|implemented|built|trained|deployed|selected|chose|achieved|performed)\b"
            if re.search(retrospective,step.action+' '+step.success_check,re.I):
                raise ValueError('Write a NEW prospective practice exercise. Do not ask the candidate to recount steps you used/applied/implemented; that assumes past experience. Keep the action and success criterion about the new exercise.')
            objective=objectives[step.objective_id]
            if len(set(step.turn_ids))!=len(step.turn_ids):
                raise ValueError('Practice evidence references must be unique')
            if objective['source']=='interview' and objective['turn_ids'] and not step.turn_ids:
                # The Python-ranked objective already owns these supplied sources.
                # Link its known provenance when the model omits an optional list.
                step.turn_ids=objective['turn_ids'][:1]
            if not set(step.turn_ids)<=set(objective['turn_ids']):
                raise ValueError('Practice evidence must belong to its supplied objective')
            step.review_topics=[topic.strip() for topic in step.review_topics if topic.strip()]
            if not 2<=len(step.review_topics)<=5 or len({topic.casefold() for topic in step.review_topics})!=len(step.review_topics):
                raise ValueError('Provide two to five distinct concrete review subtopics for every preparation objective')
            if not step.evidence_summary.strip():
                raise ValueError('Explain the observed gap or missing evidence behind each preparation priority')

        return value
    result,_,metadata=await structured(ReportNarrative,
        REPORT_SYNTHESIS_PROMPT,
        data,validate,purpose='interview',max_tokens=2400)
    output=result.model_dump()
    output['preparation_plan'].sort(key=lambda step:objectives[step['objective_id']]['rank'])
    return output,metadata

async def generate_report(db,session_id,user_id,operation_token=None):
    item=final_owned(db,session_id,user_id,True)
    turns,evaluations,metrics,fingerprint=evidence(db,item)
    report=create_or_get(db,item)
    if report.status=='ready' and report.report_metadata.get('evidence_digest')==fingerprint:
        return public_report(db,item)
    if operation_token:
        check_operation(report,operation_token);token=operation_token
    else:token=start_operation(report,'generate')
    store_metrics(report,metrics)
    db.commit()
    try:
        if not metrics['coverage']['evaluated']:
            narrative={'summary':'No assessable answers were collected. Scores and readiness cannot be established. Use the document-based priorities to prepare for a new attempt.',
                'strengths':[],'weaknesses':[],'preparation_plan':[{'objective_id':obj['id'],
                    'action':obj['practice_task'],'success_check':obj['success_check'],'turn_ids':[],
                    'evidence_summary':obj['why'],'review_topics':[obj['title'],'Evidence and limits to establish in a new attempt']} for obj in metrics['priorities']]}
            metadata=[];method='no_assessable_answers'
        else:
            narrative,metadata=await synthesize_report(turns,evaluations,metrics)
            method='saved_evidence_synthesis'
        item=final_owned(db,session_id,user_id,True);report=report_row(db,session_id)
        check_operation(report,token)
        # Report generation cannot change scoring inputs; guard concurrent recovery.
        _,_,current,current_digest=evidence(db,item)
        if current_digest!=fingerprint:raise HTTPException(409,'Evaluation evidence changed. Regenerate the report from its new saved evidence.')
        store_metrics(report,current)
        report.summary=narrative['summary'];report.strengths=narrative['strengths']
        report.weaknesses=narrative['weaknesses'];report.preparation_plan=narrative['preparation_plan']
        report.status='ready';report.generated_at=datetime.now(timezone.utc)
        finish_metadata(report,token,evidence_digest=fingerprint,policy_version=POLICY_VERSION,
            readiness_policy=current['readiness'],guidance_version=NARRATIVE_VERSION,calls=metadata,method=method)
        db.commit()
    except Exception as exc:
        db.rollback();item=final_owned(db,session_id,user_id,True);report=report_row(db,session_id)
        if report and report.report_metadata.get('operation',{}).get('token')==token:
            report.status='failed'
            finish_metadata(report,token,error='Report guidance could not be generated. Saved scores and feedback remain available; retry guidance.',error_code=type(exc).__name__)
            db.commit()
        if isinstance(exc,HTTPException):raise
        raise HTTPException(503,'Report guidance could not be generated. Your saved scores and feedback are available; retry guidance.') from None
    return public_report(db,item)

async def recover_evaluation(db,session_id,user_id):
    item=final_owned(db,session_id,user_id,True)
    rows=all_turns(db,item.id)
    evaluated=set(db.scalars(select(TurnEvaluation.turn_id).join(InterviewTurn).join(InterviewLevel).where(InterviewLevel.session_id==item.id)))
    pending=next((turn for turn in rows if turn.status=='answered' and turn.id not in evaluated),None)
    if not pending:return public_report(db,item)
    report=create_or_get(db,item);token=start_operation(report,'recover_evaluation')
    prior={str(turn.id) for turn in rows[:rows.index(pending)]}
    level=next(level for level in levels_for(db,item.id) if level.id==pending.level_id)
    level_turns=[turn for turn in rows if turn.level_id==level.id]
    context=build_context(db,item,level_turns,pending.question_spec.get('topic_key'),pending.id)
    context.update(level=level.level_number,level_purpose=LEVEL_PURPOSES[level.level_number])
    number_by_id={entry.id:entry.level_number for entry in levels_for(db,item.id)}
    prior_refs={f'L{number_by_id[entry.level_id]}Q{entry.turn_number}' for entry in rows[:rows.index(pending)]}
    context['asked_question_inventory']=[entry for entry in context.get('asked_question_inventory',[]) if entry['ref'] in prior_refs]
    for key in ('conversation_history','history_index','relevant_older_history','earlier_findings'):
        context[key]=[entry for entry in context.get(key,[]) if entry.get('turn_id') in prior]
    answer=pending.submitted_answer_text;question=deepcopy(pending.question_spec);turn_id=pending.id
    question.pop('delivery_metrics',None)
    db.commit()
    try:
        evaluation,metadata=await evaluate_answer(context,question,answer)
        item=final_owned(db,session_id,user_id,True);report=report_row(db,session_id);check_operation(report,token)
        if db.scalar(select(TurnEvaluation).where(TurnEvaluation.turn_id==turn_id)) is None:
            save_content_evaluation(db,item,pending,evaluation,metadata,'report-recovery-v2-content-memory')
        report.status='pending';finish_metadata(report,token,error=None)
        db.commit()
    except Exception as exc:
        db.rollback();item=final_owned(db,session_id,user_id,True);report=report_row(db,session_id)
        if report and report.report_metadata.get('operation',{}).get('token')==token:
            report.status='failed';finish_metadata(report,token,error='The saved answer could not be evaluated. Retry its evaluation; the interview stays finalised.')
            db.commit()
        if isinstance(exc,HTTPException):raise
        raise HTTPException(503,'The saved answer could not be evaluated. The interview stays finalised and its accepted text is unchanged.') from None
    return public_report(db,item)


async def update_communication(db,session_id,user_id):
    item=final_owned(db,session_id,user_id,True)
    report=create_or_get(db,item)
    token=start_operation(report,'communication')
    db.commit()
    try:
        turns,_,_,_=evidence(db,item)
        cached=current_ratings(turns,report.report_metadata.get('communication',{}))
        for turn in turns:
            if turn['status']!='answered' or not turn.get('answer') or turn['id'] in cached:continue
            rating=await assess_communication(turn)
            item=final_owned(db,session_id,user_id,True);report=report_row(db,session_id)
            check_operation(report,token)
            cached={**cached,turn['id']:rating}
            # Progress is saved separately; no turn or TurnEvaluation is mutated.
            report.report_metadata={**report.report_metadata,'communication':cached}
            db.commit()
        item=final_owned(db,session_id,user_id,True);report=report_row(db,session_id)
        _,_,metrics,_=evidence(db,item)
        store_metrics(report,metrics)
        report.status='pending'
        finish_metadata(report,token,communication_version=COMMUNICATION_VERSION,error=None)
        db.commit()
    except Exception as exc:
        db.rollback();report=report_row(db,session_id)
        if report and report.report_metadata.get('operation',{}).get('token')==token:
            report.status='pending'
            finish_metadata(report,token,error='Communication assessment paused. Saved history and completed communication ratings are preserved; retry to continue.')
            db.commit()
        if isinstance(exc,HTTPException):raise
        raise HTTPException(503,'Communication assessment paused. Your history is preserved; retry to continue from saved ratings.') from None
    return public_report(db,item)


def queue_report(db,item,background_tasks):
    """Persist the operation before returning scores; make one automatic attempt per digest."""
    if item.status not in FINAL_STATUSES:return False
    _,_,metrics,fingerprint=evidence(db,item)
    report=create_or_get(db,item)
    if (report.status=='ready' and report.report_metadata.get('evidence_digest')==fingerprint) or fresh_operation(report):
        return False
    if report.report_metadata.get('automatic_digest')==fingerprint:
        return False # A failed automatic call needs an explicit retry, not a reload loop.
    token=start_operation(report,'automatic_generate')
    store_metrics(report,metrics)
    report.report_metadata={**report.report_metadata,'automatic_digest':fingerprint}
    db.commit()
    background_tasks.add_task(run_automatic_report,db.get_bind(),item.id,item.user_id,token)
    return True


async def run_automatic_report(bind,session_id,user_id,token):
    # Own connection/session: response dependency teardown cannot close this job's DB.
    with Session(bind) as db:
        try:
            from .communication_jobs import fresh
            import asyncio
            while True:
                db.expire_all();row=report_row(db,session_id)
                active=any(fresh(job) for job in (row.report_metadata if row else {}).get('communication_jobs',{}).values())
                db.commit()
                if not active:break
                await asyncio.sleep(1)
            await generate_report(db,session_id,user_id,operation_token=token)
        except Exception as exc:
            # generate_report persists a retryable failure; never fail interview finalisation.
            logging.getLogger(__name__).warning('Automatic report generation paused (%s)',type(exc).__name__)
