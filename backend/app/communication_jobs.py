"""LLM1 jobs are independent of content routing and keep per-answer progress."""
from copy import deepcopy
from datetime import datetime,timezone,timedelta
from uuid import uuid4
import logging
from sqlalchemy import select
from sqlalchemy.orm import Session
from .models import InterviewReport,InterviewTurn,InterviewLevel
from .analysis_routes import owned
from .communication import assess_communication,current_ratings,answer_digest


def report_for(db,item):
    report=db.scalar(select(InterviewReport).where(InterviewReport.session_id==item.id).execution_options(populate_existing=True).with_for_update())
    if not report:report=InterviewReport(session_id=item.id);db.add(report);db.flush()
    return report


def fresh(job):
    return bool(job and job.get('status')=='running' and datetime.now(timezone.utc)-datetime.fromisoformat(job['started_at'])<timedelta(minutes=8))


def turn_data(turn):
    return {'id':str(turn.id),'answer':turn.submitted_answer_text,'raw_transcript':turn.raw_transcript,
        'mode':turn.answer_mode,'status':turn.status,'delivery_metrics':turn.question_spec.get('delivery_metrics')}


def queue_communication(db,item,background_tasks,all_pending=False):
    rows=list(db.scalars(select(InterviewTurn).join(InterviewLevel).where(InterviewLevel.session_id==item.id,InterviewTurn.status=='answered').order_by(InterviewLevel.level_number,InterviewTurn.turn_number)))
    if not rows:return
    if not all_pending:rows=rows[-1:]
    report=report_for(db,item);metadata=deepcopy(report.report_metadata or {})
    jobs=metadata.get('communication_jobs',{});ratings=metadata.get('communication',{})
    queued=[]
    for turn in rows:
        data=turn_data(turn);key=str(turn.id);old=jobs.get(key,{})
        if current_ratings([data],ratings) or fresh(old):continue
        signature=answer_digest(data)
        if old.get('status')=='failed' and old.get('answer_digest')==signature:continue
        token=str(uuid4());jobs[key]={'status':'running','token':token,'answer_digest':signature,'started_at':datetime.now(timezone.utc).isoformat()}
        queued.append((turn.id,token))
    if not queued:return
    report.report_metadata={**metadata,'communication_jobs':jobs};db.commit()
    for turn_id,token in queued:background_tasks.add_task(run_communication,db.get_bind(),item.id,item.user_id,turn_id,token)


async def run_communication(bind,session_id,user_id,turn_id,token):
    with Session(bind) as db:
        try:
            item=owned(db,session_id,user_id)
            turn=db.scalar(select(InterviewTurn).join(InterviewLevel).where(InterviewLevel.session_id==session_id,InterviewTurn.id==turn_id))
            if not turn or turn.status!='answered':return
            data=turn_data(turn);report=report_for(db,item)
            job=report.report_metadata.get('communication_jobs',{}).get(str(turn_id),{})
            if job.get('token')!=token:return
            cached=report.report_metadata.get('communication_progress',{}).get(str(turn_id),{})
            chunks=cached.get('chunks',{}) if cached.get('answer_digest')==answer_digest(data) else {}
            db.commit()
            async def progress(key,value):
                item=owned(db,session_id,user_id);row=report_for(db,item)
                if row.report_metadata.get('communication_jobs',{}).get(str(turn_id),{}).get('token')!=token:raise RuntimeError('Newer communication job took over')
                saved=deepcopy(row.report_metadata.get('communication_progress',{}))
                old=saved.get(str(turn_id),{})
                parts=old.get('chunks',{}) if old.get('answer_digest')==answer_digest(data) else {}
                saved[str(turn_id)]={'answer_digest':answer_digest(data),'chunks':{**parts,key:value}}
                row.report_metadata={**row.report_metadata,'communication_progress':saved};db.commit()
            rating=await assess_communication(data,cache=chunks,progress=progress)
            item=owned(db,session_id,user_id);report=report_for(db,item)
            jobs=deepcopy(report.report_metadata.get('communication_jobs',{}))
            if jobs.get(str(turn_id),{}).get('token')!=token:return
            jobs[str(turn_id)]={**jobs[str(turn_id)],'status':'ready'}
            saved=deepcopy(report.report_metadata.get('communication_progress',{}));saved.pop(str(turn_id),None)
            report.report_metadata={**report.report_metadata,'communication':{**report.report_metadata.get('communication',{}),str(turn_id):rating},'communication_jobs':jobs,'communication_progress':saved}
            db.commit()
        except Exception as exc:
            db.rollback()
            try:
                item=owned(db,session_id,user_id);report=report_for(db,item)
                jobs=deepcopy(report.report_metadata.get('communication_jobs',{}))
                if jobs.get(str(turn_id),{}).get('token')==token:
                    jobs[str(turn_id)]={**jobs[str(turn_id)],'status':'failed','error_code':type(exc).__name__}
                    report.report_metadata={**report.report_metadata,'communication_jobs':jobs};db.commit()
            except Exception:db.rollback()
            logging.getLogger(__name__).warning('Communication job paused (%s)',type(exc).__name__)
