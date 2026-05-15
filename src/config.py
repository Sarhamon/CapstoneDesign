"""
config.py
런타임 설정 관리
- 환경 변수 또는 .env 파일로 재정의 가능 (우선순위: 환경 변수 > .env > 코드 기본값)
- 블랙리스트/화이트리스트는 data/*.yaml 에서 로드 (env 비관리)
"""

import yaml
from pathlib import Path
from typing import Annotated, ClassVar
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

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


class Config(BaseSettings):
    """
    FocusGuard 애플리케이션 전역 설정.

    우선순위: 환경 변수 > .env 파일 > 코드 기본값
    실행 환경에 맞게 .env 파일을 생성하거나 환경 변수를 설정한다.
    (.env.example 참고)
    """

    model_config = SettingsConfigDict(
        env_file=_BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── HTTP 서버 ──────────────────────────────────────────────────────────────
    WEB_AUTH_PORT: Annotated[int, Field(ge=1, le=65535)] = 8080         # 해제 인증 서버 포트

    # ── 해제 코드 ──────────────────────────────────────────────────────────────
    UNLOCK_CODE_TTL: Annotated[int, Field(gt=0)] = 120                  # 코드 유효 시간 (초)
    UNLOCK_CODE_LENGTH: Annotated[int, Field(ge=4, le=12)] = 6          # 코드 자릿수
    UNLOCK_MAX_FAILED_ATTEMPTS: Annotated[int, Field(ge=1)] = 5         # 연속 실패 허용 횟수

    # ── 기능 플래그 ────────────────────────────────────────────────────────────
    KEYBOARD_BLOCK_ENABLED: bool = False                                 # 오버레이 중 키보드 전체 차단
    USE_CLOUD_LLM: bool = False                                          # True 시 CloudLLMClient 사용

    # ── 폴링 ───────────────────────────────────────────────────────────────────
    FAST_POLL_INTERVAL: Annotated[float, Field(gt=0)] = 1.0             # 포커스 창 변경 감지 주기 (초)
    POLL_INTERVAL: Annotated[float, Field(gt=0)] = 12.0                 # OCR 포함 전체 검사 주기 (초)

    # ── OCR ────────────────────────────────────────────────────────────────────
    OCR_CONFIDENCE_THRESHOLD: Annotated[float, Field(ge=0.0, le=1.0)] = 0.6    # 본문 OCR 신뢰도 임계값
    URL_OCR_CONFIDENCE_THRESHOLD: Annotated[float, Field(ge=0.0, le=1.0)] = 0.35  # URL 영역 OCR 신뢰도
    URL_ZONE_RATIO: Annotated[float, Field(ge=0.0, le=1.0)] = 0.12              # URL 영역 높이 비율 (0~12%)
    KEYWORD_THRESHOLD: Annotated[int, Field(ge=1)] = 2                          # LLM 검증 트리거 최소 키워드 수

    # ── Ollama ─────────────────────────────────────────────────────────────────
    OLLAMA_HOST: str = "http://localhost:11434"                          # Ollama API 서버 주소
    OLLAMA_MODEL: str = "gemma3:4b"                                      # 사용할 Ollama 모델명
    LLM_TIMEOUT: Annotated[int, Field(gt=0)] = 60                       # Ollama 응답 타임아웃 (초)

    # ── 경로 (env 비관리 — 소스 파일 위치 기반) ───────────────────────────────
    BASE_DIR: ClassVar[Path] = _BASE_DIR
    LOG_DIR: ClassVar[Path] = _BASE_DIR / "logs"

    # ── 블랙리스트 / 화이트리스트 (YAML 로드, env 비관리) ──────────────────────
    # 정확 일치 조회 → 소문자 변환 후 set (O(1) 조회)
    PROCESS_BLACKLIST: ClassVar[set]  = {p.lower() for p in _blacklists.get("process", [])}
    PROCESS_WHITELIST: ClassVar[set]  = {p.lower() for p in _whitelists.get("process", [])}
    # 부분 문자열 조회 → 소문자 변환 list (루프마다 .lower() 호출 제거)
    TITLE_BLACKLIST:   ClassVar[list] = [t.lower() for t in _blacklists.get("title", [])]
    URL_BLACKLIST:     ClassVar[list] = [u.lower() for u in _blacklists.get("url", [])]
    CONTENT_KEYWORDS:  ClassVar[list] = [k.lower() for k in _blacklists.get("content_keywords", [])]
    URL_WHITELIST:     ClassVar[list] = [u.lower() for u in _whitelists.get("url", [])]


# 앱 전역에서 사용하는 단일 설정 인스턴스
config = Config()


def reload_lists() -> None:
    """YAML 파일을 다시 읽어 Config ClassVar를 갱신한다 (관리자 페이지에서 목록 변경 시 호출)."""
    global _blacklists, _whitelists
    _blacklists = _load_yaml("blacklists.yaml")
    _whitelists = _load_yaml("whitelists.yaml")
    Config.PROCESS_BLACKLIST = {p.lower() for p in _blacklists.get("process", [])}
    Config.PROCESS_WHITELIST = {p.lower() for p in _whitelists.get("process", [])}
    Config.TITLE_BLACKLIST   = [t.lower() for t in _blacklists.get("title", [])]
    Config.URL_BLACKLIST     = [u.lower() for u in _blacklists.get("url", [])]
    Config.CONTENT_KEYWORDS  = [k.lower() for k in _blacklists.get("content_keywords", [])]
    Config.URL_WHITELIST     = [u.lower() for u in _whitelists.get("url", [])]
