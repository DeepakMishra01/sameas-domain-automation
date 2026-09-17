"""Celery application for asynchronous domain observation.

The broker/result backend are read from settings. Constructing the app does not
open a connection; the observation logic itself lives in
``domain_resolver.observation.service`` and is broker-independent, so it is fully
testable without a running broker.
"""

from __future__ import annotations

from celery import Celery

from domain_resolver.config.settings import get_settings


def create_celery_app() -> Celery:
    settings = get_settings()
    app = Celery(
        "dere",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
        include=[
            "apps.worker.tasks.observe",
            "apps.worker.tasks.extract",
            "apps.worker.tasks.match",
        ],
    )
    app.conf.update(
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        task_track_started=True,
        worker_prefetch_multiplier=1,
        task_default_retry_delay=30,
        task_max_retries=3,
    )
    return app


celery_app = create_celery_app()
