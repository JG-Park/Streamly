"""
텔레그램 알림 서비스
"""

import logging
import asyncio
from typing import Optional
from django.conf import settings
from telegram import Bot
from telegram.error import TelegramError

logger = logging.getLogger('streamly')


class TelegramService:
    """텔레그램 봇 서비스"""
    
    def __init__(self):
        self.bot_token = settings.TELEGRAM_BOT_TOKEN
        self.chat_id = settings.TELEGRAM_CHAT_ID
        self.bot = None
        
        if self.bot_token and self.chat_id:
            self.bot = Bot(token=self.bot_token)
    
    def is_configured(self) -> bool:
        """텔레그램 봇이 설정되어 있는지 확인"""
        return bool(self.bot_token and self.chat_id and self.bot)
    
    def send_message(self, message: str, parse_mode: str = 'HTML') -> bool:
        """메시지 전송 (동기 방식으로 변경)"""
        if not self.is_configured():
            logger.warning("텔레그램 봇이 설정되지 않음")
            return False
        
        try:
            import requests
            
            # REST API로 직접 호출
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            
            # chat_id를 정수로 변환
            try:
                chat_id_int = int(self.chat_id) if isinstance(self.chat_id, str) else self.chat_id
            except (ValueError, TypeError):
                logger.error(f"잘못된 chat_id 형식: {self.chat_id}")
                return False
            
            data = {
                'chat_id': chat_id_int,
                'text': message,
                'parse_mode': parse_mode
            }
            
            response = requests.post(url, json=data, timeout=10)
            result = response.json()
            
            if result.get('ok'):
                logger.debug(f"텔레그램 메시지 전송 성공: {message[:50]}...")
                return True
            else:
                logger.error(f"텔레그램 메시지 전송 실패: {result.get('description', 'Unknown error')}")
                return False
                
        except requests.exceptions.RequestException as e:
            logger.error(f"텔레그램 API 요청 실패: {e}")
            return False
        except Exception as e:
            logger.error(f"텔레그램 메시지 전송 중 예외 발생: {e}")
            return False
    
    def send_live_start_notification(self, channel_name: str, title: str, url: str) -> bool:
        """라이브 시작 알림"""
        message = f"""
🔴 <b>라이브 시작!</b>

📺 <b>채널:</b> {channel_name}
📹 <b>제목:</b> {title}
🔗 <b>URL:</b> <a href="{url}">{url}</a>

#라이브시작 #{channel_name.replace(' ', '_')}
        """.strip()
        
        return self.send_message(message)
    
    def send_live_end_notification(self, channel_name: str, title: str, duration: str) -> bool:
        """라이브 종료 알림"""
        message = f"""
⏹️ <b>라이브 종료</b>

📺 <b>채널:</b> {channel_name}
📹 <b>제목:</b> {title}
⏱️ <b>방송 시간:</b> {duration}

💾 다운로드를 시작합니다...

#라이브종료 #{channel_name.replace(' ', '_')}
        """.strip()
        
        return self.send_message(message)
    
    def send_download_complete_notification(self, channel_name: str, title: str, 
                                          quality: str, file_size: str = None) -> bool:
        """다운로드 완료 알림"""
        message = f"""
✅ <b>다운로드 완료!</b>

📺 <b>채널:</b> {channel_name}
📹 <b>제목:</b> {title}
🎬 <b>화질:</b> {quality}
        """
        
        if file_size:
            message += f"\n📏 <b>크기:</b> {file_size}"
        
        message += f"\n\n#다운로드완료 #{channel_name.replace(' ', '_')}"
        
        return self.send_message(message.strip())
    
    def send_download_failed_notification(self, channel_name: str, title: str, 
                                        quality: str, error: str) -> bool:
        """다운로드 실패 알림"""
        message = f"""
❌ <b>다운로드 실패</b>

📺 <b>채널:</b> {channel_name}
📹 <b>제목:</b> {title}
🎬 <b>화질:</b> {quality}
⚠️ <b>오류:</b> {error[:100]}{'...' if len(error) > 100 else ''}

#다운로드실패 #{channel_name.replace(' ', '_')}
        """.strip()
        
        return self.send_message(message)
    
    def send_cleanup_notification(self, deleted_count: int, freed_space: str) -> bool:
        """파일 정리 알림"""
        message = f"""
🧹 <b>파일 정리 완료</b>

🗑️ <b>삭제된 파일:</b> {deleted_count}개
💾 <b>확보된 공간:</b> {freed_space}

#파일정리
        """.strip()
        
        return self.send_message(message)
    
    def send_error_notification(self, error_type: str, message: str) -> bool:
        """에러 알림"""
        error_message = f"""
🚨 <b>시스템 오류</b>

🔴 <b>유형:</b> {error_type}
📝 <b>메시지:</b> {message[:200]}{'...' if len(message) > 200 else ''}

#시스템오류
        """.strip()
        
        return self.send_message(error_message)
    
    def test_connection(self) -> dict:
        """봇 연결 테스트"""
        if not self.is_configured():
            return {
                'success': False,
                'error': '텔레그램 봇 토큰 또는 채팅 ID가 설정되지 않음'
            }
        
        try:
            test_message = "🤖 Streamly 봇 연결 테스트"
            success = self.send_message(test_message)
            
            if success:
                return {
                    'success': True,
                    'message': '텔레그램 봇 연결 성공'
                }
            else:
                return {
                    'success': False,
                    'error': '메시지 전송 실패'
                }
                
        except Exception as e:
            return {
                'success': False,
                'error': f'연결 테스트 실패: {str(e)}'
            }


# 전역 텔레그램 서비스 인스턴스
telegram_service = TelegramService()