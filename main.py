"""
main.py
FocusGuard 메인 컨트롤러
- Tkinter를 메인 스레드에서 실행 (Tcl_AsyncDelete 오류 해결)
- Queue로 스레드 간 UI 이벤트 전달
- TITLE/PROCESS/URL 매칭은 LLM 생략 → 즉시 차단
"""

import os
import logging
import sys
import threading
import time
import queue
import numpy as np
import psutil

os.makedirs("logs", exist_ok=True)

from config import Config
from monitor import ScreenMonitor
from llm_client import get_llm_client, LocalLLMClient
from overlay import BlockOverlay
from event_logger import EventLogger
from web_auth import WebAuthServer

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/focus_guard.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("main")


class FocusGuard:
    """
    FocusGuard 애플리케이션 최상위 컨트롤러.

    스레드 구조:
        메인 스레드  — Tkinter UI 루프 (BlockOverlay.run_mainloop)
        모니터 스레드 — ScreenMonitor 폴링 루프 (daemon)
        LLM 스레드   — LLM 검증 호출 (daemon, 키워드 탐지 시에만 생성)

    이벤트 흐름:
        ScreenMonitor._check()
            → 규칙 기반 탐지(TITLE/URL) → _on_detect() → _smart_kill_target() + UI 큐
            → 키워드 탐지(KEYWORD)       → _on_detect() → _llm_verify() (별도 스레드)
                → LLM BLOCK → _smart_kill_target() + UI 큐
                → LLM ALLOW/UNSURE → EventLogger.log_allow()
    """

    def __init__(self):
        self.event_logger = EventLogger()           # 이벤트 기록기
        self.llm = get_llm_client()                 # LLM 클라이언트 (로컬 or 클라우드)
        self._ui_queue = queue.Queue()              # 모니터↔UI 간 이벤트 전달 큐

        # 웹 기반 해제 인증 서버 (LAN 내 교수자 폰에서 QR 스캔으로 접근).
        # WebAuthServer 콜백은 별도 스레드에서 호출되므로 ui_queue로 메인 스레드에 마샬링한다.
        self.web_auth = WebAuthServer(port=Config.WEB_AUTH_PORT)
        self.web_auth.set_on_success(lambda: self._ui_queue.put(("web-unlock",)))

        self.overlay = BlockOverlay(
            on_unlock_callback=self._on_unlock,
            ui_queue=self._ui_queue,
            web_auth_server=self.web_auth,
        )
        self.monitor = ScreenMonitor(on_detect_callback=self._on_detect)
        # LLM 검증이 동시에 여러 번 실행되지 않도록 직렬화하는 잠금.
        # 오버레이가 표시된 상태에서 중복 차단 처리를 방지한다.
        self._llm_lock = threading.Lock()

    # ──────────────────────────────────────────
    # 시작
    # ──────────────────────────────────────────

    def run(self):
        """
        FocusGuard를 시작한다.

        1. 로컬 LLM이면 warmup()으로 모델을 메모리에 미리 적재한다.
        2. ScreenMonitor 백그라운드 스레드를 시작한다.
        3. Tkinter 메인 루프를 실행한다 (종료 시까지 블로킹).
        """
        logger.info("=" * 50)
        logger.info("FocusGuard 시작")
        logger.info(f"모드: {'클라우드' if Config.USE_CLOUD_LLM else '로컬'} LLM")
        logger.info(f"모델: {Config.OLLAMA_MODEL}")
        logger.info("=" * 50)

        # 로컬 LLM 사용 시 첫 요청 지연을 줄이기 위해 워밍업을 실행한다.
        if not Config.USE_CLOUD_LLM and isinstance(self.llm, LocalLLMClient):
            self.llm.warmup()

        # LAN HTTP 서버 시작 — 학생 PC가 0.0.0.0:WEB_AUTH_PORT 에서 listen 한다.
        self.web_auth.start()

        self.monitor.start()
        # run_mainloop()은 Tkinter 루프가 종료될 때까지 반환되지 않는다.
        self.overlay.run_mainloop(self._ui_queue)

    # ──────────────────────────────────────────
    # 탐지 콜백
    # ──────────────────────────────────────────

    def _on_detect(self, stage: str, reason: str, screenshot: np.ndarray,
                   target_hwnd: int | None, target_pid: int | None):
        """
        ScreenMonitor에서 탐지 이벤트 발생 시 호출되는 콜백.

        규칙 기반 탐지(TITLE/URL)는 LLM을 생략하고 즉시 차단한다.
        콘텐츠 키워드 탐지(KEYWORD)는 별도 스레드에서 LLM 검증을 수행한다.

        오버레이가 이미 표시 중이면 중복 처리를 막고 즉시 반환한다.

        Args:
            stage:       탐지 단계 ("TITLE_MATCH" | "URL_MATCH" | "KEYWORD_MATCH").
            reason:      탐지 사유 문자열.
            screenshot:  탐지 시점의 화면 캡처 이미지 (현재 로그에 미사용).
            target_hwnd: 탐지 시점 포커스 창 핸들.
            target_pid:  탐지 시점 포커스 창의 프로세스 ID.
        """
        # 화이트리스트 텍스트가 reason에 포함된 경우 차단하지 않는다.
        if self._is_whitelisted(reason):
            logger.info(f"화이트리스트 통과: {reason}")
            return

        # 오버레이가 이미 활성화되어 있으면 추가 처리를 하지 않는다.
        if self.overlay.is_active:
            return

        # ── 확실한 탐지: LLM 생략하고 즉시 차단 ──
        if stage in ("TITLE_MATCH", "PROCESS_MATCH", "URL_MATCH"):
            logger.info(f"즉시 차단 ({stage}): {reason}")
            self.event_logger.log_block(stage, reason, "RULE_BASED")
            self._smart_kill_target(target_hwnd, target_pid)
            # UI 큐에 show 이벤트를 넣으면 메인 스레드의 Tkinter가 오버레이를 표시한다.
            self._ui_queue.put(("show", reason))
            return

        # ── 키워드 조합 탐지만 LLM 검증 ──
        threading.Thread(
            target=self._llm_verify,
            args=(stage, reason, screenshot, target_hwnd, target_pid),
            daemon=True,
        ).start()

    def _llm_verify(self, stage: str, reason: str, screenshot: np.ndarray,
                    target_hwnd: int | None, target_pid: int | None):
        """
        LLM을 호출하여 콘텐츠 키워드 탐지 결과를 검증한다.

        _llm_lock으로 직렬화하여 동시에 여러 LLM 요청이 실행되지 않도록 한다.
        잠금 획득 후 오버레이가 이미 활성화되어 있으면 처리를 취소한다.

        LLM 결과:
            BLOCK  → 프로세스 종료 + 오버레이 표시
            ALLOW  → 허용 이벤트 기록
            UNSURE → 경고 로그 후 통과 처리

        Args:
            stage, reason, screenshot, target_hwnd, target_pid:
                _on_detect()에서 전달된 탐지 정보.
        """
        with self._llm_lock:
            # 잠금 대기 중 다른 스레드가 오버레이를 표시했을 수 있다.
            if self.overlay.is_active:
                return

            logger.info(f"LLM 검증 시작: {stage} | {reason}")
            llm_result = self.llm.analyze(
                window_title=reason,
                url_text="",
                ocr_text=reason,
            )

            if llm_result == "BLOCK":
                self.event_logger.log_block(stage, reason, llm_result)
                self._smart_kill_target(target_hwnd, target_pid)
                self._ui_queue.put(("show", reason))

            elif llm_result == "UNSURE":
                # UNSURE는 판단 불가이므로 차단하지 않고 허용으로 처리한다.
                logger.warning(f"LLM UNSURE → 통과 처리: {reason}")
                self.event_logger.log_allow(reason)

            else:
                # ALLOW
                self.event_logger.log_allow(reason)

    # ──────────────────────────────────────────
    # 해제 콜백
    # ──────────────────────────────────────────

    def _on_unlock(self, block_reason: str):
        """
        overlay.py에서 웹 기반 해제 인증 성공 시 호출되는 콜백.

        해제 이벤트를 로그에 기록한다. 오버레이 숨김은 overlay.py 내부에서 처리된다.

        Args:
            block_reason: 해제된 차단의 원인 사유 문자열.
        """
        self.event_logger.log_unlock_request(block_reason, "웹 인증 성공")
        logger.info(f"[차단 해제] {block_reason}")

    # ──────────────────────────────────────────
    # 프로세스 강제 종료
    # ──────────────────────────────────────────

    def _smart_kill_target(self, hwnd: int | None, pid: int | None):
        """
        탐지된 창/프로세스를 종류에 따라 적절하게 종료한다.

        브라우저(Chrome / Edge / Whale / Firefox):
            WM_CLOSE 메시지로 해당 탭/창만 닫는다.
            kill()보다 안전하며 다른 탭에 영향을 주지 않는다.

        그 외 프로세스:
            psutil.terminate()로 종료 신호를 전송한다.

        Python 프로세스는 자기 자신(FocusGuard)일 수 있으므로 종료를 차단한다.

        Args:
            hwnd: 종료할 창 핸들. None이면 처리를 건너뛴다.
            pid:  종료할 프로세스 ID. None이면 처리를 건너뛴다.
        """
        if not hwnd or not pid:
            logger.warning("종료할 대상 정보가 부족합니다.")
            return

        try:
            import win32gui
            import win32con
            proc = psutil.Process(pid)
            proc_name = proc.name().lower()

            # FocusGuard 자신이 Python으로 실행 중이므로 Python 프로세스는 종료하지 않는다.
            if "python" in proc_name:
                logger.warning(f"Python 프로세스 종료 차단: {proc_name}")
                return

            browser_list = ["chrome.exe", "msedge.exe", "whale.exe", "firefox.exe"]

            if any(b in proc_name for b in browser_list):
                # 브라우저는 WM_CLOSE로 해당 창만 닫는다 (다른 탭 유지).
                logger.info(f"[브라우저 창 닫기] {proc_name} (HWND: {hwnd})")
                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                self.event_logger.log_block("WINDOW_CLOSE", f"{proc_name} (HWND {hwnd})")
            else:
                # 게임 클라이언트 등 일반 프로세스는 terminate()로 종료한다.
                proc.terminate()
                logger.info(f"[프로세스 종료] {proc_name} (PID {pid})")
                self.event_logger.log_block("PROCESS_KILL", f"{proc_name} (PID {pid})")

        except psutil.NoSuchProcess:
            # 탐지와 종료 시도 사이에 사용자가 직접 닫은 경우.
            logger.info("대상 프로세스가 이미 닫혔습니다.")
        except Exception as e:
            logger.error(f"종료 처리 중 오류: {e}")

    # ──────────────────────────────────────────
    # 화이트리스트
    # ──────────────────────────────────────────

    def _is_whitelisted(self, text: str) -> bool:
        """
        탐지 사유 문자열에 URL_WHITELIST 항목이 포함되어 있는지 확인한다.

        monitor.py의 _is_whitelisted()와 달리 이 메서드는 포맷된 reason 문자열을
        검사한다. 화이트리스트 주소가 reason 문자열 안에 있으면 차단을 취소한다.

        Args:
            text: 확인할 사유 문자열.

        Returns:
            화이트리스트 항목이 포함되어 있으면 True, 아니면 False.
        """
        return any(wl.lower() in text.lower() for wl in Config.URL_WHITELIST)


if __name__ == "__main__":
    FocusGuard().run()
