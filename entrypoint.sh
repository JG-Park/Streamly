#!/bin/bash
set -e

# Django 설정 모듈 명시적 설정
export DJANGO_SETTINGS_MODULE=streamly.settings
export PYTHONPATH=/app/src:$PYTHONPATH

# 작업 디렉토리 변경
cd /app/src

echo "Waiting for database..."
until nc -z db 5432; do
  echo "Database is unavailable - sleeping"
  sleep 1
done
echo "Database is up - executing command"

echo "Running migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput --clear

echo "Creating superuser..."
python manage.py shell -c "
from django.contrib.auth.models import User;
User.objects.filter(username='admin').exists() or \
User.objects.create_superuser('admin', 'admin@streamly.local', 'streamly123')
" || echo "Superuser creation skipped or failed"

echo "Starting application..."
exec "$@"