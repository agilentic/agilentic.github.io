from celery import Celery
from api.app.core.config import settings

celery_app = Celery(
    "factor_discovery",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["workers.tasks.experiment_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    task_routes={
        "workers.tasks.experiment_tasks.run_experiment_task": {"queue": "experiments"},
    },
)
