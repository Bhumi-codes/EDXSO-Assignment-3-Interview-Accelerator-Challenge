from uuid import UUID
from fastapi import APIRouter,Depends,Response,BackgroundTasks
import re
from .report_pdf import render_report_pdf
from sqlalchemy.orm import Session
from .auth import current_identity,Identity
from .database import get_db
from .report_service import final_owned,public_report,generate_report,recover_evaluation,update_communication,queue_report

router=APIRouter(prefix='/api/sessions')
@router.get('/{session_id}/report')
def read(session_id:UUID,identity:Identity=Depends(current_identity),db:Session=Depends(get_db)):
    return public_report(db,final_owned(db,session_id,identity.user_id))

@router.post('/{session_id}/report/ensure')
def ensure(session_id:UUID,background_tasks:BackgroundTasks,identity:Identity=Depends(current_identity),db:Session=Depends(get_db)):
    item=final_owned(db,session_id,identity.user_id,True)
    queue_report(db,item,background_tasks)
    return public_report(db,item)

@router.post('/{session_id}/report')
async def generate(session_id:UUID,identity:Identity=Depends(current_identity),db:Session=Depends(get_db)):
    return await generate_report(db,session_id,identity.user_id)

@router.post('/{session_id}/report/recover-evaluation')
async def recover(session_id:UUID,background_tasks:BackgroundTasks,identity:Identity=Depends(current_identity),db:Session=Depends(get_db)):
    await recover_evaluation(db,session_id,identity.user_id)
    item=final_owned(db,session_id,identity.user_id,True);queue_report(db,item,background_tasks)
    return public_report(db,item)

@router.post('/{session_id}/report/communication')
async def communication(session_id:UUID,background_tasks:BackgroundTasks,identity:Identity=Depends(current_identity),db:Session=Depends(get_db)):
    await update_communication(db,session_id,identity.user_id)
    item=final_owned(db,session_id,identity.user_id,True);queue_report(db,item,background_tasks)
    return public_report(db,item)

@router.get('/{session_id}/report/pdf')
def pdf(session_id:UUID,identity:Identity=Depends(current_identity),db:Session=Depends(get_db)):
    item=final_owned(db,session_id,identity.user_id)
    report=public_report(db,item)
    name=re.sub(r'[^a-zA-Z0-9_-]+','-',item.title).strip('-')[:70] or 'interview'
    return Response(render_report_pdf(report),media_type='application/pdf',headers={
        'Content-Disposition':f'attachment; filename="{name}-report.pdf"',
        'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})
