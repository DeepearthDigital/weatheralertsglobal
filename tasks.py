#tasks.py
from celery import Celery
from dotenv import load_dotenv
import os

load_dotenv()

# Redis Cloud details from environment variables.
redis_cloud_host = os.environ.get('redis_cloud_host')
redis_cloud_port = os.environ.get('redis_cloud_port')
redis_cloud_password = os.environ.get('redis_cloud_password')
redis_cloud_db = os.environ.get('redis_cloud_db', 0)

if not all([redis_cloud_host, redis_cloud_port, redis_cloud_password]):
    raise ValueError("Redis Cloud environment variables are missing.")

try:
    redis_cloud_db = int(redis_cloud_db)
except ValueError:
    raise ValueError("redis_cloud_db must be an integer.")

# Celery configuration (NO Flask app involved here)
celery = Celery(__name__,
                broker=f'redis://:{redis_cloud_password}@{redis_cloud_host}:{redis_cloud_port}/{redis_cloud_db}',
                backend=f'redis://:{redis_cloud_password}@{redis_cloud_host}:{redis_cloud_port}/{redis_cloud_db}')

celery.conf.update(
    result_backend=f'redis://:{redis_cloud_password}@{redis_cloud_host}:{redis_cloud_port}/{redis_cloud_db}',
    task_serializer='json',
    result_serializer='json',
    accept_content=['json']
)
from main import send_alert_notification_zone_creation_email
celery.task(name='tasks.send_alert_notification_zone_creation_email')(send_alert_notification_zone_creation_email)

print(f"Redis Cloud Host: {redis_cloud_host}")
print(f"Redis Cloud Port: {redis_cloud_port}")
print(f"Redis Cloud Password: {redis_cloud_password}")
print(f"Redis Cloud DB: {redis_cloud_db}")