import asyncio
from .pause_detection import measure_pauses
from uuid import UUID,uuid4
from fastapi import APIRouter,Depends,HTTPException,Request,Query,BackgroundTasks
from sqlalchemy.orm import Session
from .auth import current_identity,Identity
from .database import get_db
from .analysis_routes import owned
from .interview_schemas import AnswerInput,RedoInput
from .schemas import SessionDetail
from .interview_service import start,advance,accept_answer,public_view,level_and_turns,end_interview,redo
from .speech import transcribe_audio,MAX_AUDIO_BYTES
from .llm import AnalysisUnavailable
from .report_service import queue_report
from .communication_jobs import queue_communication
from .memory_jobs import queue_archive
from fastapi.responses import JSONResponse
import logging

router=APIRouter(prefix='/api/sessions')

def completed_view(view,db,session_id,user_id,background_tasks):
    item=owned(db,session_id,user_id,True)
    try:queue_communication(db,item,background_tasks,all_pending=view['finalised'])
    except Exception as exc:
        db.rollback();logging.getLogger(__name__).warning('Communication scheduling paused (%s)',type(exc).__name__)
    if view['finalised']:
        try:queue_report(db,owned(db,session_id,user_id,True),background_tasks)
        except Exception as exc:
            db.rollback()
            logging.getLogger(__name__).warning('Report scheduling paused (%s)',type(exc).__name__)
    try:
        if view['coverage']['answered']>=8:queue_archive(db,owned(db,session_id,user_id,True),background_tasks)
    except Exception as exc:
        db.rollback();logging.getLogger(__name__).info('Archive scheduling deferred (%s)',type(exc).__name__)
    return view


async def advance_response(db,session_id,user_id,background_tasks):
    try:return completed_view(await advance(db,session_id,user_id),db,session_id,user_id,background_tasks)
    except HTTPException as exc:
        # Saved delivery work still runs when content processing needs a retry.
        try:queue_communication(db,owned(db,session_id,user_id,True),background_tasks)
        except Exception:db.rollback()
        return JSONResponse(status_code=exc.status_code,content={'detail':exc.detail},background=background_tasks)

@router.get('/{session_id}/interview')
def view(session_id:UUID,identity:Identity=Depends(current_identity),db:Session=Depends(get_db)):
    return public_view(db,owned(db,session_id,identity.user_id))

@router.post('/{session_id}/interview/start')
async def begin(session_id:UUID,background_tasks:BackgroundTasks,identity:Identity=Depends(current_identity),db:Session=Depends(get_db)):
    start(db,session_id,identity.user_id)
    return await advance_response(db,session_id,identity.user_id,background_tasks)

@router.post('/{session_id}/interview/advance')
async def retry(session_id:UUID,background_tasks:BackgroundTasks,identity:Identity=Depends(current_identity),db:Session=Depends(get_db)):
    return await advance_response(db,session_id,identity.user_id,background_tasks)

@router.post('/{session_id}/interview/answer')
async def answer(session_id:UUID,body:AnswerInput,background_tasks:BackgroundTasks,identity:Identity=Depends(current_identity),db:Session=Depends(get_db)):
    replay=accept_answer(db,session_id,identity.user_id,body)
    if replay:
        return completed_view(public_view(db,owned(db,session_id,identity.user_id)),db,session_id,identity.user_id,background_tasks)
    return await advance_response(db,session_id,identity.user_id,background_tasks)

@router.post('/{session_id}/interview/turns/{turn_id}/transcribe')
async def transcribe(session_id:UUID,turn_id:UUID,request:Request,format:str=Query(pattern='^(webm|wav|mp4|m4a|ogg)$'),
                     identity:Identity=Depends(current_identity),db:Session=Depends(get_db)):
    item=owned(db,session_id,identity.user_id,True)
    level,turns=level_and_turns(db,item.id)
    turn=next((t for t in turns if t.id==turn_id),None)
    if not turn:raise HTTPException(404,'Question not found.')
    if item.status!='in_progress' or turn.status!='asked':
        raise HTTPException(409,'This question is not accepting a recording.')
    token=str(uuid4())
    turn.question_spec={**turn.question_spec,'transcription_token':token}
    db.commit()
    audio=bytearray()
    try:
        async for chunk in request.stream():
            audio.extend(chunk)
            if len(audio)>MAX_AUDIO_BYTES:
                raise HTTPException(413,'Keep your recording under 8 MB.')
        result=await transcribe_audio(bytes(audio),'answer.'+format)
        delivery=await asyncio.to_thread(measure_pauses,bytes(audio),result.get('words',[]))
        item=owned(db,session_id,identity.user_id,True)
        db.refresh(turn)
        if item.status!='in_progress' or turn.status!='asked' or turn.question_spec.get('transcription_token')!=token:
            raise HTTPException(409,'A newer recording or answer took over. Refresh this question.')
        turn.raw_transcript=result['text']
        turn.response_duration_seconds=result['duration']
        turn.question_spec={**turn.question_spec,'delivery_metrics':delivery}
        db.commit()
        return {'text':result['text']}
    except AnalysisUnavailable as exc:
        raise HTTPException(503,str(exc)) from None
    finally:
        audio.clear()

@router.post('/{session_id}/interview/end')
def end(session_id:UUID,background_tasks:BackgroundTasks,identity:Identity=Depends(current_identity),db:Session=Depends(get_db)):
    return completed_view(end_interview(db,session_id,identity.user_id),db,session_id,identity.user_id,background_tasks)

@router.post('/{session_id}/redo',response_model=SessionDetail,status_code=201)
def new_attempt(session_id:UUID,body:RedoInput,identity:Identity=Depends(current_identity),db:Session=Depends(get_db)):
    return redo(db,session_id,identity.user_id,body.request_id)
