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
    LLM 클라이언트 공통 인터페이스.

    로컬(Ollama)과 클라우드(Anthropic / OpenAI) 구현체를 동일한 인터페이스로
    교체할 수 있도록 추상화한다.

    반환값 규격:
        "BLOCK"  — 수업 방해 콘텐츠로 판단, 즉시 차단
        "ALLOW"  — 수업 관련 콘텐츠로 판단, 허용
        "UNSURE" — 판단 불가, 차단하지 않고 통과
    """

    @abstractmethod
    def analyze(self, window_title: str, url_text: str, ocr_text: str) -> str:
        """
        화면 정보를 분석하여 차단 여부를 반환한다.

        Args:
            window_title: 활성 창 제목 또는 탐지 사유 문자열.
            url_text:     화면 상단 URL 표시줄 영역의 OCR 텍스트.
            ocr_text:     화면 본문 영역의 OCR 텍스트 (최대 500자).

        Returns:
            "BLOCK" | "ALLOW" | "UNSURE"
        """
        pass


# ──────────────────────────────────────────────────────────────
# 로컬 Ollama (현재 사용)
# ──────────────────────────────────────────────────────────────

class LocalLLMClient(LLMClient):
    """
    Ollama 로컬 서버를 통해 LLM을 호출하는 클라이언트.

    Ollama가 localhost에서 실행 중이어야 하며, Config.OLLAMA_MODEL에 지정된
    모델이 사전에 pull되어 있어야 한다.
    temperature=0.0으로 설정하여 매번 동일한 판단을 유도한다.
    """

    # LLM에게 전달하는 시스템 역할 지시문.
    # 반드시 BLOCK / ALLOW / UNSURE 세 단어 중 하나만 출력하도록 강제한다.
    SYSTEM_PROMPT = """당신은 수업 중 학생 화면의 콘텐츠를 분류하는 판단기입니다.
명백한 차단 대상(게임 런처, SNS 앱 등)은 이미 걸러진 상태이므로,
당신에게 오는 입력은 규칙만으로 판단하기 어려운 애매한 케이스입니다.
창 제목, URL, 화면 텍스트를 종합 분석하여 아래 셋 중 하나만 출력하세요.

BLOCK — 수업 방해 콘텐츠
- 오락 영상: 유튜브 예능·음악·게임 방송, 영화·드라마 스트리밍
- 게임: 게임 플레이 화면, 공략·리뷰 사이트, 게임 전용 커뮤니티
- SNS·커뮤니티: 인스타그램, 페이스북, 틱톡, 디시인사이드, 에펨코리아 등
- 쇼핑: 상품 검색, 장바구니, 결제 페이지
- 웹툰·웹소설

ALLOW — 수업 관련 콘텐츠
- 코딩·개발: IDE, 터미널, 개발 공식 문서, 오류 디버깅, 기술 Q&A (화면에 코드·오류 메시지 포함)
- 수업 자료: PDF 뷰어, PPT, 교재, LMS 강의 페이지
- 문서 작성: 워드, 한글, 노션, 구글 문서, 마크다운 편집기
- 학술 검색: 논문 사이트, 백과사전, 학술 자료
- 교육 영상: 창 제목·채널명에 '강의', 'lecture', 'tutorial', '수업', '강좌' 키워드 포함

UNSURE — 판단 불가 (차단하지 않고 통과)
- URL·창 제목·화면 텍스트 모두로도 목적을 특정할 수 없는 경우
- 학습과 오락 모두에 쓰이는 도구 (예: Discord, Telegram, Slack)
- 검색 결과 페이지에서 검색어가 보이지 않는 경우

판단 우선순위: URL > 창 제목 > 화면 텍스트
유튜브는 창 제목·채널명에 교육 키워드가 있으면 ALLOW, 없으면 BLOCK.

