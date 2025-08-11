#!/usr/bin/env python3
"""
브라우저를 실행하여 다운로드 페이지의 JavaScript 오류를 디버깅
"""

from playwright.sync_api import sync_playwright
import time

def debug_downloads_page():
    with sync_playwright() as p:
        # 브라우저 실행 (headless=False로 실제 브라우저 창 표시)
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        
        # 콘솔 메시지 캡처
        page = context.new_page()
        
        # 콘솔 로그 이벤트 리스너
        page.on("console", lambda msg: print(f"[{msg.type}] {msg.text}"))
        
        # 페이지 오류 이벤트 리스너
        page.on("pageerror", lambda err: print(f"[ERROR] {err}"))
        
        print("다운로드 페이지로 이동 중...")
        page.goto("http://localhost:40732/dashboard/downloads/")
        
        # 페이지 로드 대기
        page.wait_for_load_state("networkidle")
        
        print("\n페이지 소스에서 오류 위치 확인:")
        
        # HTML 소스 가져오기
        content = page.content()
        lines = content.split('\n')
        
        # 516번째 줄 근처 확인
        print("\n=== 516번 줄 근처 ===")
        for i in range(max(0, 515-5), min(len(lines), 516+5)):
            prefix = ">>> " if i == 515 else "    "
            print(f"{prefix}{i+1}: {lines[i][:100]}")
        
        # retryDownload 함수가 정의되어 있는지 확인
        print("\n=== retryDownload 함수 검색 ===")
        js_check = """
        () => {
            return {
                retryDownload: typeof retryDownload !== 'undefined',
                forceDownload: typeof forceDownload !== 'undefined',
                app: typeof app !== 'undefined',
                appMethods: typeof app !== 'undefined' ? Object.keys(app).join(', ') : 'app not defined'
            };
        }
        """
        result = page.evaluate(js_check)
        print(f"JavaScript 함수 상태: {result}")
        
        # 10초 대기 (수동 디버깅용)
        print("\n브라우저에서 직접 확인 중... (10초 대기)")
        time.sleep(10)
        
        browser.close()

if __name__ == "__main__":
    debug_downloads_page()