"""Optional archive work after the response; never part of question generation."""
from copy import deepcopy
from datetime import datetime,timezone,timedelta
from uuid import uuid4
import logging
from sqlalchemy.orm import Session
from .analysis_routes import owned
from .interview_service import load_snapshot
from .answer_memory import memory_context
from .memory_archive import consolidate


def current_job(job):
    try:return job.get('status')=='running' and datetime.now(timezone.utc)-datetime.fromisoformat(job['started_at'])<timedelta(minutes=8)
    except (KeyError,TypeError,ValueError):return False


def queue_archive(db,item,background_tasks):
    memory=deepcopy(item.interview_state.get('answer_memory',{}))
    entries=memory.get('entries',{});prefix=((len(entries)-2)//6)*6
    if prefix<6 or memory.get('archive',{}).get('prefix',0)>=prefix:return
    job=memory.get('archive_job',{})
    if current_job(job) or job.get('prefix')==prefix and job.get('status') in ('ready','deferred'):return
    token=str(uuid4())
    memory['archive_job']={'token':token,'prefix':prefix,'status':'running','started_at':datetime.now(timezone.utc).isoformat()}
    item.interview_state={**item.interview_state,'answer_memory':memory};db.commit()
    background_tasks.add_task(run_archive,db.get_bind(),item.id,item.user_id,token)


async def run_archive(bind,session_id,user_id,token):
    with Session(bind) as db:
        try:
            item=owned(db,session_id,user_id)
            memory=deepcopy(item.interview_state.get('answer_memory',{}))
            if memory.get('archive_job',{}).get('token')!=token:return
            snapshot=load_snapshot(db,session_id)
            numbers={level.id:level.level_number for level in snapshot['levels']}
            evaluations={str(e.turn_id):e for e in snapshot['evaluations']}
            history=[t for t in snapshot['turns'] if t.status in ('answered','skipped')]
            evidence=memory_context(history,evaluations,item.interview_state,numbers)
            source_digests={key:value.get('answer_digest') for key,value in memory.get('entries',{}).items()}
            db.commit() # No transaction/row lock while the optional model is running.
            archive,changed=await consolidate(evidence,memory.get('archive'))
            db.expire_all();item=owned(db,session_id,user_id,True)
            latest=deepcopy(item.interview_state.get('answer_memory',{}))
            if latest.get('archive_job',{}).get('token')!=token:return
            valid=all(latest.get('entries',{}).get(key,{}).get('answer_digest')==value for key,value in source_digests.items())
            newer=latest.get('archive',{}).get('prefix',0)>archive.get('prefix',0)
            if changed and valid and not newer:latest['archive']=archive
            latest['archive_job']={**latest['archive_job'],'status':'ready' if valid else 'deferred'}
            # Merge ONLY archive fields into a freshly locked state. A newer
            # answer, operation token, chunks, communication or grade is untouched.
            item.interview_state={**item.interview_state,'answer_memory':latest};db.commit()
        except Exception as exc:
            db.rollback()
            try:
                db.expire_all();item=owned(db,session_id,user_id,True)
                memory=deepcopy(item.interview_state.get('answer_memory',{}))
                if memory.get('archive_job',{}).get('token')==token:
                    memory['archive_job']={**memory['archive_job'],'status':'deferred','error_code':type(exc).__name__}
                    item.interview_state={**item.interview_state,'answer_memory':memory};db.commit()
            except Exception:db.rollback()
            logging.getLogger(__name__).info('Background archive deferred (%s)',type(exc).__name__)
