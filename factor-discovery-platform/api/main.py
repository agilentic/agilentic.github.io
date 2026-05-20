from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from api.app.core.config import settings
from api.app.core.database import engine, Base


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        from api.app.core.redis_client import get_redis
        r = get_redis()
        await r.ping()
    except Exception:
        pass
    yield


app = FastAPI(
    title="Factor Discovery Platform API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from api.app.api.routers import datasets, experiments, features, portfolio

app.include_router(datasets.router, prefix="/api/v1")
app.include_router(experiments.router, prefix="/api/v1")
app.include_router(features.router, prefix="/api/v1")
app.include_router(portfolio.router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok"}
