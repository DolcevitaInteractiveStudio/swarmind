import os
from celery import Celery

redis_url = os.environ.get('CELERY_BROKER_URL',
            os.environ.get('REDIS_URL', 'redis://redis:6379/0'))

celery_app = Celery(
    'swarmind',
    broker=redis_url,
    backend=redis_url,
    include=['app.simulation.tasks'],
)

celery_app.conf.update(
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],
    task_track_started=True,
    broker_connection_retry_on_startup=True,
)

from app import create_app
flask_app = create_app()
flask_app.app_context().push()
