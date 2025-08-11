#!/usr/bin/env python3
"""
Streamly Health Check Script
Docker 컨테이너 및 서비스 상태를 확인하는 스크립트
"""

import os
import sys
import django
import requests
from pathlib import Path

# Django 설정
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'streamly.settings')
BASE_DIR = Path(__file__).resolve().parent
sys.path.append(str(BASE_DIR))

try:
    django.setup()
    from django.db import connection
    from django.core.cache import cache
    from core.models import Settings
    from channels.models import Channel
    from downloads.models import Download
except Exception as e:
    print(f"❌ Django 초기화 실패: {e}")
    sys.exit(1)


def check_database():
    """데이터베이스 연결 확인"""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        print("✅ 데이터베이스 연결 정상")
        return True
    except Exception as e:
        print(f"❌ 데이터베이스 연결 실패: {e}")
        return False


def check_redis():
    """Redis 연결 확인"""
    try:
        cache.set('health_check', 'ok', 10)
        result = cache.get('health_check')
        if result == 'ok':
            print("✅ Redis 연결 정상")
            return True
        else:
            print("❌ Redis 연결 실패: 값 확인 실패")
            return False
    except Exception as e:
        print(f"❌ Redis 연결 실패: {e}")
        return False


def check_web_server():
    """웹 서버 응답 확인"""
    try:
        response = requests.get('http://localhost:40732/health/', timeout=10)
        if response.status_code == 200:
            print("✅ 웹 서버 응답 정상")
            return True
        else:
            print(f"❌ 웹 서버 응답 실패: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ 웹 서버 연결 실패: {e}")
        return False


def check_models():
    """모델 및 데이터 확인"""
    try:
        channel_count = Channel.objects.count()
        download_count = Download.objects.count()
        print(f"✅ 모델 접근 정상 (채널: {channel_count}, 다운로드: {download_count})")
        return True
    except Exception as e:
        print(f"❌ 모델 접근 실패: {e}")
        return False


def check_directories():
    """필요한 디렉토리 확인"""
    required_dirs = [
        os.environ.get('DOWNLOAD_PATH', './downloads'),
        os.environ.get('MEDIA_ROOT', './media'),
        './logs'
    ]
    
    all_good = True
    for dir_path in required_dirs:
        path = Path(dir_path)
        if path.exists() and path.is_dir():
            print(f"✅ 디렉토리 존재: {dir_path}")
        else:
            print(f"❌ 디렉토리 없음: {dir_path}")
            all_good = False
    
    return all_good


def main():
    """메인 헬스 체크"""
    print("🔍 Streamly 헬스 체크 시작\n")
    
    checks = [
        ("데이터베이스", check_database),
        ("Redis", check_redis),
        ("웹 서버", check_web_server),
        ("모델", check_models),
        ("디렉토리", check_directories),
    ]
    
    results = []
    for name, check_func in checks:
        print(f"📋 {name} 확인 중...")
        result = check_func()
        results.append(result)
        print()
    
    success_count = sum(results)
    total_count = len(results)
    
    print("=" * 50)
    print(f"📊 헬스 체크 결과: {success_count}/{total_count}")
    
    if success_count == total_count:
        print("🎉 모든 서비스가 정상 작동 중입니다!")
        return 0
    else:
        print("⚠️  일부 서비스에 문제가 있습니다.")
        return 1


if __name__ == "__main__":
    sys.exit(main())