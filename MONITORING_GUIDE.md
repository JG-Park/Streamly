# 📊 Streamly 효율적인 YouTube 모니터링 가이드

## 🎯 목표
YouTube API 할당량(일 10,000 유닛)을 최소화하면서 실시간 모니터링 제공

## 🚀 모니터링 전략

### 1. API 사용 최소화
- **채널 등록 시**: YouTube API 1회 사용 (채널 정보 획득)
- **라이브 모니터링**: RSS/yt-dlp 사용 (API 소비 없음)
- **상세 정보**: 필요시에만 API 호출

### 2. 3단계 체크 시스템

#### 📡 1단계: RSS 피드 (권장)
```python
# API 소비: 0
# 최신 비디오 목록 획득
https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}
```

#### 🔍 2단계: yt-dlp 라이브 확인
```python
# API 소비: 0  
# RSS에서 얻은 최근 비디오 중 라이브 여부 확인
# 봇 감지 회피를 위한 쿠키 사용 가능
```

#### 📝 3단계: API 상세 정보 (선택)
```python
# API 소비: 1-3 유닛
# 썸네일, 조회수, 좋아요 등 추가 정보
```

## ⚙️ 설정 방법

### 1. 환경변수 설정
```bash
# .env 파일
YOUTUBE_MONITORING_MODE=efficient  # 'efficient' 또는 'api'
YOUTUBE_API_KEY=your_api_key_here  # 채널 등록용
```

### 2. 쿠키 파일 설정 (선택사항)
봇 감지를 피하고 연령 제한 콘텐츠에 접근하려면:

1. 브라우저에서 YouTube 로그인
2. 쿠키 추출 (브라우저 확장 프로그램 사용)
3. `cookies.txt` 파일로 저장
4. 프로젝트 루트에 배치

### 3. 동적 체크 주기
채널의 라이브 빈도에 따라 자동 조정:

| 라이브 빈도 | 체크 주기 | 일일 체크 횟수 |
|------------|----------|---------------|
| 매일 (7+/주) | 1분 | 1,440회 |
| 자주 (3-6/주) | 5분 | 288회 |
| 가끔 (0-2/주) | 15분 | 96회 |

## 📈 API 사용량 비교

### 기존 방식 (API 전용)
- 10개 채널 × 1분 체크 × 100 유닛 = **144,000 유닛/일**
- 할당량 초과로 **10분만에 중단**

### 효율적 방식 (하이브리드)
- 채널 등록: 10개 × 1 유닛 = 10 유닛
- 라이브 모니터링: 0 유닛 (RSS/yt-dlp)
- 상세 정보: ~50 유닛/일 (선택적)
- **총 60 유닛/일** (99.96% 절감)

## 💻 코드 예제

### 채널 등록
```python
from core.youtube_monitor import hybrid_service

# API 1회 사용하여 정확한 채널 정보 획득
channel_info = hybrid_service.register_channel("https://youtube.com/@channelname")
```

### 라이브 모니터링
```python
# API 사용 없이 라이브 확인
live_streams = hybrid_service.check_channel_streams(channel_id)

for stream in live_streams:
    print(f"🔴 LIVE: {stream['title']}")
    print(f"URL: {stream['url']}")
```

### 상세 정보 (선택적)
```python
# 필요한 경우에만 API로 상세 정보
if live_streams and need_details:
    details = hybrid_service.get_stream_details(video_id)
    print(f"조회수: {details['view_count']}")
    print(f"좋아요: {details['like_count']}")
```

## 🔧 문제 해결

### RSS 피드 실패
- 일부 채널은 RSS 비활성화 가능
- 대안: yt-dlp로 채널 페이지 직접 확인

### 봇 감지
- 증상: "Sign in to confirm you're not a bot"
- 해결: cookies.txt 파일 사용

### 연령 제한 콘텐츠
- 증상: "Age-restricted video"
- 해결: 로그인된 쿠키 사용

## 📊 모니터링 대시보드

### 채널 상태 확인
- 마지막 확인 시간
- 체크 주기 (동적 조정)
- 마지막 라이브 시간
- 주간 라이브 횟수

### 시스템 상태
- API 사용량: 일일 할당량 대비 %
- RSS 성공률
- yt-dlp 성공률
- 평균 응답 시간

## 🎯 권장 사항

1. **RSS 우선 사용**: 가장 효율적이고 안정적
2. **쿠키 파일 설정**: 봇 감지 회피
3. **체크 주기 최적화**: 채널별 활동 패턴 학습
4. **API 예약**: 중요한 이벤트용으로 API 할당량 보존
5. **캐싱 활용**: 반복 요청 최소화

## 📈 성능 지표

| 지표 | 목표 | 현재 |
|-----|-----|-----|
| API 일일 사용량 | < 100 | ~60 |
| 지원 채널 수 | 100+ | 무제한 |
| 라이브 감지 지연 | < 5분 | 1-15분 |
| 시스템 가동률 | 99.9% | - |

## 🚀 향후 개선 계획

1. **WebSocket 지원**: YouTube 실시간 알림
2. **머신러닝**: 채널별 라이브 패턴 예측
3. **분산 처리**: 여러 서버로 부하 분산
4. **프록시 로테이션**: IP 차단 회피
5. **커뮤니티 쿠키**: 사용자들이 쿠키 공유

---

이 가이드대로 설정하면 YouTube API 할당량 걱정 없이 수백 개의 채널을 효율적으로 모니터링할 수 있습니다!