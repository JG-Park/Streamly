"""
다운로드 상태 불일치 문제 해결 관리 명령어
"""

import logging
from django.core.management.base import BaseCommand
from django.utils import timezone
from celery import current_app

from channels.models import LiveStream
from downloads.models import Download
from core.models import SystemLog

logger = logging.getLogger('streamly')


class Command(BaseCommand):
    help = '다운로드 상태 불일치 문제를 해결합니다'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='실제 변경 없이 검사만 수행',
        )
        parser.add_argument(
            '--fix-stuck-downloads',
            action='store_true',
            help='멈춘 다운로드 상태 수정',
        )
        parser.add_argument(
            '--fix-stuck-streams',
            action='store_true',
            help='멈춘 스트림 상태 수정',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        fix_stuck_downloads = options['fix_stuck_downloads']
        fix_stuck_streams = options['fix_stuck_streams']

        if not any([fix_stuck_downloads, fix_stuck_streams]):
            # 기본적으로 모든 수정 수행
            fix_stuck_downloads = True
            fix_stuck_streams = True

        self.stdout.write(self.style.SUCCESS('다운로드 상태 불일치 검사 시작...'))
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN 모드: 실제 변경은 수행되지 않습니다.'))

        total_fixed = 0

        if fix_stuck_downloads:
            total_fixed += self.fix_stuck_downloads(dry_run)

        if fix_stuck_streams:
            total_fixed += self.fix_stuck_streams(dry_run)

        # 활성 Celery 태스크와 비교
        total_fixed += self.check_active_celery_tasks(dry_run)

        if total_fixed > 0:
            self.stdout.write(
                self.style.SUCCESS(
                    f'총 {total_fixed}개의 상태 불일치를 {"발견" if dry_run else "수정"}했습니다.'
                )
            )
        else:
            self.stdout.write(self.style.SUCCESS('상태 불일치가 발견되지 않았습니다.'))

    def fix_stuck_downloads(self, dry_run=False):
        """멈춘 다운로드 상태 수정"""
        self.stdout.write('멈춘 다운로드 검사 중...')
        
        fixed_count = 0
        
        # 30분 이상 다운로드 중 상태인 것들 찾기
        stuck_time = timezone.now() - timezone.timedelta(minutes=30)
        stuck_downloads = Download.objects.filter(
            status='downloading',
            started_at__lt=stuck_time
        )
        
        for download in stuck_downloads:
            self.stdout.write(
                f'  멈춘 다운로드 발견: {download.live_stream.title} ({download.get_quality_display()})'
            )
            
            if not dry_run:
                download.mark_as_failed('30분 이상 진행되지 않아 자동으로 실패 처리됨')
                SystemLog.log('INFO', 'system', 
                             f'멈춘 다운로드 상태 수정: {download.live_stream.title}',
                             {'download_id': download.id})
            
            fixed_count += 1
        
        # 시작 시간이 없는 다운로드 중 상태들
        downloads_without_start = Download.objects.filter(
            status='downloading',
            started_at__isnull=True
        )
        
        for download in downloads_without_start:
            self.stdout.write(
                f'  시작 시간 없는 다운로드 발견: {download.live_stream.title} ({download.get_quality_display()})'
            )
            
            if not dry_run:
                download.status = 'pending'
                download.save(update_fields=['status'])
                SystemLog.log('INFO', 'system', 
                             f'시작 시간 없는 다운로드 상태 수정: {download.live_stream.title}',
                             {'download_id': download.id})
            
            fixed_count += 1
        
        return fixed_count

    def fix_stuck_streams(self, dry_run=False):
        """멈춘 스트림 상태 수정"""
        self.stdout.write('멈춘 스트림 상태 검사 중...')
        
        fixed_count = 0
        
        # 다운로드 중 상태이지만 실제로는 다운로드가 없는 스트림들
        downloading_streams = LiveStream.objects.filter(status='downloading')
        
        for stream in downloading_streams:
            # 해당 스트림의 활성 다운로드 확인
            active_downloads = stream.downloads.filter(
                status__in=['pending', 'downloading']
            ).count()
            
            if active_downloads == 0:
                self.stdout.write(
                    f'  활성 다운로드 없는 스트림 발견: {stream.title}'
                )
                
                if not dry_run:
                    # 완료된 다운로드가 있으면 completed, 없으면 ended
                    completed_downloads = stream.downloads.filter(status='completed').count()
                    new_status = 'completed' if completed_downloads > 0 else 'ended'
                    
                    stream.status = new_status
                    stream.save(update_fields=['status'])
                    
                    SystemLog.log('INFO', 'system', 
                                 f'스트림 상태 수정: {stream.title}',
                                 {'stream_id': stream.id, 'new_status': new_status})
                
                fixed_count += 1
        
        return fixed_count

    def check_active_celery_tasks(self, dry_run=False):
        """활성 Celery 태스크와 DB 상태 비교"""
        self.stdout.write('Celery 태스크 상태 확인 중...')
        
        fixed_count = 0
        
        try:
            # Celery 인스펙터로 활성 태스크 확인
            inspect = current_app.control.inspect()
            active_tasks = inspect.active()
            
            if not active_tasks:
                self.stdout.write('  활성 Celery 태스크가 없습니다.')
                return fixed_count
            
            # 모든 워커의 활성 다운로드 태스크 ID 수집
            active_download_ids = set()
            
            for worker, tasks in active_tasks.items():
                for task in tasks:
                    if task.get('name') == 'core.tasks.download_video':
                        args = task.get('args', [])
                        if args:
                            try:
                                download_id = int(args[0])
                                active_download_ids.add(download_id)
                            except (ValueError, IndexError):
                                continue
            
            self.stdout.write(f'  활성 다운로드 태스크: {len(active_download_ids)}개')
            
            # DB에서 다운로드 중 상태인 것들과 비교
            downloading_in_db = Download.objects.filter(status='downloading')
            
            for download in downloading_in_db:
                if download.id not in active_download_ids:
                    self.stdout.write(
                        f'  Celery에서 실행되지 않는 다운로드 발견: {download.live_stream.title}'
                    )
                    
                    if not dry_run:
                        download.mark_as_failed('Celery 태스크가 존재하지 않아 실패 처리됨')
                        SystemLog.log('INFO', 'system', 
                                     f'Celery 태스크 없는 다운로드 실패 처리: {download.live_stream.title}',
                                     {'download_id': download.id})
                    
                    fixed_count += 1
            
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Celery 태스크 확인 중 오류: {e}')
            )
        
        return fixed_count