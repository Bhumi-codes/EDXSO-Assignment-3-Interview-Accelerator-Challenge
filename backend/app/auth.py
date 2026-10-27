from uuid import UUID
import httpx
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from .config import get_settings

bearer = HTTPBearer(auto_error=False)

class Identity(BaseModel):
    user_id: UUID
    display_name: str

async def current_identity(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> Identity:
    if not credentials or credentials.scheme.lower() != 'bearer':
        raise HTTPException(401, 'Sign in to continue.', headers={'WWW-Authenticate': 'Bearer'})
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_publishable_key:
        raise HTTPException(503, 'Sign-in setup is required. See docs/SETUP.md.')
    # Auth verifies the token; never trust a decoded, unverified JWT or browser owner ID.
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
            result = await client.get(f'{settings.supabase_url}/auth/v1/user', headers={
                'apikey': settings.supabase_publishable_key.get_secret_value(),
                'Authorization': f'Bearer {credentials.credentials}'})
    except httpx.HTTPError:
        raise HTTPException(503, 'Sign-in verification is temporarily unavailable.') from None
    if result.status_code in (401, 403):
        raise HTTPException(401, 'Your sign-in has expired. Please sign in again.')
    if result.status_code != 200:
        raise HTTPException(503, 'Sign-in verification is temporarily unavailable.')
    try:
        user = result.json()
        if user.get('is_anonymous') or user.get('role') != 'authenticated':
            raise ValueError('Not authenticated')
        return Identity(user_id=UUID(user['id']), display_name=str(
            user.get('user_metadata', {}).get('full_name') or 'Candidate')[:200])
    except (KeyError, ValueError, TypeError):
        raise HTTPException(401, 'Unable to verify your account.') from None