반드시 BLOCK, ALLOW, UNSURE 중 하나만 출력하세요. 다른 말은 절대 하지 마세요."""

    def analyze(self, window_title: str, url_text: str, ocr_text: str) -> str:
        """
        Ollama /api/chat 엔드포인트를 호출하여 차단 여부를 판단한다.

        타임아웃 또는 네트워크 오류 발생 시 UNSURE를 반환하여 오탐(차단 누락)보다
        미탐(허용)을 선택한다. 소형 LLM의 불안정한 출력 형식은 _parse_response()로
        보정한다.

        Args:
            window_title: 창 제목 또는 탐지 사유.
            url_text:     URL 영역 OCR 텍스트.
            ocr_text:     본문 영역 OCR 텍스트.

        Returns:
            "BLOCK" | "ALLOW" | "UNSURE"
        """
        # LLM에 전달할 사용자 메시지를 구성한다.
        user_msg = f"""창 제목: {window_title or '없음'}
URL: {url_text or '없음'}
화면 텍스트: {ocr_text[:500] if ocr_text else '없음'}"""

        payload = {
            "model": Config.OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "stream": False,          # 스트리밍 비활성화 — 응답 전체를 한 번에 수신한다.
            "options": {
                "temperature": 0.0,   # 0으로 고정하여 매번 동일한 판단을 보장한다.
                "num_predict": 10,    # 짧은 응답(BLOCK/ALLOW/UNSURE)만 생성하도록 제한한다.
            },
        }

        try:
            resp = requests.post(
                f"{Config.OLLAMA_HOST}/api/chat",
                json=payload,
                timeout=Config.LLM_TIMEOUT,
            )
            resp.raise_for_status()
            # 응답 본문에서 LLM이 생성한 텍스트를 추출하고 대문자로 정규화한다.
            raw = resp.json()["message"]["content"].strip().upper()
            return self._parse_response(raw)

        except requests.exceptions.Timeout:
            # LLM 응답이 늦을 경우 차단하지 않고 통과시킨다.
            logger.warning("LLM 응답 타임아웃 → UNSURE 처리")
            return "UNSURE"
        except Exception as e:
            logger.error(f"LLM 호출 오류: {e}")
            return "UNSURE"

    def _parse_response(self, raw: str) -> str:
        """
        LLM 응답 문자열에서 BLOCK / ALLOW / UNSURE 키워드를 추출한다.

        소형 LLM은 지시를 어기고 "I think this is BLOCK because..."처럼
        문장으로 답할 수 있으므로, 부분 문자열 검색으로 키워드를 탐색한다.
        어떤 키워드도 없으면 UNSURE로 fallback한다.

        Args:
            raw: 대문자로 정규화된 LLM 출력 문자열.

        Returns:
            "BLOCK" | "ALLOW" | "UNSURE"
        """
        for keyword in ["BLOCK", "ALLOW", "UNSURE"]:
            if keyword in raw:
                return keyword
        logger.warning(f"LLM 응답 파싱 실패: '{raw}' → UNSURE 처리")
        return "UNSURE"

    def warmup(self):
        """
        앱 시작 시 Ollama 모델을 미리 메모리에 로드한다.

        첫 번째 실제 분석 요청의 응답 지연을 줄이기 위해 더미 입력으로
        모델을 한 번 호출한다. main.py의 run()에서 USE_CLOUD_LLM=False일 때만 실행된다.
        """
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
    클라우드 LLM API를 사용하는 클라이언트 (미구현).

    Config.USE_CLOUD_LLM = True로 설정 시 get_llm_client()가 이 클래스를 반환한다.
    LocalLLMClient와 동일한 analyze() 인터페이스를 구현해야 한다.

    TODO: Anthropic Claude API 또는 OpenAI API 연동 예정
    """

    def analyze(self, window_title: str, url_text: str, ocr_text: str) -> str:
        raise NotImplementedError("클라우드 LLM은 4월 말 이후 구현 예정")


# ──────────────────────────────────────────────────────────────
# 팩토리 함수 — main.py에서 이 한 줄만 바꾸면 전환 완료
# ──────────────────────────────────────────────────────────────

def get_llm_client() -> LLMClient:
    """
    Config.USE_CLOUD_LLM 값에 따라 적절한 LLMClient 구현체를 반환한다.

    로컬/클라우드 전환 시 이 함수 하나만 수정하면 되도록 설계되었다.

    Returns:
        LocalLLMClient (USE_CLOUD_LLM=False) 또는
        CloudLLMClient (USE_CLOUD_LLM=True)
    """
    if Config.USE_CLOUD_LLM:
        return CloudLLMClient()
    return LocalLLMClient()
