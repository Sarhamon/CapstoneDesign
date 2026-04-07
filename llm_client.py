"""
llm_client.py
LLM 추상화 레이어
- 현재: LocalLLMClient (Ollama)
- 추후: CloudLLMClient (Anthropic / OpenAI) 로 교체
"""

import re
import logging
import requests
from abc import ABC, abstractmethod
from config import Config

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# 추상 베이스
# ──────────────────────────────────────────────────────────────

class LLMClient(ABC):
    """
    반환값: "BLOCK" | "ALLOW" | "UNSURE"
    """

    @abstractmethod
    def analyze(self, window_title: str, url_text: str, ocr_text: str) -> str:
        pass


# ──────────────────────────────────────────────────────────────
# 로컬 Ollama (현재 사용)
# ──────────────────────────────────────────────────────────────

class LocalLLMClient(LLMClient):
    SYSTEM_PROMPT = """당신은 수업 방해 콘텐츠를 판단하는 분류기입니다.
입력된 정보를 보고 아래 중 하나만 출력하세요.

BLOCK: 게임, 유튜브 오락 영상, 커뮤니티, SNS, 쇼핑, 스트리밍
ALLOW: 수업 자료, 코딩, 문서 작성, 학술 검색, 교육 영상
UNSURE: 판단 불가

반드시 BLOCK, ALLOW, UNSURE 중 하나만 출력하세요. 다른 말은 절대 하지 마세요."""

    def analyze(self, window_title: str, url_text: str, ocr_text: str) -> str:
        user_msg = f"""창 제목: {window_title or '없음'}
URL: {url_text or '없음'}
화면 텍스트: {ocr_text[:500] if ocr_text else '없음'}"""

        payload = {
            "model": Config.OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "stream": False,
            "options": {
                "temperature": 0.0,   # 일관된 판단을 위해 temperature 0
                "num_predict": 10,    # 짧은 응답 강제
            },
        }

        try:
            resp = requests.post(
                f"{Config.OLLAMA_HOST}/api/chat",
                json=payload,
                timeout=Config.LLM_TIMEOUT,
            )
            resp.raise_for_status()
            raw = resp.json()["message"]["content"].strip().upper()
            return self._parse_response(raw)

        except requests.exceptions.Timeout:
            logger.warning("LLM 응답 타임아웃 → UNSURE 처리")
            return "UNSURE"
        except Exception as e:
            logger.error(f"LLM 호출 오류: {e}")
            return "UNSURE"

    def _parse_response(self, raw: str) -> str:
        """응답에서 BLOCK / ALLOW / UNSURE 추출 (소형 LLM 포맷 불안정 대응)"""
        for keyword in ["BLOCK", "ALLOW", "UNSURE"]:
            if keyword in raw:
                return keyword
        logger.warning(f"LLM 응답 파싱 실패: '{raw}' → UNSURE 처리")
        return "UNSURE"

    def warmup(self):
        """앱 시작 시 모델 로딩 워밍업"""
        logger.info(f"LLM 워밍업 중... (모델: {Config.OLLAMA_MODEL})")
        try:
            self.analyze("warmup", "", "")
            logger.info("LLM 워밍업 완료")
        except Exception as e:
            logger.error(f"LLM 워밍업 실패: {e}")


# ──────────────────────────────────────────────────────────────
# 클라우드 LLM (4월 말 이후 전환)
# ──────────────────────────────────────────────────────────────

class CloudLLMClient(LLMClient):
    """
    TODO: 클라우드 계약 이후 구현
    - Anthropic Claude API 또는 OpenAI API 연동 예정
    - LocalLLMClient와 동일한 인터페이스 유지
    """

    def analyze(self, window_title: str, url_text: str, ocr_text: str) -> str:
        raise NotImplementedError("클라우드 LLM은 4월 말 이후 구현 예정")


# ──────────────────────────────────────────────────────────────
# 팩토리 함수 — main.py에서 이 한 줄만 바꾸면 전환 완료
# ──────────────────────────────────────────────────────────────

def get_llm_client() -> LLMClient:
    if Config.USE_CLOUD_LLM:
        return CloudLLMClient()
    return LocalLLMClient()