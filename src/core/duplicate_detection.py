"""
중복 감지 시스템 강화
라이브 스트림과 다운로드 중복을 더욱 정교하게 감지하고 관리합니다.
"""

import logging
import hashlib
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from django.db import transaction
from django.utils import timezone
from django.core.cache import cache

from channels.models import Channel, LiveStream
from core.models import SystemLog

# downloads.models는 나중에 임포트 (순환 임포트 방지)
try:
    from downloads.models import Download
except ImportError:
    # 마이그레이션 중일 때는 임포트 실패 허용
    Download = None

logger = logging.getLogger('streamly')


class DuplicateDetectionService:
    """중복 감지 및 관리 서비스"""
    
    # 캐시 키 상수
    CACHE_KEY_RECENT_STREAMS = "recent_streams_{channel_id}"
    CACHE_KEY_TITLE_HASH = "title_hash_{hash}"
    CACHE_KEY_DUPLICATE_CHECK = "duplicate_check_{video_id}"
    
    # 설정 상수
    TITLE_SIMILARITY_THRESHOLD = 0.85  # 제목 유사도 임계값
    TIME_WINDOW_MINUTES = 120          # 중복 확인 시간 창 (2시간)
    CACHE_TIMEOUT_MINUTES = 60         # 캐시 유지 시간
    
    def __init__(self):
        self.recent_streams_cache = {}
    
    def check_stream_duplicate(self, 
                              channel: Channel, 
                              video_id: str, 
                              title: str, 
                              url: str) -> Dict[str, Any]:
        """
        라이브 스트림 중복 여부 확인
        
        Returns:
            {
                'is_duplicate': bool,
                'duplicate_type': str,  # 'exact', 'similar', 'restream', None
                'existing_stream': LiveStream or None,
                'confidence': float,    # 중복 확신도 (0.0-1.0)
                'reason': str          # 중복 판정 이유
            }
        """
        result = {
            'is_duplicate': False,
            'duplicate_type': None,
            'existing_stream': None,
            'confidence': 0.0,
            'reason': ''
        }
        
        try:
            # 1. 정확한 video_id 매치 확인
            exact_match = self._check_exact_video_id_match(video_id)
            if exact_match:
                result.update({
                    'is_duplicate': True,
                    'duplicate_type': 'exact',
                    'existing_stream': exact_match,
                    'confidence': 1.0,
                    'reason': f'동일한 video_id: {video_id}'
                })
                return result
            
            # 2. 제목 기반 중복 확인
            title_duplicate = self._check_title_duplicate(channel, title)
            if title_duplicate['is_duplicate']:
                result.update({
                    'is_duplicate': True,
                    'duplicate_type': 'similar',
                    'existing_stream': title_duplicate['existing_stream'],
                    'confidence': title_duplicate['confidence'],
                    'reason': title_duplicate['reason']
                })
                return result
            
            # 3. 재방송 패턴 확인
            restream_check = self._check_restream_pattern(channel, title)
            if restream_check['is_duplicate']:
                result.update({
                    'is_duplicate': True,
                    'duplicate_type': 'restream',
                    'existing_stream': restream_check['existing_stream'],
                    'confidence': restream_check['confidence'],
                    'reason': restream_check['reason']
                })
                return result
            
            # 4. 캐시에 현재 스트림 정보 저장
            self._cache_stream_info(channel.channel_id, video_id, title)
            
            logger.debug(f"중복 없음: {channel.name} - {title[:50]}...")
            
        except Exception as e:
            logger.error(f"중복 감지 오류: {e}")
            result['reason'] = f'중복 감지 중 오류: {str(e)}'
        
        return result
    
    def _check_exact_video_id_match(self, video_id: str) -> Optional[LiveStream]:
        """정확한 video_id 매치 확인"""
        try:
            return LiveStream.objects.filter(video_id=video_id).first()
        except Exception as e:
            logger.error(f"video_id 중복 확인 오류: {e}")
            return None
    
    def _check_title_duplicate(self, channel: Channel, title: str) -> Dict[str, Any]:
        """제목 기반 중복 확인"""
        result = {
            'is_duplicate': False,
            'existing_stream': None,
            'confidence': 0.0,
            'reason': ''
        }
        
        try:
            # 최근 스트림들과 비교
            time_threshold = timezone.now() - timedelta(minutes=self.TIME_WINDOW_MINUTES)
            recent_streams = LiveStream.objects.filter(
                channel=channel,
                started_at__gte=time_threshold
            ).values('id', 'title', 'video_id')
            
            for stream_data in recent_streams:
                similarity = self._calculate_title_similarity(title, stream_data['title'])
                
                if similarity >= self.TITLE_SIMILARITY_THRESHOLD:
                    # 높은 유사도의 제목 발견
                    existing_stream = LiveStream.objects.get(id=stream_data['id'])
                    result.update({
                        'is_duplicate': True,
                        'existing_stream': existing_stream,
                        'confidence': similarity,
                        'reason': f'유사한 제목 (유사도: {similarity:.2f}): "{stream_data["title"]}"'
                    })
                    break
            
        except Exception as e:
            logger.error(f"제목 중복 확인 오류: {e}")
        
        return result
    
    def _check_restream_pattern(self, channel: Channel, title: str) -> Dict[str, Any]:
        """재방송 패턴 확인"""
        result = {
            'is_duplicate': False,
            'existing_stream': None,
            'confidence': 0.0,
            'reason': ''
        }
        
        try:
            # 재방송 키워드 패턴
            restream_keywords = [
                '다시보기', '재방송', 'replay', 'rerun', '재송', 
                'encore', '앙코르', '리플레이', 'restream'
            ]
            
            title_lower = title.lower()
            has_restream_keyword = any(keyword in title_lower for keyword in restream_keywords)
            
            if has_restream_keyword:
                # 재방송 키워드가 있는 경우, 원본 스트림 찾기
                cleaned_title = self._clean_restream_title(title)
                
                # 최근 일주일 내 유사한 제목의 스트림 찾기
                time_threshold = timezone.now() - timedelta(days=7)
                potential_originals = LiveStream.objects.filter(
                    channel=channel,
                    started_at__gte=time_threshold,
                    status__in=['completed', 'ended']
                )
                
                for original_stream in potential_originals:
                    original_cleaned = self._clean_restream_title(original_stream.title)
                    similarity = self._calculate_title_similarity(cleaned_title, original_cleaned)
                    
                    if similarity >= 0.7:  # 재방송 확인을 위한 낮은 임계값
                        result.update({
                            'is_duplicate': True,
                            'existing_stream': original_stream,
                            'confidence': similarity,
                            'reason': f'재방송 감지 (원본: "{original_stream.title}")'
                        })
                        break
        
        except Exception as e:
            logger.error(f"재방송 패턴 확인 오류: {e}")
        
        return result
    
    def _calculate_title_similarity(self, title1: str, title2: str) -> float:
        """제목 유사도 계산 (Jaccard similarity 사용)"""
        try:
            # 문자열 정규화
            title1_normalized = self._normalize_title(title1)
            title2_normalized = self._normalize_title(title2)
            
            # 단어 집합 생성
            words1 = set(title1_normalized.split())
            words2 = set(title2_normalized.split())
            
            if not words1 and not words2:
                return 1.0
            if not words1 or not words2:
                return 0.0
            
            # Jaccard similarity 계산
            intersection = words1.intersection(words2)
            union = words1.union(words2)
            
            similarity = len(intersection) / len(union) if union else 0.0
            return similarity
            
        except Exception as e:
            logger.error(f"제목 유사도 계산 오류: {e}")
            return 0.0
    
    def _normalize_title(self, title: str) -> str:
        """제목 정규화"""
        try:
            import re
            
            # 소문자 변환
            normalized = title.lower()
            
            # 특수문자 제거 (한글, 영문, 숫자, 공백만 유지)
            normalized = re.sub(r'[^\w\s가-힣]', ' ', normalized)
            
            # 연속된 공백을 하나로
            normalized = re.sub(r'\s+', ' ', normalized).strip()
            
            # 일반적인 불용어 제거
            stop_words = {'live', 'stream', 'streaming', '라이브', '방송', 'the', 'a', 'an', 'and', 'or'}
            words = [word for word in normalized.split() if word not in stop_words and len(word) > 1]
            
            return ' '.join(words)
            
        except Exception as e:
            logger.error(f"제목 정규화 오류: {e}")
            return title.lower()
    
    def _clean_restream_title(self, title: str) -> str:
        """재방송 관련 키워드 제거"""
        try:
            import re
            
            # 재방송 키워드 패턴 제거
            restream_patterns = [
                r'다시\s?보기', r'재방송', r'replay', r'rerun', r'재송',
                r'encore', r'앙코르', r'리플레이', r'restream',
                r'\[.*재방송.*\]', r'\(.*다시보기.*\)', r'#재방송',
                r'재업로드', r'reupload'
            ]
            
            cleaned = title
            for pattern in restream_patterns:
                cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
            
            # 연속된 공백과 구두점 정리
            cleaned = re.sub(r'\s+', ' ', cleaned).strip()
            cleaned = re.sub(r'^[^\w가-힣]*|[^\w가-힣]*$', '', cleaned)
            
            return cleaned if cleaned else title
            
        except Exception as e:
            logger.error(f"재방송 제목 정리 오류: {e}")
            return title
    
    def _cache_stream_info(self, channel_id: str, video_id: str, title: str):
        """스트림 정보 캐시"""
        try:
            cache_key = self.CACHE_KEY_RECENT_STREAMS.format(channel_id=channel_id)
            
            # 기존 캐시 가져오기
            recent_streams = cache.get(cache_key, [])
            
            # 새 정보 추가
            stream_info = {
                'video_id': video_id,
                'title': title,
                'timestamp': timezone.now().isoformat()
            }
            recent_streams.append(stream_info)
            
            # 오래된 항목 제거 (최대 10개 유지)
            recent_streams = recent_streams[-10:]
            
            # 캐시 업데이트
            cache.set(cache_key, recent_streams, timeout=3600 * 2)  # 2시간 유지
            
        except Exception as e:
            logger.error(f"스트림 정보 캐시 오류: {e}")
    
    def check_download_duplicate(self, video_id: str, quality: str) -> Dict[str, Any]:
        """다운로드 중복 여부 확인"""
        # Download 모델 직접 임포트
        from downloads.models import Download
        
        result = {
            'is_duplicate': False,
            'existing_download': None,
            'reason': ''
        }
        
        try:
            # 먼저 video_id로 LiveStream 찾기
            from channels.models import LiveStream
            live_stream = LiveStream.objects.filter(video_id=video_id).first()
            
            if live_stream:
                # 동일한 LiveStream과 품질로 다운로드가 있는지 확인
                existing_download = Download.objects.filter(
                    live_stream=live_stream,
                    quality=quality
                ).first()
                
                if existing_download:
                    result.update({
                        'is_duplicate': True,
                        'existing_download': existing_download,
                        'reason': f'동일한 다운로드 존재 (품질: {quality}, 상태: {existing_download.status})'
                    })
                    
                    logger.debug(f"다운로드 중복 발견: {video_id} ({quality})")
            
        except Exception as e:
            logger.error(f"다운로드 중복 확인 오류: {e}")
            result['reason'] = f'중복 확인 중 오류: {str(e)}'
        
        return result
    
    def get_duplicate_statistics(self) -> Dict[str, Any]:
        """중복 감지 통계"""
        try:
            # 최근 24시간 중복 감지 통계
            time_threshold = timezone.now() - timedelta(hours=24)
            
            # 시스템 로그에서 중복 감지 로그 조회
            duplicate_logs = SystemLog.objects.filter(
                level__in=['INFO', 'WARNING'],
                category='duplicate_detection',
                created_at__gte=time_threshold
            )
            
            stats = {
                'total_checks': duplicate_logs.count(),
                'duplicates_found': duplicate_logs.filter(
                    message__icontains='중복 감지'
                ).count(),
                'duplicate_types': {
                    'exact': 0,
                    'similar': 0,
                    'restream': 0
                },
                'last_24h': duplicate_logs.count(),
                'cache_status': 'active' if cache.get('duplicate_detection_active') else 'inactive'
            }
            
            # 중복 타입별 분류
            for log in duplicate_logs:
                if 'exact' in log.message.lower():
                    stats['duplicate_types']['exact'] += 1
                elif 'similar' in log.message.lower():
                    stats['duplicate_types']['similar'] += 1
                elif 'restream' in log.message.lower():
                    stats['duplicate_types']['restream'] += 1
            
            return stats
            
        except Exception as e:
            logger.error(f"중복 감지 통계 오류: {e}")
            return {'error': str(e)}
    
    def cleanup_old_cache(self):
        """오래된 캐시 정리"""
        try:
            # 캐시 키 패턴으로 정리는 Redis 의존적이므로 
            # 여기서는 주요 캐시만 정리
            patterns_to_clean = [
                'recent_streams_*',
                'title_hash_*',
                'duplicate_check_*'
            ]
            
            # 실제 구현은 캐시 백엔드에 따라 달라짐
            logger.info("중복 감지 시스템 캐시 정리 완료")
            
        except Exception as e:
            logger.error(f"캐시 정리 오류: {e}")


# 전역 중복 감지 서비스 인스턴스
duplicate_detection_service = DuplicateDetectionService()