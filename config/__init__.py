# Intentionally empty: avoid importing Celery during Django startup.
# Run: celery -A config.celery worker -l info
#      celery -A config.celery beat -l info
