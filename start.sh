#!/bin/bash

# Streamly 시작 스크립트
set -e

echo "🎬 Streamly 시작 중..."

# 환경 변수 확인
if [ ! -f .env ]; then
    echo "⚠️  .env 파일이 없습니다. .env.example을 복사하여 .env 파일을 생성하세요."
    echo "   cp .env.example .env"
    echo "   그 후 .env 파일을 수정하여 필요한 설정을 입력하세요."
    exit 1
fi

# Docker Compose 프로필 확인
PROFILE=${1:-production}

if [ "$PROFILE" = "dev" ]; then
    echo "🔧 개발 모드로 시작합니다..."
    docker-compose -f docker-compose.dev.yml down --remove-orphans
    docker-compose -f docker-compose.dev.yml up --build
elif [ "$PROFILE" = "production" ]; then
    echo "🚀 프로덕션 모드로 시작합니다..."
    docker-compose down --remove-orphans
    docker-compose up --build -d
    
    echo ""
    echo "✅ Streamly가 성공적으로 시작되었습니다!"
    echo "   📱 관리자 페이지: http://192.168.0.10:40732/admin/"
    echo "   🌐 대시보드: http://192.168.0.10:40732/dashboard/"
    echo "   📊 API 문서: http://192.168.0.10:40732/api/"
    echo ""
    echo "📋 서비스 상태 확인:"
    docker-compose ps
    echo ""
    echo "📊 로그 확인: docker-compose logs -f"
    echo "🛑 서비스 중지: docker-compose down"
else
    echo "❌ 잘못된 프로필입니다. 'dev' 또는 'production'을 사용하세요."
    echo "   사용법: $0 [dev|production]"
    exit 1
fi