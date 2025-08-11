# Streamly 배포 가이드

## 🚀 배포 방식

### 1. Docker Compose (권장)
전체 시스템을 Docker 컨테이너로 실행합니다.

```bash
# 환경 변수 설정
cp .env.example .env
# .env 파일 편집하여 필요한 값 설정

# Docker Compose로 시작
docker-compose up -d

# 로그 확인
docker-compose logs -f
```

서비스 접속:
- **웹 인터페이스**: http://localhost (nginx가 80 포트로 프록시)
- **Django 직접 접속**: http://localhost:40732

### 2. 로컬 개발 환경

#### Django 서버 실행
```bash
# 가상환경 활성화
python3 -m venv venv
source venv/bin/activate

# 의존성 설치
pip install -r requirements.txt

# 데이터베이스 마이그레이션
python manage.py migrate

# 정적 파일 수집
python manage.py collectstatic --noinput

# 서버 실행
python manage.py runserver 0.0.0.0:40732
```

#### Celery 실행
```bash
# Celery Worker와 Beat 시작
./start_celery.sh

# 또는 개별 실행
celery -A streamly worker -l info
celery -A streamly beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

#### Nginx 프록시 (선택사항)
```bash
# 로컬 nginx 실행 (80 → 40732 프록시)
./start_nginx.sh

# nginx 종료
sudo nginx -s quit
```

## 🔧 포트 구성

| 서비스 | 포트 | 설명 |
|--------|------|------|
| Nginx | 80 | 메인 웹 서버 (프록시) |
| Django | 40732 | 애플리케이션 서버 |
| PostgreSQL | 5432 | 데이터베이스 (Docker 내부) |
| Redis | 6379 | 캐시 및 Celery 브로커 (Docker 내부) |

## 📁 디렉토리 구조

```
/app/downloads/     # 다운로드된 영상 저장
  ├── best/        # 고화질 영상
  └── worst/       # 저화질 영상
/app/media/        # 미디어 파일
/app/static/       # 정적 파일
/app/logs/         # 로그 파일
```

## 🔐 환경 변수

필수 환경 변수:
- `SECRET_KEY`: Django 시크릿 키
- `DATABASE_URL`: PostgreSQL 연결 URL
- `TELEGRAM_BOT_TOKEN`: 텔레그램 봇 토큰
- `TELEGRAM_CHAT_ID`: 텔레그램 채팅 ID
- `YOUTUBE_API_KEY`: YouTube Data API 키 (선택사항, yt-dlp 백업 있음)

## 🌐 Nginx 설정

### Docker 환경
`nginx.conf` 파일이 자동으로 사용됩니다:
- 80 포트로 들어오는 요청을 `web:40732`로 프록시
- 정적 파일 서빙
- Rate limiting 적용
- 보안 헤더 설정

### 로컬 환경
`nginx-local.conf` 사용:
- 80 포트로 들어오는 요청을 `127.0.0.1:40732`로 프록시
- 로컬 정적 파일 경로 사용

## 📊 모니터링

### 헬스 체크
```bash
curl http://localhost/health
```

### 로그 확인
```bash
# Docker 로그
docker-compose logs -f web
docker-compose logs -f celery_worker
docker-compose logs -f celery_beat

# 로컬 로그
tail -f /tmp/celery-worker.log
tail -f /tmp/celery-beat.log
```

### Celery 상태
```bash
# Flower 실행 (웹 기반 모니터링)
celery -A streamly flower
```

## 🔄 업데이트 배포

```bash
# 코드 업데이트
git pull

# Docker 이미지 재빌드
docker-compose build

# 서비스 재시작
docker-compose down
docker-compose up -d

# 마이그레이션 실행
docker-compose exec web python manage.py migrate
```

## 🚨 트러블슈팅

### Nginx 502 Bad Gateway
- Django 서버가 40732 포트에서 실행 중인지 확인
- `upstream` 설정 확인 (Docker: `web:40732`, 로컬: `127.0.0.1:40732`)

### Celery 작업이 실행되지 않음
- Redis 서버 실행 확인
- Celery Worker와 Beat 모두 실행 중인지 확인
- 데이터베이스에 PeriodicTask가 등록되어 있는지 확인

### 정적 파일 404
- `python manage.py collectstatic` 실행
- Nginx 정적 파일 경로 확인
- `STATIC_ROOT` 설정 확인