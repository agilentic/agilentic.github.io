import asyncio
import json
from datetime import datetime
from workers.celery_app import celery_app


@celery_app.task(bind=True, name="workers.tasks.experiment_tasks.run_experiment_task")
def run_experiment_task(self, experiment_id: str):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from api.app.core.config import settings
    from api.app.models.models import Experiment
    import redis

    sync_engine = create_engine(settings.sync_database_url)
    r = redis.from_url(settings.redis_url)

    def publish(data: dict):
        r.publish(f"exp:{experiment_id}:progress", json.dumps(data))

    def progress_callback(data: dict):
        publish(data)
        with Session(sync_engine) as db:
            exp = db.get(Experiment, experiment_id)
            if exp:
                exp.progress = data.get("progress", exp.progress)
                if data.get("phase") == "ga" and "generation" in data.get("message", ""):
                    try:
                        parts = data["message"].split()
                        gen_str = parts[1].split("/")[0]
                        exp.current_generation = int(gen_str)
                    except Exception:
                        pass
                db.commit()

    with Session(sync_engine) as db:
        exp = db.get(Experiment, experiment_id)
        if not exp:
            return
        exp.status = "running"
        config = exp.config or {}
        config["dataset_id"] = exp.dataset_id
        config["target_col"] = exp.target_col
        config["seed"] = exp.seed
        db.commit()

    try:
        from engine.agents.orchestrator import Orchestrator
        orch = Orchestrator(experiment_id=experiment_id, config=config, progress_callback=progress_callback)
        results = orch.run()
        with Session(sync_engine) as db:
            exp = db.get(Experiment, experiment_id)
            if exp:
                exp.status = "completed"
                exp.progress = 1.0
                exp.summary = results.get("summary", {})
                exp.completed_at = datetime.utcnow()
                db.commit()
        publish({"phase": "done", "progress": 1.0, "status": "completed"})
    except Exception as e:
        with Session(sync_engine) as db:
            exp = db.get(Experiment, experiment_id)
            if exp:
                exp.status = "failed"
                exp.error_msg = str(e)[:500]
                db.commit()
        publish({"phase": "error", "progress": 0, "status": "failed", "error": str(e)})
        raise
