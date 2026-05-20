import asyncio
import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from api.app.core.database import get_db
from api.app.core.redis_client import get_redis
from api.app.models.models import Experiment, Dataset, Subset, GenerationRecord
from api.app.schemas.schemas import ExperimentCreate, ExperimentRead, SubsetRead, GenerationRead

router = APIRouter(prefix="/experiments", tags=["experiments"])


@router.get("/", response_model=list[ExperimentRead])
async def list_experiments(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Experiment).order_by(Experiment.created_at.desc()))
    return result.scalars().all()


@router.post("/run", response_model=ExperimentRead)
async def run_experiment(data: ExperimentCreate, db: AsyncSession = Depends(get_db)):
    ds = await db.get(Dataset, data.dataset_id)
    if not ds:
        raise HTTPException(404, "Dataset not found")
    exp = Experiment(
        name=data.name,
        description=data.description,
        dataset_id=data.dataset_id,
        target_col=data.target_col,
        target_type=data.target_type,
        total_generations=data.n_generations,
        config={
            "population_size": data.population_size,
            "n_generations": data.n_generations,
            "subset_size_min": data.subset_size_min,
            "subset_size_max": data.subset_size_max,
            "objective_weights": data.objective_weights,
            "run_gp": data.run_gp,
            "run_ga": data.run_ga,
        },
        seed=data.seed,
        status="pending",
    )
    db.add(exp)
    await db.commit()
    await db.refresh(exp)
    try:
        from workers.tasks.experiment_tasks import run_experiment_task
        task = run_experiment_task.delay(exp.id)
        exp.celery_task_id = task.id
        exp.status = "running"
        await db.commit()
    except Exception:
        asyncio.create_task(_run_inline(exp.id))
        exp.status = "running"
        await db.commit()
    await db.refresh(exp)
    return exp


async def _run_inline(exp_id: str):
    from engine.agents.orchestrator import Orchestrator
    from api.app.core.database import async_session_factory
    from api.app.core.redis_client import get_redis as _get_redis
    async with async_session_factory() as db:
        exp = await db.get(Experiment, exp_id)
        if not exp:
            return
        try:
            orch = Orchestrator(experiment_id=exp_id, config=exp.config or {})
            results = await asyncio.get_event_loop().run_in_executor(None, orch.run)
            exp.status = "completed"
            exp.progress = 1.0
            exp.summary = results.get("summary", {})
            exp.completed_at = datetime.utcnow()
            await db.commit()
        except Exception as e:
            exp.status = "failed"
            exp.error_msg = str(e)[:500]
            await db.commit()


@router.get("/{exp_id}", response_model=ExperimentRead)
async def get_experiment(exp_id: str, db: AsyncSession = Depends(get_db)):
    exp = await db.get(Experiment, exp_id)
    if not exp:
        raise HTTPException(404, "Experiment not found")
    return exp


@router.post("/{exp_id}/stop", response_model=ExperimentRead)
async def stop_experiment(exp_id: str, db: AsyncSession = Depends(get_db)):
    exp = await db.get(Experiment, exp_id)
    if not exp:
        raise HTTPException(404, "Experiment not found")
    if exp.celery_task_id:
        try:
            from workers.celery_app import celery_app
            celery_app.control.revoke(exp.celery_task_id, terminate=True)
        except Exception:
            pass
    exp.status = "stopped"
    await db.commit()
    await db.refresh(exp)
    return exp


@router.get("/{exp_id}/stream")
async def stream_experiment(exp_id: str):
    redis = get_redis()
    channel = f"exp:{exp_id}:progress"

    async def event_generator():
        pubsub = redis.pubsub()
        await pubsub.subscribe(channel)
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    yield f"data: {message['data'].decode()}\n\n"
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.close()

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/{exp_id}/generations", response_model=list[GenerationRead])
async def get_generations(exp_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(GenerationRecord)
        .where(GenerationRecord.experiment_id == exp_id)
        .order_by(GenerationRecord.generation_num)
    )
    return result.scalars().all()


@router.get("/{exp_id}/subsets", response_model=list[SubsetRead])
async def get_subsets(exp_id: str, limit: int = 20, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Subset)
        .where(Subset.experiment_id == exp_id)
        .order_by(Subset.composite_score.desc())
        .limit(limit)
    )
    return result.scalars().all()


@router.get("/{exp_id}/pareto")
async def get_pareto(exp_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Subset)
        .where(Subset.experiment_id == exp_id, Subset.pareto_rank == 1)
        .order_by(Subset.composite_score.desc())
    )
    subsets = result.scalars().all()
    solutions = [
        {
            "id": s.id,
            "relevance": s.relevance_score or 0,
            "synergy": s.synergy_score or 0,
            "redundancy": s.redundancy_score or 0,
            "stability": s.stability_score or 0,
            "portfolio": s.portfolio_score or 0,
            "composite": s.composite_score or 0,
            "pareto_rank": s.pareto_rank or 1,
            "feature_names": s.feature_names or [],
        }
        for s in subsets
    ]
    return {"solutions": solutions, "synergy_matrix": {}}
