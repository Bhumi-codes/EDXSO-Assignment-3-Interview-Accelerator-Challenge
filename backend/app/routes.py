from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from .auth import Identity, current_identity
from .database import get_db
from .models import InterviewSession, Profile
from .schemas import SessionCreate, SessionDetail, SessionSummary

router = APIRouter(prefix='/api')

@router.get('/me')
def me(identity: Identity = Depends(current_identity)):
    return identity

@router.get('/sessions', response_model=list[SessionSummary])
def list_sessions(identity: Identity = Depends(current_identity), db: Session = Depends(get_db)):
    return db.scalars(select(InterviewSession).where(InterviewSession.user_id == identity.user_id)
                      .order_by(InterviewSession.created_at.desc()).limit(100)).all()

@router.post('/sessions', response_model=SessionDetail, status_code=201)
def create_session(body: SessionCreate, identity: Identity = Depends(current_identity), db: Session = Depends(get_db)):
    db.execute(insert(Profile).values(user_id=identity.user_id, display_name=identity.display_name)
               .on_conflict_do_nothing(index_elements=[Profile.user_id]))
    attempt = InterviewSession(user_id=identity.user_id, title=body.title)
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return attempt

@router.get('/sessions/{session_id}', response_model=SessionDetail)
def get_session(session_id: UUID, identity: Identity = Depends(current_identity), db: Session = Depends(get_db)):
    attempt = db.scalar(select(InterviewSession).where(
        InterviewSession.id == session_id, InterviewSession.user_id == identity.user_id))
    if attempt is None:
        raise HTTPException(404, 'Session not found.')
    return attempt
