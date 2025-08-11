"""
채널 관련 Django 신호(signals)
"""

from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django_celery_beat.models import PeriodicTask, IntervalSchedule
from .models import Channel, LiveStream
import json
import logging

logger = logging.getLogger('streamly')


@receiver(post_save, sender=Channel)
def update_channel_schedule(sender, instance, created, **kwargs):
    """채널이 저장될 때 Celery Beat 스케줄 업데이트"""
    
    task_name = f'check-channel-{instance.channel_id}'
    
    if instance.is_active:
        # 활성 채널: 스케줄 생성 또는 업데이트
        try:
            # 체크 주기에 맞는 IntervalSchedule 생성 또는 가져오기
            interval_minutes = instance.check_interval_minutes
            interval, _ = IntervalSchedule.objects.get_or_create(
                every=interval_minutes * 60,  # 초 단위로 변환
                period=IntervalSchedule.SECONDS
            )
            
            # PeriodicTask 생성 또는 업데이트
            task, task_created = PeriodicTask.objects.update_or_create(
                name=task_name,
                defaults={
                    'interval': interval,
                    'task': 'core.tasks.check_channel_live_streams',
                    'args': json.dumps([instance.id]),
                    'enabled': True,
                    'description': f'{instance.name} 채널 체크 (매 {interval_minutes}분)'
                }
            )
            
            action = '생성' if task_created else '업데이트'
            logger.info(f'채널 스케줄 {action}: {instance.name} - 매 {interval_minutes}분')
            
        except Exception as e:
            logger.error(f'채널 스케줄 업데이트 실패: {instance.name} - {e}')
    
    else:
        # 비활성 채널: 스케줄 비활성화
        try:
            task = PeriodicTask.objects.get(name=task_name)
            task.enabled = False
            task.save()
            logger.info(f'채널 스케줄 비활성화: {instance.name}')
        except PeriodicTask.DoesNotExist:
            pass


@receiver(post_delete, sender=Channel)
def delete_channel_schedule(sender, instance, **kwargs):
    """채널이 삭제될 때 Celery Beat 스케줄도 삭제"""
    
    task_name = f'check-channel-{instance.channel_id}'
    
    try:
        task = PeriodicTask.objects.get(name=task_name)
        task.delete()
        logger.info(f'채널 스케줄 삭제: {instance.name}')
    except PeriodicTask.DoesNotExist:
        pass


@receiver(post_save, sender=LiveStream)
def send_live_stream_notification(sender, instance, created, **kwargs):
    """라이브 스트림이 생성될 때 텔레그램 알림 전송"""
    
    # 새로 생성된 라이브 스트림이고 알림이 전송되지 않은 경우
    if created and instance.status == 'live' and not instance.notification_sent:
        try:
            from core.telegram_service import telegram_service
            
            # 텔레그램 알림 전송
            success = telegram_service.send_live_start_notification(
                channel_name=instance.channel.name,
                title=instance.title,
                url=instance.url
            )
            
            if success:
                # 알림 전송 성공 시 플래그 업데이트
                instance.notification_sent = True
                instance.save(update_fields=['notification_sent'])
                logger.info(f'라이브 시작 알림 전송 성공: {instance.title}')
            else:
                logger.warning(f'라이브 시작 알림 전송 실패: {instance.title}')
                
        except Exception as e:
            logger.error(f'라이브 시작 알림 전송 중 오류: {e}')


@receiver(post_save, sender=LiveStream)
def send_live_end_notification(sender, instance, created, **kwargs):
    """라이브 스트림이 종료될 때 텔레그램 알림 전송"""
    
    # 업데이트이고 status가 'ended'로 변경된 경우
    if not created and instance.status == 'ended' and instance.ended_at:
        try:
            from core.telegram_service import telegram_service
            
            # 방송 시간 계산
            duration = instance.duration
            if duration:
                hours, remainder = divmod(duration.total_seconds(), 3600)
                minutes, _ = divmod(remainder, 60)
                duration_str = f"{int(hours)}시간 {int(minutes)}분" if hours else f"{int(minutes)}분"
            else:
                duration_str = "알 수 없음"
            
            # 텔레그램 알림 전송
            success = telegram_service.send_live_end_notification(
                channel_name=instance.channel.name,
                title=instance.title,
                duration=duration_str
            )
            
            if success:
                logger.info(f'라이브 종료 알림 전송 성공: {instance.title}')
            else:
                logger.warning(f'라이브 종료 알림 전송 실패: {instance.title}')
                
        except Exception as e:
            logger.error(f'라이브 종료 알림 전송 중 오류: {e}')