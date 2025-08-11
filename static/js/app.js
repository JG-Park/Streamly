/**
 * Streamly 통합 JavaScript 앱
 */

class StreamlyApp {
    constructor() {
        this.apiBase = '/api/v1';
        this.csrfToken = this.getCsrfToken();
        this.init();
    }

    init() {
        // CSRF 토큰 설정
        this.setupAjaxDefaults();
        
        // 토스트 컨테이너 초기화
        this.initToastContainer();
        
        // 전역 이벤트 리스너
        this.bindGlobalEvents();
    }

    getCsrfToken() {
        // Django CSRF 토큰 가져오기
        const token = document.querySelector('[name=csrfmiddlewaretoken]');
        if (token) return token.value;
        
        // 쿠키에서 가져오기
        const cookieValue = document.cookie
            .split('; ')
            .find(row => row.startsWith('csrftoken='))
            ?.split('=')[1];
        
        return cookieValue || window.CSRF_TOKEN || '';
    }

    setupAjaxDefaults() {
        // Fetch API 기본 설정
        window.fetchWithAuth = (url, options = {}) => {
            const defaultOptions = {
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.csrfToken,
                    ...options.headers
                },
                credentials: 'same-origin'
            };

            return fetch(url, { ...defaultOptions, ...options });
        };
    }

    initToastContainer() {
        if (!document.getElementById('toast-container')) {
            const container = document.createElement('div');
            container.id = 'toast-container';
            container.className = 'toast toast-end';
            document.body.appendChild(container);
        }
    }

    bindGlobalEvents() {
        // 전역 키보드 단축키
        document.addEventListener('keydown', (e) => {
            // Ctrl/Cmd + K: 검색
            if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
                e.preventDefault();
                this.openSearch();
            }
        });
    }

    // API 헬퍼 메서드
    async apiRequest(method, endpoint, data = null) {
        const options = {
            method: method,
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.csrfToken
            },
            credentials: 'same-origin'
        };

        if (data && method !== 'GET') {
            options.body = JSON.stringify(data);
        }

        try {
            const response = await fetch(`${this.apiBase}${endpoint}`, options);
            const result = await response.json();
            
            if (!response.ok) {
                throw new Error(result.error || result.detail || 'API 요청 실패');
            }
            
            return result;
        } catch (error) {
            console.error('API Error:', error);
            this.showToast('error', error.message);
            throw error;
        }
    }

    // 토스트 메시지
    showToast(type, message, duration = 3000) {
        const toast = document.createElement('div');
        toast.className = `alert alert-${type === 'success' ? 'success' : type === 'error' ? 'error' : 'info'}`;
        
        const icon = type === 'success' ? 'check-circle' : 
                     type === 'error' ? 'x-circle' : 'info-circle';
        
        toast.innerHTML = `
            <svg class="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                <path fill-rule="evenodd" d="${this.getIconPath(icon)}" clip-rule="evenodd"/>
            </svg>
            <span>${message}</span>
        `;
        
        const container = document.getElementById('toast-container');
        container.appendChild(toast);
        
        setTimeout(() => {
            toast.style.animation = 'fadeOut 0.3s';
            setTimeout(() => toast.remove(), 300);
        }, duration);
    }

    getIconPath(icon) {
        const paths = {
            'check-circle': 'M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z',
            'x-circle': 'M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z',
            'info-circle': 'M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z'
        };
        return paths[icon] || paths['info-circle'];
    }

    // 로딩 표시
    showLoading(element, show = true) {
        if (show) {
            element.innerHTML = '<div class="loading loading-spinner loading-lg"></div>';
        }
    }

    // 시간 포맷팅
    formatTime(date) {
        const now = new Date();
        const diff = (now - new Date(date)) / 1000;
        
        if (diff < 60) return '방금 전';
        if (diff < 3600) return `${Math.floor(diff / 60)}분 전`;
        if (diff < 86400) return `${Math.floor(diff / 3600)}시간 전`;
        if (diff < 604800) return `${Math.floor(diff / 86400)}일 전`;
        
        return new Date(date).toLocaleDateString('ko-KR');
    }

    // 파일 크기 포맷팅
    formatFileSize(bytes) {
        if (bytes === 0) return '0 B';
        
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

    // 검색 모달
    openSearch() {
        // TODO: 전역 검색 구현
        console.log('Search opened');
    }
}

// 앱 초기화
document.addEventListener('DOMContentLoaded', () => {
    window.app = new StreamlyApp();
});

// 전역 함수들 (레거시 지원)
function showToast(type, message) {
    if (window.app) {
        window.app.showToast(type, message);
    }
}