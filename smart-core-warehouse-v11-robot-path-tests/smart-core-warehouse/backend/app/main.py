from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.db import Base, engine
from app.demo.seed import ensure_seeded

settings = get_settings()
configure_logging(settings.log_level)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Local/demo usability: a fresh checkout is immediately runnable and populated.
    # Alembic remains the deployment migration path; create_all is a safe fallback for a blank demo DB.
    Base.metadata.create_all(engine)
    if settings.auto_seed_demo:
        ensure_seeded()
    yield


app = FastAPI(
    title=settings.app_name,
    version='1.1.0',
    description='Industrial Smart Core Warehouse control-system API',
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        'http://localhost:5173',
        'http://127.0.0.1:5173',
        'http://localhost:3000',
        'http://127.0.0.1:3000',
    ],
    allow_credentials=False,
    allow_methods=['*'],
    allow_headers=['*'],
)


@app.get('/', tags=['system'])
def root():
    return {
        'service': settings.app_name,
        'status': 'ok',
        'api': settings.api_prefix,
        'docs': '/docs',
        'health': '/health',
        'demo_auto_seed': settings.auto_seed_demo,
    }


@app.get('/health', tags=['system'])
def root_health():
    return {'status': 'ok', 'service': 'smart-core-warehouse'}


app.include_router(router, prefix=settings.api_prefix)
