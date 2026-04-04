import os
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django

django.setup()

from celery import Celery

app = Celery('autohandy')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

# Windows + prefork: billiard worker often crashes with
# ValueError: not enough values to unpack (expected 3, got 0) in celery.app.trace.fast_trace_task.
# Solo pool avoids forked children (override with: celery worker -P prefork).
if sys.platform == 'win32':
    app.conf.worker_pool = 'solo'
    app.conf.worker_concurrency = 1

import apps.order.tasks  # noqa: E402 — ensure @shared_task registration

@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
