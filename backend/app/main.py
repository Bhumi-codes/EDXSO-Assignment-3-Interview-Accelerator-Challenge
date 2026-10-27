from pathlib import Path
from contextlib import asynccontextmanager
from .provider_http import provider_lifespan
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy.exc import SQLAlchemyError
from .config import get_settings
from .routes import router

settings = get_settings()
@asynccontextmanager
async def lifespan(app):
    if settings.app_env=='production' and not (dist/'index.html').is_file():
        raise RuntimeError('Build the frontend before starting production')
    async with provider_lifespan():yield

app = FastAPI(title='Ace-it', docs_url=None, redoc_url=None,lifespan=lifespan)
if settings.app_env=='production':
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=[h.strip() for h in settings.app_allowed_hosts.split(',') if h.strip()])
app.add_middleware(CORSMiddleware, allow_origins=[settings.app_origin],
                   allow_methods=['GET','POST'], allow_headers=['Authorization','Content-Type'])
app.include_router(router)
from .analysis_routes import router as analysis_router
app.include_router(analysis_router)
from .interview_routes import router as interview_router
app.include_router(interview_router)
from .report_routes import router as report_router
app.include_router(report_router)

@app.middleware('http')
async def private_responses(request: Request, call_next):
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    if settings.app_env=='production':response.headers['Strict-Transport-Security']='max-age=15552000'
    if request.url.path.startswith('/api'):
        response.headers['Cache-Control'] = 'no-store'
    return response

@app.exception_handler(SQLAlchemyError)
async def database_error(request, error):
    return JSONResponse(status_code=503, content={'detail':
        'Session storage is unavailable. Check database setup and migrations, then retry.'})

@app.get('/api/health')
def health():
    return {'status':'ok', 'configured':settings.configured}

dist = Path(__file__).resolve().parents[2] / 'frontend' / 'dist'
if (dist / 'assets').is_dir():
    app.mount('/assets', StaticFiles(directory=dist / 'assets'), name='assets')

@app.get('/{path:path}')
def frontend(path: str):
    if path == 'api' or path.startswith(('api/', 'assets/')):
        raise HTTPException(404, 'Not found.')
    if (dist / 'index.html').is_file():
        return FileResponse(dist / 'index.html', headers={'Cache-Control':'no-cache'})
    raise HTTPException(404, 'Build the frontend or use the Vite development server.')
