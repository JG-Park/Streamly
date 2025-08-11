#!/bin/bash

# Nginx 로컬 실행 스크립트

echo "Streamly Nginx Proxy 시작 스크립트"
echo "================================="

# nginx 설치 확인
if ! command -v nginx &> /dev/null; then
    echo "❌ nginx가 설치되지 않았습니다."
    echo "   macOS: brew install nginx"
    echo "   Ubuntu: sudo apt-get install nginx"
    exit 1
fi

# Django 서버 실행 확인
if ! curl -s http://localhost:40732/health > /dev/null 2>&1; then
    echo "⚠️  Django 서버가 40732 포트에서 실행되고 있지 않습니다."
    echo "   먼저 Django 서버를 시작하세요:"
    echo "   python3 manage.py runserver 0.0.0.0:40732"
    exit 1
fi

# 기존 nginx 프로세스 종료
echo "기존 nginx 프로세스 확인 중..."
if pgrep nginx > /dev/null; then
    echo "기존 nginx 프로세스를 종료합니다..."
    sudo nginx -s quit 2>/dev/null || sudo killall nginx 2>/dev/null
    sleep 2
fi

# 로그 디렉토리 생성
LOG_DIR="/usr/local/var/log/nginx"
if [ ! -d "$LOG_DIR" ]; then
    echo "로그 디렉토리 생성: $LOG_DIR"
    sudo mkdir -p $LOG_DIR
fi

# nginx 설정 테스트
echo "nginx 설정 테스트 중..."
sudo nginx -t -c $(pwd)/nginx-local.conf
if [ $? -ne 0 ]; then
    echo "❌ nginx 설정에 오류가 있습니다."
    exit 1
fi

# nginx 시작
echo "nginx를 시작합니다..."
sudo nginx -c $(pwd)/nginx-local.conf

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Nginx가 성공적으로 시작되었습니다!"
    echo ""
    echo "접속 URL:"
    echo "  - http://localhost (80번 포트)"
    echo "  - http://127.0.0.1 (80번 포트)"
    echo ""
    echo "프록시 대상:"
    echo "  - Django: http://localhost:40732"
    echo ""
    echo "로그 위치:"
    echo "  - Access: $LOG_DIR/streamly-access.log"
    echo "  - Error: $LOG_DIR/streamly-error.log"
    echo ""
    echo "nginx 종료:"
    echo "  sudo nginx -s quit"
    echo ""
    
    # 연결 테스트
    echo "연결 테스트 중..."
    sleep 2
    if curl -s http://localhost/health > /dev/null 2>&1; then
        echo "✅ 프록시 연결 성공!"
    else
        echo "⚠️  프록시 연결 실패. 로그를 확인하세요."
    fi
else
    echo "❌ nginx 시작 실패"
    exit 1
fi