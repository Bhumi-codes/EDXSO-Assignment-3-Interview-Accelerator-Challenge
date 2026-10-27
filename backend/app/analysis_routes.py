from datetime import datetime,timezone,timedelta
from uuid import UUID,uuid4
from fastapi import APIRouter,Depends,HTTPException,Request,Query
from sqlalchemy import select,delete
from sqlalchemy.orm import Session
from .auth import current_identity,Identity
from .database import get_db
from .models import InterviewSession,SessionRequirement,RequirementMatch
from .analysis_schemas import DocumentsInput
from .schemas import SessionDetail
from .documents import extract_document,MAX_BYTES
from .analysis import analyse_documents
from .llm import AnalysisUnavailable
from .config import get_settings

router=APIRouter(prefix='/api')

def owned(db,session_id,user_id,lock=False):
    query=select(InterviewSession).where(InterviewSession.id==session_id,InterviewSession.user_id==user_id)
    item=db.scalar(query.with_for_update() if lock else query)
    if not item:
        raise HTTPException(404,'Session not found.')
    return item

@router.post('/documents/extract')
async def extract(request:Request,filename:str=Query(max_length=200),kind:str=Query(pattern='^(jd|resume)$'),
                  identity:Identity=Depends(current_identity)):
    # Raw bounded bytes avoid multipart framework disk spooling.
    data=bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data)>MAX_BYTES:
            raise HTTPException(413,'Choose a file smaller than 5 MB.')
    return {'text':extract_document(bytes(data),filename,10000 if kind=='jd' else 14000)}

@router.post('/sessions/{session_id}/documents',response_model=SessionDetail)
def save_documents(session_id:UUID,body:DocumentsInput,identity:Identity=Depends(current_identity),db:Session=Depends(get_db)):
    item=owned(db,session_id,identity.user_id,True)
    if item.status!='draft':
        raise HTTPException(409,'These snapshots are locked. Use a new draft for changed documents.')
    jd,resume=body.jd_text.strip(),body.resume_text.strip()
    if min(len(jd),len(resume))<20 or '\x00' in jd+resume:
        raise HTTPException(422,'Provide at least 20 readable characters in each document.')
    item.jd_text=jd
    item.resume_text=resume
    item.input_metadata={'jd':{'method':'upload' if body.jd_filename else 'paste','filename':body.jd_filename},
                         'resume':{'method':'upload' if body.resume_filename else 'paste','filename':body.resume_filename}}
    item.processing_metadata={}
    db.commit();db.refresh(item)
    return item

@router.post('/sessions/{session_id}/analyse',response_model=SessionDetail)
async def analyse(session_id:UUID,identity:Identity=Depends(current_identity),db:Session=Depends(get_db)):
    if not get_settings().groq_api_key:
        raise HTTPException(503,'Analysis is awaiting project setup. Your saved documents are safe.')
    item=owned(db,session_id,identity.user_id,True)
    if item.status=='ready':
        return item
    now=datetime.now(timezone.utc)
    started=(item.processing_metadata or {}).get('started_at')
    if item.status=='analysing' and started and now-datetime.fromisoformat(started)<timedelta(minutes=10):
        raise HTTPException(409,'Analysis is already processing. Refresh shortly; a stalled request can be retried after 10 minutes.')
    if item.status not in ('draft','analysing'):
        raise HTTPException(409,'This attempt cannot be reanalysed.')
    if min(len(item.jd_text),len(item.resume_text))<20:
        raise HTTPException(422,'Save and review both documents before analysis.')
    token=str(uuid4())
    item.status='analysing'
    item.processing_metadata={'token':token,'started_at':now.isoformat()}
    jd,resume=item.jd_text,item.resume_text
    db.commit() # No database write transaction stays open during external calls.
    try:
        role,candidate,fit,metadata=await analyse_documents(session_id,jd,resume)
    except Exception as exc:
        item=owned(db,session_id,identity.user_id,True)
        if item.processing_metadata.get('token')==token:
            item.status='draft'
            item.processing_metadata={'error':'analysis_failed'}
            db.commit()
        message=str(exc) if isinstance(exc,AnalysisUnavailable) else 'Analysis failed safely. Your documents are saved; retry shortly.'
        raise HTTPException(503,message) from None
    item=owned(db,session_id,identity.user_id,True)
    if item.processing_metadata.get('token')!=token:
        raise HTTPException(409,'A newer analysis request took over. Refresh the session.')
    db.execute(delete(SessionRequirement).where(SessionRequirement.session_id==session_id))
    for requirement in fit['requirements']:
        req_id=UUID(requirement['id'])
        db.add(SessionRequirement(id=req_id,session_id=session_id,key=requirement['key'],
            label=requirement['label'],category=requirement['category'],importance=requirement['importance'],
            origin=requirement['origin'],evidence=requirement['evidence'],scoring_weight=requirement['weight'],
            include_in_fit=requirement['include_in_fit']))
        db.flush()
        match=next(m for m in fit['matches'] if m['requirement_key']==requirement['key'])
        db.add(RequirementMatch(requirement_id=req_id,match_status=match['status'],
            resume_evidence=match['resume_evidence'],reason=match['reason'],
            preparation_note=match['preparation_note'],probe_target=match['probe_target']))
    item.role_profile=role
    item.candidate_profile=candidate
    item.fit_summary=fit
    item.job_fit_score=fit['score']
    item.configuration={**item.configuration,'analysis':metadata}
    item.processing_metadata={}
    item.status='ready'
    db.commit();db.refresh(item)
    return item
