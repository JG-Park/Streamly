#!/bin/bash

# Celery 시작 스크립트

echo "Starting Celery Worker and Beat..."

# 기존 Celery 프로세스 종료
pkill -f "celery worker"
pkill -f "celery beat"

# Redis 확인
redis-cli ping > /dev/null 2>&1
if [ $? -ne 0 ]; then
    echo "Redis is not running. Starting Redis..."
    redis-server --daemonize yes
    sleep 2
fi

# Celery Worker 시작 (백그라운드)
echo "Starting Celery Worker..."
celery -A streamly worker -l info --detach \
    --pidfile=/tmp/celery-worker.pid \
    --logfile=/tmp/celery-worker.log

# Celery Beat 시작 (백그라운드)
echo "Starting Celery Beat..."
celery -A streamly beat -l info --detach \
    --pidfile=/tmp/celery-beat.pid \
    --logfile=/tmp/celery-beat.log \
    --scheduler django_celery_beat.schedulers:DatabaseScheduler

echo "Celery services started!"
echo ""
echo "Logs:"
echo "  Worker: /tmp/celery-worker.log"
echo "  Beat: /tmp/celery-beat.log"
echo ""
echo "To stop:"
echo "  pkill -f 'celery worker'"
echo "  pkill -f 'celery beat'"