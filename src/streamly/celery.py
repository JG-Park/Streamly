"""
Celery 설정
"""

import os
from celery import Celery
from django.conf import settings

# Django 설정 모듈 지정
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'streamly.settings')

app = Celery('streamly')

# Django 설정에서 Celery 설정 가져오기
app.config_from_object('django.conf:settings', namespace='CELERY')

# Django 앱에서 태스크 자동 발견
app.autodiscover_tasks()

# Celery Beat 스케줄 설정
app.conf.beat_schedule = {
    'check-channels-every-minute': {
        'task': 'core.tasks.check_all_channels',
        'schedule': 60.0,  # 60초마다 실행
    },
    'process-ended-streams': {
        'task': 'core.tasks.process_ended_streams',
        'schedule': 120.0,  # 2분마다 실행
    },
    'process-pending-downloads': {
        'task': 'core.tasks.process_pending_downloads',
        'schedule': 30.0,  # 30초마다 실행 (대기 중 다운로드 처리)
    },
    'check-stuck-downloads': {
        'task': 'core.tasks.check_stuck_downloads',
        'schedule': 600.0,  # 10분마다 실행 (멈춘 다운로드 확인)
    },
    'retry-failed-stream-downloads': {
        'task': 'core.tasks.retry_failed_stream_downloads',
        'schedule': 10.0,  # 10초마다 실행 (종료 후 재시도)
    },
    'cleanup-old-downloads': {
        'task': 'core.tasks.cleanup_old_downloads',
        'schedule': 3600.0,  # 1시간마다 실행
    },
    'cleanup-old-logs': {
        'task': 'core.tasks.cleanup_old_logs',
        'schedule': 24 * 3600.0,  # 24시간마다 실행
    },
}

app.conf.timezone = 'Asia/Seoul'


@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')