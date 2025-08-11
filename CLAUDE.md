# CLAUDE.md

**사용자는 한국어 사용자입니다. 한국어로 대답하세요.**
**땜빵하듯이 처리하는 코딩은 절대 금기입니다. 문제 해결을 사용자가 요청하면, 관련 코드를 전부 파악해서 원인을 파악 후, 리팩토링, 중복(충돌) 제거, 불필요한 코드 소거 등의 방법으로 원론적인 해결을 해야합니다.**

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Streamly** - YouTube Live Stream Monitoring & Auto-Download System
- Monitors specific YouTube channels every minute for live streams
- Sends Telegram notifications when live streams start
- Automatically downloads streams in both low and high quality after they end
- Auto-deletes recordings after configurable period (default: 14 days)

## Tech Stack

- **Backend**: Django + Django REST Framework
- **Task Queue**: Celery + Redis
- **Database**: PostgreSQL
- **Video Download**: yt-dlp
- **Deployment**: Port 40732, behind HTTPS router
- **Domain**: streamly.jgplabs.kr

## Common Commands

### Django Development
```bash
# Create Django project structure
django-admin startproject streamly .
python manage.py startapp core
python manage.py startapp channels
python manage.py startapp downloads

# Database migrations
python manage.py makemigrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Run development server
python manage.py runserver 0.0.0.0:40732

# Run tests
python manage.py test

# Collect static files
python manage.py collectstatic --noinput
```

### Celery Commands
```bash
# Start Celery worker
celery -A streamly worker -l info

# Start Celery beat scheduler
celery -A streamly beat -l info

# Monitor Celery tasks
celery -A streamly flower
```

### Redis Commands
```bash
# Start Redis server
redis-server

# Test Redis connection
redis-cli ping
```

### yt-dlp Commands
```bash
# Download low quality
yt-dlp -f worst VIDEO_URL -o "downloads/low/%(title)s.%(ext)s"

# Download high quality
yt-dlp -f best VIDEO_URL -o "downloads/high/%(title)s.%(ext)s"

# Check if stream is live
yt-dlp --print is_live VIDEO_URL
```

## Architecture

### Django Apps Structure
- **core/**: Main app with settings, base models, and utilities
- **channels/**: YouTube channel management (CRUD, enable/disable)
- **downloads/**: Download queue management and file handling
- **api/**: REST API endpoints for admin interface

### Key Models
- `Channel`: YouTube channel info (channel_id, name, url, is_active, last_checked)
- `LiveStream`: Live stream records (channel, video_id, title, started_at, ended_at, is_downloading)
- `Download`: Download records (live_stream, quality, file_path, downloaded_at, delete_after)

### Celery Tasks
- `check_channels_task`: Runs every minute to check all active channels
- `download_stream_task`: Downloads ended streams in both qualities
- `cleanup_old_downloads_task`: Daily task to delete old recordings

### API Endpoints
- `/api/channels/` - Channel CRUD operations
- `/api/downloads/` - Download history and management
- `/api/settings/` - System settings (retention period, Telegram config)
- `/api/dashboard/` - Dashboard statistics

## Environment Variables

Create `.env` file with:
```
DEBUG=False
SECRET_KEY=your-secret-key
DATABASE_URL=postgresql://user:pass@localhost/streamly
REDIS_URL=redis://localhost:6379
TELEGRAM_BOT_TOKEN=your-bot-token
TELEGRAM_CHAT_ID=your-chat-id
DOWNLOAD_PATH=/path/to/downloads
RETENTION_DAYS=14
```

## Key Implementation Notes

1. **Live Detection**: Use yt-dlp's `is_live` property to detect live streams without downloading
2. **Parallel Downloads**: Use Celery to download low/high quality simultaneously
3. **Duplicate Prevention**: Check video_id before creating new LiveStream records
4. **Error Handling**: Implement retry logic for YouTube API rate limits
5. **File Management**: Store files in `DOWNLOAD_PATH/{quality}/{channel_name}/{timestamp}_{title}.{ext}`
6. **Telegram Integration**: Use python-telegram-bot for notifications

## Development Workflow

1. Always check for existing LiveStream records before processing
2. Use Django admin for initial testing of models
3. Implement API endpoints with proper serializers and permissions
4. Add logging for all Celery tasks
5. Use Django signals for post-download actions
6. Implement proper database indexes for channel_id and video_id lookups

## Testing Approach

```bash
# Test channel checking
python manage.py test channels.tests.test_live_detection

# Test download functionality
python manage.py test downloads.tests.test_download_task

# Test API endpoints
python manage.py test api.tests.test_endpoints

# Test Celery tasks
python manage.py test core.tests.test_celery_tasks
```

## Security Considerations

- Use Django's authentication for admin access
- Validate all YouTube URLs before processing
- Sanitize file names to prevent path traversal
- Rate limit API endpoints
- Use environment variables for all sensitive data
- Implement CORS properly for frontend access