"""
config.py
전체 설정값 중앙 관리
- 런타임 설정(포트, 타임아웃 등)은 이 파일에서 관리
- 블랙리스트/화이트리스트는 data/blacklists.yaml, data/whitelists.yaml 에서 관리
"""

import yaml
from pathlib import Path

_BASE_DIR = Path(__file__).resolve().parent.parent
_DATA_DIR = _BASE_DIR / "data"


def _load_yaml(filename: str) -> dict:
    """data/ 디렉토리의 YAML 파일을 읽어 dict로 반환한다. 파일이 없으면 빈 dict."""
    path = _DATA_DIR / filename
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# 앱 시작 시 한 번 로드; Config 클래스 변수에 주입된다
_blacklists = _load_yaml("blacklists.yaml")
_whitelists = _load_yaml("whitelists.yaml")


class Config:
    """
    FocusGuard 애플리케이션 전역 설정 클래스.

    모든 설정값은 클래스 변수로 선언되어 인스턴스 생성 없이 Config.변수명으로 접근한다.
    블랙리스트/화이트리스트 목록은 data/*.yaml 에서 로드되므로
    앱을 재시작하지 않고 yaml 파일만 수정해도 다음 실행 시 반영된다.
    """

    WEB_AUTH_PORT: int = 8080  # 해제 인증 HTTP 서버 바인드 포트

    UNLOCK_CODE_TTL: int = 120  # 해제 코드 유효 시간 (초); 만료 시 자동 무효화

    UNLOCK_CODE_LENGTH: int = 6  # 해제 코드 자릿수 (숫자)

    UNLOCK_MAX_FAILED_ATTEMPTS: int = 5  # 연속 실패 허용 횟수; 초과 시 코드 무효화

    KEYBOARD_BLOCK_ENABLED: bool = False  # True 시 오버레이 활성화 중 키보드 전체 차단

    USE_CLOUD_LLM: bool = False  # True 로 바꾸면 LocalLLMClient 대신 CloudLLMClient 사용

    FAST_POLL_INTERVAL: float = 1.0  # 포커스 창 변경 감지 폴링 주기 (초)

    POLL_INTERVAL: float = 12.0  # OCR 포함 전체 탐지 검사 주기 (초)

    OCR_CONFIDENCE_THRESHOLD: float = 0.6  # 본문 OCR 신뢰도 임계값 (이 값 미만은 무시)

    URL_OCR_CONFIDENCE_THRESHOLD: float = 0.35  # URL 영역 OCR 신뢰도; 더 낮게 설정해 작은 텍스트도 포착

    URL_ZONE_RATIO: float = 0.12  # URL 영역 높이 비율 (화면 상단 0 ~ 12%)

    KEYWORD_THRESHOLD: int = 2  # LLM 검증 트리거 최소 키워드 감지 수

    OLLAMA_HOST: str = "http://localhost:11434"  # Ollama API 서버 주소

    OLLAMA_MODEL: str = "gemma3:4b"  # 사용할 Ollama 모델명

    LLM_TIMEOUT: int = 60  # Ollama API 응답 타임아웃 (초)

    BASE_DIR: Path = _BASE_DIR
    LOG_DIR: Path = _BASE_DIR / "logs"  # 로그 파일 저장 경로 (프로젝트 루트/logs)

    # data/blacklists.yaml 에서 로드
    PROCESS_BLACKLIST: list = _blacklists.get("process", [])
    TITLE_BLACKLIST: list = _blacklists.get("title", [])
    URL_BLACKLIST: list = _blacklists.get("url", [])
    CONTENT_KEYWORDS: list = _blacklists.get("content_keywords", [])

    # data/whitelists.yaml 에서 로드
    PROCESS_WHITELIST: list = _whitelists.get("process", [])
    URL_WHITELIST: list = _whitelists.get("url", [])
