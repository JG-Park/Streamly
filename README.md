# 🎬 Streamly - YouTube Live Stream Monitor & Auto-Download System

Streamly는 특정 YouTube 채널을 모니터링하여 라이브 스트림 시작을 감지하고, 종료 후 자동으로 다운로드하는 시스템입니다.

## ✨ 주요 기능

- 🔍 **실시간 모니터링**: 등록된 YouTube 채널을 1분 간격으로 확인
- 📢 **즉시 알림**: 라이브 시작/종료 시 텔레그램 알림 발송
- 💾 **자동 다운로드**: 라이브 종료 후 저화질/고화질 병렬 다운로드
- 🗂️ **자동 정리**: 설정 가능한 보관 기간 후 자동 파일 삭제
- 📊 **관리 대시보드**: 웹 인터페이스로 모든 기능 관리
- 🔧 **REST API**: 외부 시스템과의 연동 지원

## 🛠 기술 스택

- **Backend**: Django 5.2 + Django REST Framework
- **Task Queue**: Celery + Redis
- **Database**: PostgreSQL (개발 시 SQLite)
- **Download Engine**: yt-dlp
- **Notification**: Telegram Bot API
- **Frontend**: Bootstrap 5 + Django Templates

## 🚀 빠른 시작

### 1. 저장소 클론 및 환경 설정

```bash
git clone <repository-url>
cd Streamly
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. 환경 변수 설정

```bash
cp .env.example .env
```

`.env` 파일을 편집하여 다음 설정을 입력하세요:

```env
# Django 설정
DEBUG=True
SECRET_KEY=your-secret-key-here
ALLOWED_HOSTS=localhost,127.0.0.1,your-domain.com

# 데이터베이스 (개발용 SQLite)
DATABASE_URL=sqlite:///db.sqlite3

# Redis (Celery용)
REDIS_URL=redis://localhost:6379/0

# 텔레그램 봇 설정
TELEGRAM_BOT_TOKEN=your-bot-token-here
TELEGRAM_CHAT_ID=your-chat-id-here

# 파일 저장 경로
DOWNLOAD_PATH=./downloads
RETENTION_DAYS=14
```

### 3. 데이터베이스 설정

```bash
python manage.py migrate
python manage.py createsuperuser
```

### 4. 서버 실행

```bash
# Django 개발 서버
python manage.py runserver 0.0.0.0:40732

# 별도 터미널에서 Celery Worker 실행
celery -A streamly worker -l info

# 별도 터미널에서 Celery Beat 실행 (스케줄러)
celery -A streamly beat -l info
```

## 📱 사용 방법

### 1. 관리자 로그인
- http://localhost:40732/admin/ 접속
- 생성한 슈퍼유저로 로그인

### 2. 채널 등록
- 채널 관리 메뉴에서 YouTube 채널 URL 입력
- 지원되는 URL 형식:
  - `https://www.youtube.com/@channelname`
  - `https://www.youtube.com/channel/UCxxxxxxxxxx`
  - `https://www.youtube.com/c/channelname`

