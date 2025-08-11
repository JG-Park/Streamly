"""
채널별 개별 체크 스케줄 설정 명령어
"""

from django.core.management.base import BaseCommand
from django_celery_beat.models import PeriodicTask, IntervalSchedule
from channels.models import Channel
import json


class Command(BaseCommand):
    help = '각 채널의 개별 체크 주기에 맞춰 Celery Beat 스케줄 설정'

    def handle(self, *args, **options):
        # 기존 전체 채널 체크 태스크 비활성화
        try:
            all_channels_task = PeriodicTask.objects.get(name='check-channels-every-minute')
            all_channels_task.enabled = False
            all_channels_task.save()
            self.stdout.write(self.style.SUCCESS('기존 전체 채널 체크 태스크 비활성화'))
        except PeriodicTask.DoesNotExist:
            pass
        
        # 각 채널에 대한 개별 태스크 생성
        channels = Channel.objects.filter(is_active=True)
        
        for channel in channels:
            # 해당 채널의 체크 주기에 맞는 IntervalSchedule 생성 또는 가져오기
            interval_minutes = channel.check_interval_minutes
            interval, created = IntervalSchedule.objects.get_or_create(
                every=interval_minutes * 60,  # 초 단위로 변환
                period=IntervalSchedule.SECONDS
            )
            
            # PeriodicTask 생성 또는 업데이트
            task_name = f'check-channel-{channel.channel_id}'
            
            task, created = PeriodicTask.objects.update_or_create(
                name=task_name,
                defaults={
                    'interval': interval,
                    'task': 'core.tasks.check_channel_live_streams',
                    'args': json.dumps([channel.id]),
                    'enabled': True,
                    'description': f'{channel.name} 채널 체크 (매 {interval_minutes}분)'
                }
            )
            
            action = '생성' if created else '업데이트'
            self.stdout.write(
                self.style.SUCCESS(
                    f'{action}: {channel.name} - 매 {interval_minutes}분마다 체크'
                )
            )
        
        self.stdout.write(self.style.SUCCESS(f'총 {channels.count()}개 채널 스케줄 설정 완료'))