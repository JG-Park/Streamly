"""
YouTube Data API v3 통합 서비스
yt-dlp의 백업으로 사용되며, 더 안정적인 채널 모니터링을 제공합니다.
"""

import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from django.conf import settings

logger = logging.getLogger('streamly')

try:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    YOUTUBE_API_AVAILABLE = True
except ImportError:
    YOUTUBE_API_AVAILABLE = False
    logger.warning("YouTube API 클라이언트가 설치되지 않았습니다. yt-dlp만 사용됩니다.")


class YouTubeAPIService:
    """YouTube Data API v3 서비스"""
    
    def __init__(self):
        # YouTube API 비활성화 - yt-dlp만 사용
        self.api_key = None  # getattr(settings, 'YOUTUBE_API_KEY', '')
        self.service = None
        
        # API 사용 비활성화
        logger.info("YouTube API 비활성화 - yt-dlp만 사용")
        
        # 향후 API 재활성화가 필요한 경우 아래 코드 주석 해제
        # if YOUTUBE_API_AVAILABLE and self.api_key:
        #     try:
        #         self.service = build('youtube', 'v3', developerKey=self.api_key)
        #         logger.info("YouTube API 서비스 초기화 완료")
        #     except Exception as e:
        #         logger.error(f"YouTube API 서비스 초기화 실패: {e}")
    
    def is_available(self) -> bool:
        """YouTube API 사용 가능 여부 확인"""
        return self.service is not None
    
    def get_channel_info_by_url(self, channel_url: str) -> Optional[Dict[str, Any]]:
        """URL로부터 채널 정보 가져오기"""
        if not self.is_available():
            return None
            
        try:
            # URL에서 채널 ID 또는 사용자명 추출
            channel_id = None
            username = None
            custom_name = None
            
            if '/channel/' in channel_url:
                channel_id = channel_url.split('/channel/')[1].split('/')[0].split('?')[0]
            elif '/@' in channel_url:
                username = channel_url.split('/@')[1].split('/')[0].split('?')[0]
            elif '/c/' in channel_url:
                custom_name = channel_url.split('/c/')[1].split('/')[0].split('?')[0]
            elif '/user/' in channel_url:
                username = channel_url.split('/user/')[1].split('/')[0].split('?')[0]
            
            # API로 채널 정보 조회
            if channel_id:
                return self._get_channel_by_id(channel_id)
            elif username:
                # @ 핸들인 경우 특별 처리
                if username.startswith('@'):
                    username = username[1:]
                # forUsername이 작동하지 않으면 검색 API 사용
                result = self._get_channel_by_username(username)
                if not result:
                    result = self._search_channel_by_name(username)
                return result
            elif custom_name:
                return self._search_channel_by_name(custom_name)
                
        except Exception as e:
            logger.error(f"YouTube API로 채널 정보 조회 실패: {channel_url}, 에러: {e}")
            
        return None
    
    def _get_channel_by_id(self, channel_id: str) -> Optional[Dict[str, Any]]:
        """채널 ID로 채널 정보 가져오기"""
        try:
            request = self.service.channels().list(
                part='snippet,statistics',
                id=channel_id
            )
            response = request.execute()
            
            if response['items']:
                item = response['items'][0]
                return {
                    'channel_id': item['id'],
                    'channel_name': item['snippet']['title'],
                    'channel_url': f"https://www.youtube.com/channel/{item['id']}",
                    'description': item['snippet'].get('description', ''),
                    'thumbnail': item['snippet']['thumbnails'].get('default', {}).get('url', ''),
                    'subscriber_count': int(item['statistics'].get('subscriberCount', 0)),
                    'video_count': int(item['statistics'].get('videoCount', 0)),
                    'published_at': item['snippet'].get('publishedAt'),
                }
        except HttpError as e:
            logger.error(f"YouTube API 에러 (채널 ID: {channel_id}): {e}")
        except Exception as e:
            logger.error(f"채널 정보 조회 실패 (채널 ID: {channel_id}): {e}")
            
        return None
    
    def _get_channel_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """사용자명으로 채널 정보 가져오기"""
        try:
            # forUsername 파라미터는 레거시 사용자명에만 작동
            request = self.service.channels().list(
                part='snippet,statistics',
                forUsername=username
            )
            response = request.execute()
            
            if response['items']:
                item = response['items'][0]
                return {
                    'channel_id': item['id'],
                    'channel_name': item['snippet']['title'],
                    'channel_url': f"https://www.youtube.com/channel/{item['id']}",
                    'description': item['snippet'].get('description', ''),
                    'thumbnail': item['snippet']['thumbnails'].get('default', {}).get('url', ''),
                    'subscriber_count': int(item['statistics'].get('subscriberCount', 0)),
                    'video_count': int(item['statistics'].get('videoCount', 0)),
                    'published_at': item['snippet'].get('publishedAt'),
                }
            else:
                # forUsername이 작동하지 않으면 검색으로 시도
                return self._search_channel_by_name(username)
                
        except HttpError as e:
            logger.error(f"YouTube API 에러 (사용자명: {username}): {e}")
            # 검색으로 재시도
            return self._search_channel_by_name(username)
        except Exception as e:
            logger.error(f"채널 정보 조회 실패 (사용자명: {username}): {e}")
            
        return None
    
    def _search_channel_by_name(self, channel_name: str) -> Optional[Dict[str, Any]]:
        """채널명으로 검색하여 채널 정보 가져오기"""
        try:
            # 먼저 검색으로 채널 찾기
            search_request = self.service.search().list(
                part='snippet',
                q=channel_name,
                type='channel',
                maxResults=5
            )
            search_response = search_request.execute()
            
            if search_response['items']:
                # 가장 관련성 높은 채널 선택
                for item in search_response['items']:
                    if item['snippet']['title'].lower() == channel_name.lower():
                        channel_id = item['id']['channelId']
                        return self._get_channel_by_id(channel_id)
                
                # 정확히 일치하는 것이 없으면 첫 번째 결과 사용
                channel_id = search_response['items'][0]['id']['channelId']
                return self._get_channel_by_id(channel_id)
                
        except HttpError as e:
            logger.error(f"YouTube API 검색 에러 (채널명: {channel_name}): {e}")
        except Exception as e:
            logger.error(f"채널 검색 실패 (채널명: {channel_name}): {e}")
            
        return None
    
    def get_live_streams(self, channel_id: str) -> List[Dict[str, Any]]:
        """채널의 라이브 스트림 목록 가져오기"""
        if not self.is_available():
            return []
            
        try:
            # @ 핸들인 경우 실제 채널 ID로 변환
            if channel_id.startswith('@'):
                channel_info = self.get_channel_info_by_url(f"https://youtube.com/{channel_id}")
                if channel_info:
                    channel_id = channel_info['channel_id']
                else:
                    logger.error(f"채널 ID 변환 실패: {channel_id}")
                    return []
            
            # 채널의 최근 동영상 중 라이브 스트림 찾기
            search_request = self.service.search().list(
                part='snippet',
                channelId=channel_id,
                eventType='live',
                type='video',
                maxResults=10,
                order='date'
            )
            search_response = search_request.execute()
            
            live_streams = []
            for item in search_response['items']:
                # 동영상 상세 정보 가져오기
                video_request = self.service.videos().list(
                    part='snippet,liveStreamingDetails,statistics',
                    id=item['id']['videoId']
                )
                video_response = video_request.execute()
                
                if video_response['items']:
                    video = video_response['items'][0]
                    live_details = video.get('liveStreamingDetails', {})
                    
                    # 실제로 라이브 중인지 확인
                    if live_details.get('actualStartTime') and not live_details.get('actualEndTime'):
                        live_streams.append({
                            'video_id': video['id'],
                            'title': video['snippet']['title'],
                            'url': f"https://www.youtube.com/watch?v={video['id']}",
                            'thumbnail': video['snippet']['thumbnails'].get('medium', {}).get('url', ''),
                            'is_live': True,
                            'started_at': live_details.get('actualStartTime'),
                            'scheduled_start': live_details.get('scheduledStartTime'),
                            'concurrent_viewers': live_details.get('concurrentViewers'),
                            'description': video['snippet'].get('description', ''),
                        })
            
            return live_streams
            
        except HttpError as e:
            error_message = str(e)
            # 할당량 초과 에러 체크
            if 'quotaExceeded' in error_message or 'quota' in error_message.lower():
                logger.error(f"YouTube API 할당량 초과 (채널 ID: {channel_id}): {e}")
                # 할당량 초과는 명시적으로 실패 처리하여 백업으로 전환되도록 함
                raise Exception(f"quotaExceeded: {error_message}")
            else:
                logger.error(f"YouTube API 라이브 스트림 조회 에러 (채널 ID: {channel_id}): {e}")
                raise e
        except Exception as e:
            logger.error(f"라이브 스트림 조회 실패 (채널 ID: {channel_id}): {e}")
            raise e
            
        return []
    
    def get_video_details(self, video_id: str) -> Optional[Dict[str, Any]]:
        """비디오 상세 정보 가져오기"""
        if not self.is_available():
            return None
            
        try:
            request = self.service.videos().list(
                part='snippet,liveStreamingDetails,statistics,contentDetails',
                id=video_id
            )
            response = request.execute()
            
            if response['items']:
                video = response['items'][0]
                live_details = video.get('liveStreamingDetails', {})
                
                return {
                    'video_id': video['id'],
                    'title': video['snippet']['title'],
                    'url': f"https://www.youtube.com/watch?v={video['id']}",
                    'thumbnail': video['snippet']['thumbnails'].get('medium', {}).get('url', ''),
                    'channel_id': video['snippet']['channelId'],
                    'channel_name': video['snippet']['channelTitle'],
                    'description': video['snippet'].get('description', ''),
                    'published_at': video['snippet'].get('publishedAt'),
                    'is_live': bool(live_details.get('actualStartTime') and not live_details.get('actualEndTime')),
                    'was_live': bool(live_details.get('actualStartTime')),
                    'duration': video.get('contentDetails', {}).get('duration'),
                    'live_start_time': live_details.get('actualStartTime'),
                    'live_end_time': live_details.get('actualEndTime'),
                    'scheduled_start': live_details.get('scheduledStartTime'),
                    'concurrent_viewers': live_details.get('concurrentViewers'),
                    'view_count': int(video['statistics'].get('viewCount', 0)),
                    'like_count': int(video['statistics'].get('likeCount', 0)),
                    'comment_count': int(video['statistics'].get('commentCount', 0)),
                }
                
        except HttpError as e:
            logger.error(f"YouTube API 비디오 정보 조회 에러 (비디오 ID: {video_id}): {e}")
        except Exception as e:
            logger.error(f"비디오 정보 조회 실패 (비디오 ID: {video_id}): {e}")
            
        return None
    
    def check_quota_usage(self) -> Dict[str, Any]:
        """API 할당량 사용량 확인 (대략적 추정)"""
        return {
            'available': self.is_available(),
            'api_key_set': bool(self.api_key),
            'note': 'YouTube API는 일일 할당량 제한이 있습니다. 과도한 사용 시 yt-dlp로 전환됩니다.'
        }


# 전역 YouTube API 서비스 인스턴스
youtube_api_service = YouTubeAPIService()