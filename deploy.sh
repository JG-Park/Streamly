#!/bin/bash
# Streamly 배포 스크립트

echo "🚀 Streamly 배포 시작..."

# Git 최신 코드 가져오기
echo "📥 최신 코드 가져오는 중..."
git pull origin main

# 필요한 디렉토리 생성
echo "📁 디렉토리 생성 중..."
mkdir -p static_collected
mkdir -p downloads_files
mkdir -p media
mkdir -p logs

# 권한 설정
chmod 755 static_collected
chmod 755 downloads_files
chmod 755 media
chmod 755 logs

# Docker 이미지 빌드
echo "🔨 Docker 이미지 빌드 중..."
docker-compose build

# 기존 컨테이너 중지 및 제거
echo "🛑 기존 컨테이너 중지 중..."
docker-compose down

# 컨테이너 시작
echo "🚀 컨테이너 시작 중..."
docker-compose up -d

# 잠시 대기 (DB 연결 대기)
echo "⏳ 서비스 초기화 대기 중..."
sleep 10

# Static 파일 수집 (강제 실행)
echo "📦 Static 파일 수집 중..."
docker-compose exec -T web python /app/src/manage.py collectstatic --noinput --clear

# nginx 재시작
echo "🔄 Nginx 재시작 중..."
docker-compose restart nginx

# 상태 확인
echo "✅ 배포 완료! 서비스 상태:"
docker-compose ps

echo ""
echo "📌 다음 URL에서 서비스를 확인할 수 있습니다:"
echo "   https://streamly.jgplabs.kr"
echo ""
echo "🔍 로그 확인:"
echo "   docker-compose logs -f web"
echo "   docker-compose logs -f celery_worker"