### 3. 텔레그램 봇 설정
- [@BotFather](https://t.me/BotFather)에서 봇 생성
- 봇 토큰과 채팅 ID를 설정에서 입력
- 설정 → 텔레그램 설정에서 테스트 메시지 전송으로 연결 확인

### 4. 시스템 모니터링
- 대시보드에서 실시간 상태 확인
- 시스템 로그에서 동작 상태 모니터링
- 다운로드 목록에서 파일 관리

## 🔧 API 사용법

### 인증
모든 API 엔드포인트는 Django 세션 인증이 필요합니다.

### 주요 엔드포인트

```bash
# 채널 목록 조회
GET /api/channels/

# 새 채널 추가
POST /api/channels/
{
    "url": "https://www.youtube.com/@channelname"
}

# 채널 활성/비활성 토글
POST /api/channels/{id}/toggle_active/

# 라이브 스트림 목록
GET /api/live-streams/

# 다운로드 목록
GET /api/downloads/

# 대시보드 통계
GET /api/dashboard/

# 텔레그램 테스트
POST /api/telegram/test/
{
    "message": "테스트 메시지"
}
```

## 📂 프로젝트 구조

```
streamly/
├── manage.py
├── requirements.txt
├── .env.example
├── streamly/           # Django 설정
│   ├── settings.py
│   ├── urls.py
│   └── celery.py
├── core/              # 핵심 로직
│   ├── models.py      # Settings, SystemLog
│   ├── utils.py       # YouTube API, 유틸리티
│   ├── services.py    # 비즈니스 로직
│   ├── tasks.py       # Celery 태스크
│   └── views.py       # 대시보드 뷰
├── channels/          # 채널 관리
│   ├── models.py      # Channel, LiveStream
│   └── admin.py
├── downloads/         # 다운로드 관리
│   ├── models.py      # Download
│   └── admin.py
├── api/              # REST API
│   ├── views.py
│   ├── serializers.py
│   └── urls.py
└── templates/        # HTML 템플릿
    ├── base.html
    └── admin/
        └── dashboard.html
```

## ⚙️ Celery 태스크

### 주요 태스크
- `check_all_channels`: 모든 활성 채널 확인 (1분마다)
- `process_ended_streams`: 종료된 라이브 스트림 처리 (2분마다)
- `download_video`: 개별 비디오 다운로드
- `cleanup_old_downloads`: 오래된 파일 정리 (1시간마다)
- `send_live_notification`: 라이브 시작 알림
- `send_download_notification`: 다운로드 완료 알림

### 수동 태스크 실행
```bash
# 채널 확인 실행
python manage.py shell -c "from core.tasks import check_all_channels; check_all_channels.delay()"

# 파일 정리 실행
python manage.py shell -c "from core.tasks import cleanup_old_downloads; cleanup_old_downloads.delay()"
```

## 🧪 테스트

```bash
# 전체 테스트 실행
python manage.py test

# 특정 앱 테스트
python manage.py test core

# 커버리지와 함께 실행 (pytest 사용)
pytest --cov=.
```

## 🚀 프로덕션 배포

### 1. 환경 설정
```bash
DEBUG=False
SECRET_KEY=strong-production-key
DATABASE_URL=postgresql://user:pass@localhost/streamly
```

### 2. 웹 서버 설정 (Nginx + Gunicorn)
```bash
# Gunicorn 실행
gunicorn streamly.wsgi:application --bind 0.0.0.0:8000 --workers 3

# systemd 서비스 등록
sudo systemctl enable streamly
sudo systemctl start streamly
```

### 3. Celery 서비스 설정
```bash
# Celery Worker
celery -A streamly worker --loglevel=info --concurrency=4

# Celery Beat
celery -A streamly beat --loglevel=info
```

## 🔧 관리 도구

### Adminer (데이터베이스 관리)
Docker Compose로 실행 시 Adminer가 함께 실행됩니다.

- **접속 주소**: http://localhost:40732/adminer/
- **서버**: `db` (Docker 내부) 또는 `localhost` (로컬)
- **사용자명**: `streamly`
- **비밀번호**: `streamly123`
- **데이터베이스**: `streamly`

## 🔒 보안 고려사항

- Django의 기본 보안 설정 활용
- 환경 변수로 민감 정보 관리
- CSRF 보호 활성화
- 파일 경로 안전성 검증
- API 인증 필수
- Adminer는 프로덕션에서 비활성화 권장

## 📋 요구사항

- Python 3.8+
- Redis Server
- PostgreSQL (프로덕션)
- 충분한 디스크 공간 (다운로드 파일용)

## 🔄 백업 및 복구

### 데이터베이스 백업
```bash
# SQLite
cp db.sqlite3 db_backup_$(date +%Y%m%d).sqlite3

# PostgreSQL
pg_dump streamly > streamly_backup_$(date +%Y%m%d).sql
```

### 다운로드 파일 백업
```bash
tar -czf downloads_backup_$(date +%Y%m%d).tar.gz downloads/
```

## 📞 지원 및 문의

이슈나 기능 요청은 GitHub Issues를 통해 제출해주세요.

## 📄 라이선스

This project is licensed under the MIT License.

---

**Streamly** - 개인 사용을 위한 YouTube 라이브 스트림 모니터링 및 자동 다운로드 시스템