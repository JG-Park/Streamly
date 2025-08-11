"""
API 백업 로직 서비스
YouTube API 호출 실패 시 yt-dlp로 자동 전환하는 스마트 백업 시스템
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Callable
from django.core.cache import cache
from django.utils import timezone
from django.conf import settings

from core.models import SystemLog

logger = logging.getLogger('streamly')


class APIBackupService:
    """API 백업 로직 관리 서비스"""
    
    # 캐시 키 상수
    CACHE_KEY_API_FAILURE_COUNT = "youtube_api_failure_count"
    CACHE_KEY_API_LAST_FAILURE = "youtube_api_last_failure"
    CACHE_KEY_API_BLOCKED_UNTIL = "youtube_api_blocked_until"
    
    # 설정 상수
    MAX_FAILURES_BEFORE_BLOCK = 5  # 5회 실패 시 일시적 차단
    BLOCK_DURATION_MINUTES = 30    # 30분간 차단
    FAILURE_RESET_HOURS = 6        # 6시간 후 실패 카운트 리셋
    
    def __init__(self):
        self.failure_count = 0
        self.last_failure_time = None
        self.blocked_until = None
        self._load_state()
    
    def _load_state(self):
        """캐시에서 상태 정보 로드"""
        try:
            self.failure_count = cache.get(self.CACHE_KEY_API_FAILURE_COUNT, 0)
            self.last_failure_time = cache.get(self.CACHE_KEY_API_LAST_FAILURE)
            self.blocked_until = cache.get(self.CACHE_KEY_API_BLOCKED_UNTIL)
        except Exception as e:
            logger.warning(f"API 백업 상태 로드 실패: {e}")
    
    def _save_state(self):
        """상태 정보를 캐시에 저장"""
        try:
            cache.set(self.CACHE_KEY_API_FAILURE_COUNT, self.failure_count, 
                     timeout=3600 * self.FAILURE_RESET_HOURS)
            if self.last_failure_time:
                cache.set(self.CACHE_KEY_API_LAST_FAILURE, self.last_failure_time,
                         timeout=3600 * self.FAILURE_RESET_HOURS)
            if self.blocked_until:
                cache.set(self.CACHE_KEY_API_BLOCKED_UNTIL, self.blocked_until,
                         timeout=self.BLOCK_DURATION_MINUTES * 60)
        except Exception as e:
            logger.warning(f"API 백업 상태 저장 실패: {e}")
    
    def is_api_blocked(self) -> bool:
        """API가 현재 차단되었는지 확인"""
        if not self.blocked_until:
            return False
        
        now = timezone.now()
        if now < self.blocked_until:
            return True
        else:
            # 차단 시간이 지났으면 상태 리셋
            self.blocked_until = None
            cache.delete(self.CACHE_KEY_API_BLOCKED_UNTIL)
            return False
    
    def should_use_backup(self) -> bool:
        """백업(yt-dlp) 사용 여부 결정"""
        # API가 차단된 상태면 백업 사용
        if self.is_api_blocked():
            return True
        
        # 실패 횟수가 임계값에 근접하면 백업 사용 확률 증가
        if self.failure_count >= 3:
            return True
        
        return False
    
    def record_api_success(self, operation: str = "unknown"):
        """API 성공 기록"""
        # 성공 시 실패 카운트 감소 (단, 0 이하로는 감소하지 않음)
        if self.failure_count > 0:
            self.failure_count = max(0, self.failure_count - 1)
            self._save_state()
            
        logger.debug(f"YouTube API 성공: {operation}, 실패 카운트: {self.failure_count}")
    
    def record_api_failure(self, operation: str = "unknown", error: Exception = None):
        """API 실패 기록"""
        now = timezone.now()
        
        # 할당량 초과 에러는 즉시 차단 처리
        error_str = str(error) if error else ""
        if 'quotaExceeded' in error_str or 'quota' in error_str.lower():
            self.failure_count = self.MAX_FAILURES_BEFORE_BLOCK
            self.blocked_until = now + timedelta(hours=24)  # 24시간 차단
            logger.warning(f"YouTube API 할당량 초과 - 24시간 차단")
            
            SystemLog.log('WARNING', 'api_backup', 
                         f"YouTube API 할당량 초과 - 24시간 차단",
                         {
                             'operation': operation,
                             'error': str(error) if error else None,
                             'blocked_until': self.blocked_until.isoformat(),
                             'block_duration_hours': 24
                         })
            self._save_state()
            return
        
        # 마지막 실패로부터 충분한 시간이 지났으면 카운트 리셋
        if (self.last_failure_time and 
            now - self.last_failure_time > timedelta(hours=self.FAILURE_RESET_HOURS)):
            self.failure_count = 0
        
        self.failure_count += 1
        self.last_failure_time = now
        
        # 실패 횟수가 임계값 이상이면 API 차단
        if self.failure_count >= self.MAX_FAILURES_BEFORE_BLOCK:
            self.blocked_until = now + timedelta(minutes=self.BLOCK_DURATION_MINUTES)
            logger.warning(f"YouTube API 일시 차단: {self.BLOCK_DURATION_MINUTES}분간 "
                          f"(실패 {self.failure_count}회)")
            
            SystemLog.log('WARNING', 'api_backup', 
                         f"YouTube API 일시 차단 ({self.failure_count}회 실패)",
                         {
                             'operation': operation,
                             'error': str(error) if error else None,
                             'blocked_until': self.blocked_until.isoformat(),
                             'block_duration_minutes': self.BLOCK_DURATION_MINUTES
                         })
        
        self._save_state()
        
        logger.warning(f"YouTube API 실패 기록: {operation}, "
                      f"실패 카운트: {self.failure_count}, 에러: {error}")
    
    def execute_with_backup(self, 
                           primary_func: Callable,
                           backup_func: Callable,
                           operation_name: str = "unknown",
                           *args, **kwargs) -> Any:
        """
        주 API 함수와 백업 함수를 실행하는 스마트 실행기
        
        Args:
            primary_func: 주 함수 (YouTube API)
            backup_func: 백업 함수 (yt-dlp)
            operation_name: 작업 이름
            *args, **kwargs: 함수에 전달할 인자들
        """
        # 먼저 백업 사용 여부 확인
        if self.should_use_backup():
            logger.info(f"백업 모드로 직접 실행: {operation_name}")
            try:
                result = backup_func(*args, **kwargs)
                # 백업 성공 시에도 상태 개선으로 기록
                if result is not None:
                    self.record_api_success(f"backup_{operation_name}")
                return result
            except Exception as e:
                logger.error(f"백업 함수 실행 실패: {operation_name}, 에러: {e}")
                return None
        
        # 주 API 시도
        try:
            start_time = time.time()
            result = primary_func(*args, **kwargs)
            execution_time = time.time() - start_time
            
            if result is not None:
                self.record_api_success(operation_name)
                logger.debug(f"주 API 성공: {operation_name} ({execution_time:.2f}초)")
                return result
            else:
                # 결과가 None이면 백업으로 전환
                logger.info(f"주 API 결과 없음, 백업으로 전환: {operation_name}")
                return self._execute_backup(backup_func, operation_name, *args, **kwargs)
                
        except Exception as e:
            # API 실패 기록
            self.record_api_failure(operation_name, e)
            
            # 백업 실행
            return self._execute_backup(backup_func, operation_name, *args, **kwargs)
    
    def _execute_backup(self, backup_func: Callable, operation_name: str, *args, **kwargs) -> Any:
        """백업 함수 실행"""
        try:
            start_time = time.time()
            result = backup_func(*args, **kwargs)
            execution_time = time.time() - start_time
            
            logger.info(f"백업 함수 성공: {operation_name} ({execution_time:.2f}초)")
            return result
            
        except Exception as e:
            logger.error(f"백업 함수도 실패: {operation_name}, 에러: {e}")
            
            SystemLog.log('ERROR', 'api_backup', 
                         f"주 API와 백업 모두 실패: {operation_name}",
                         {
                             'operation': operation_name,
                             'backup_error': str(e),
                             'failure_count': self.failure_count
                         })
            return None
    
    def get_status(self) -> Dict[str, Any]:
        """현재 백업 시스템 상태 조회"""
        return {
            'failure_count': self.failure_count,
            'is_blocked': self.is_api_blocked(),
            'blocked_until': self.blocked_until.isoformat() if self.blocked_until else None,
            'last_failure': self.last_failure_time.isoformat() if self.last_failure_time else None,
            'should_use_backup': self.should_use_backup(),
            'max_failures': self.MAX_FAILURES_BEFORE_BLOCK,
            'block_duration_minutes': self.BLOCK_DURATION_MINUTES,
            'failure_reset_hours': self.FAILURE_RESET_HOURS,
        }
    
    def reset_state(self):
        """상태 리셋 (수동 복구용)"""
        self.failure_count = 0
        self.last_failure_time = None
        self.blocked_until = None
        
        # 캐시에서도 삭제
        cache.delete(self.CACHE_KEY_API_FAILURE_COUNT)
        cache.delete(self.CACHE_KEY_API_LAST_FAILURE)
        cache.delete(self.CACHE_KEY_API_BLOCKED_UNTIL)
        
        logger.info("API 백업 시스템 상태가 리셋되었습니다")
        
        SystemLog.log('INFO', 'api_backup', 
                     "API 백업 시스템 상태 리셋",
                     {'timestamp': timezone.now().isoformat()})


# 전역 백업 서비스 인스턴스
api_backup_service = APIBackupService()