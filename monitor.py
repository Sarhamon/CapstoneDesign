"""
monitor.py
화면 캡처 + 창 타이틀 감지 + OCR 파이프라인
PaddleOCR → EasyOCR 로 교체
"""

import time
import threading
import logging
import mss
import numpy as np
import cv2
import pygetwindow as gw
import easyocr
import psutil
from config import Config

logger = logging.getLogger(__name__)


class ScreenMonitor:
    """
    백그라운드 스레드에서 주기적으로 화면을 감시하는 모니터.

    탐지 파이프라인 (3단계):
        1단계 — 창 타이틀 블랙리스트: Config.TITLE_BLACKLIST와 대소문자 무관 부분 일치.
                 일치 시 즉시 callback("TITLE_MATCH", ...) 호출.
        2단계 — URL 키워드 블랙리스트: 화면 상단 영역 OCR 후 Config.URL_BLACKLIST와 비교.
                 일치 시 즉시 callback("URL_MATCH", ...) 호출.
        3단계 — 콘텐츠 키워드: 화면 본문 영역 OCR 후 Config.CONTENT_KEYWORDS와 비교.
                 KEYWORD_THRESHOLD 개 이상 감지 시 callback("KEYWORD_MATCH", ...) 호출.
                 → main.py에서 LLM 검증을 거쳐 최종 차단 여부를 결정한다.

    화이트리스트(Config.URL_WHITELIST)에 포함된 텍스트가 감지되면
    블랙리스트 검사를 건너뛰고 허용한다.
    """

    def __init__(self, on_detect_callback):
        """
        Args:
            on_detect_callback: 탐지 시 호출할 콜백 함수.
                signature: (stage: str, reason: str, screenshot: np.ndarray,
                            target_hwnd: int | None, target_pid: int | None) -> None
        """
        self.callback = on_detect_callback

        # EasyOCR 모델 초기화 — 한국어(ko)와 영어(en)를 동시에 인식한다.
        # GPU 없이 CPU 모드로 실행하며, 첫 실행 시 모델 파일을 다운로드한다.
        logger.info("OCR 모델 초기화 중...")
        self.ocr = easyocr.Reader(["ko", "en"], gpu=False, verbose=False)
        logger.info("OCR 모델 초기화 완료")

        self.running = False          # 모니터링 루프 실행 여부 플래그
        self._thread = None           # 모니터링 백그라운드 스레드
        self._last_window_title = ""  # 직전 폴링 주기의 창 제목 (변경 감지용)

    def start(self):
        """모니터링 백그라운드 스레드를 시작한다."""
        self.running = True
        # daemon=True: 메인 스레드 종료 시 함께 종료되어 프로세스가 남지 않는다.
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("모니터링 시작")

    def stop(self):
        """모니터링 루프를 중지한다. 현재 폴링 주기가 끝난 후 스레드가 종료된다."""
        self.running = False
        logger.info("모니터링 중지")

    def _loop(self):
        """
        Config.POLL_INTERVAL 간격으로 _check()를 반복 호출하는 메인 루프.

        _check() 내부에서 예외가 발생해도 루프가 중단되지 않도록 try/except로 감싼다.
        """
        while self.running:
            try:
                self._check()
            except Exception as e:
                logger.error(f"모니터링 루프 오류: {e}")
            time.sleep(Config.POLL_INTERVAL)

    def _get_current_focus_info(self) -> tuple[int | None, int | None]:
        """
        현재 포커스된 창의 HWND(창 핸들)와 PID(프로세스 ID)를 반환한다.

        탐지 시점과 프로세스 종료 시점 사이에 포커스가 바뀔 수 있으므로,
        탐지 직전에 스냅샷을 찍어 정확한 대상을 특정하는 데 사용한다.

        Returns:
            (hwnd, pid) 튜플. 취득 실패 시 (None, None).
        """
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if not hwnd:
                return None, None
            pid = ctypes.c_ulong()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            return hwnd, pid.value
        except:
            return None, None

    def _get_process_name(self, pid: int | None) -> str:
        """PID로 실행 파일명(예: 'Code.exe')을 반환한다. 실패 시 ""."""
        if not pid:
            return ""
        try:
            return psutil.Process(pid).name()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return ""

    def _is_process_whitelisted(self, proc_name: str) -> bool:
        """프로세스명이 PROCESS_WHITELIST에 있으면 True (대소문자 무시)."""
        name_lower = proc_name.lower()
        return any(w.lower() == name_lower for w in Config.PROCESS_WHITELIST)

    def _check_process_blacklist(self, proc_name: str):
        """프로세스명이 PROCESS_BLACKLIST에 있으면 사유 문자열 반환, 없으면 None."""
        name_lower = proc_name.lower()
        for blocked in Config.PROCESS_BLACKLIST:
            if blocked.lower() == name_lower:
                return f"프로세스 블랙리스트 감지: '{proc_name}'"
        return None

    def _check(self):
        """
        한 번의 폴링 주기에서 수행되는 전체 탐지 파이프라인.

        단계별로 탐지 시 즉시 return하여 불필요한 OCR 호출을 줄인다.
        포커스 창 정보(hwnd, pid)는 탐지 직전에 스냅샷으로 기록하여,
        callback에서 정확한 프로세스를 종료할 수 있도록 전달한다.
        """
        # 검사 시작 시점의 포커스 창 정보를 스냅샷으로 기록한다.
        target_hwnd, target_pid = self._get_current_focus_info()

        # ── 0단계: 프로세스 화이트리스트 (최우선) ──
        # proc_name 취득 성공 여부와 무관하게 화이트리스트를 먼저 평가한다.
        proc_name = self._get_process_name(target_pid)
        if self._is_process_whitelisted(proc_name):
            logger.debug(f"프로세스 화이트리스트 통과: {proc_name}")
            return

        # ── 0단계: 프로세스 블랙리스트 ──
        # 프로세스명을 확인한 경우에만 블랙리스트와 대조한다.
        if proc_name:
            result = self._check_process_blacklist(proc_name)
            if result:
                screenshot = self._capture_screen()
                self.callback("PROCESS_MATCH", result, screenshot, target_hwnd, target_pid)
                return

        # ── 1단계: 창 타이틀 블랙리스트 검사 ──
        title = self._get_active_window_title()
        if title and title != self._last_window_title:
            logger.debug(f"활성 창: {title}")
            self._last_window_title = title

        # 화이트리스트에 포함된 창이면 모든 검사를 건너뛴다.
        if self._is_whitelisted(title):
            logger.debug(f"화이트리스트 통과 (타이틀): {title}")
            return

        result = self._check_window_title(title)
        if result:
            screenshot = self._capture_screen()
            # 창 타이틀 일치 → LLM 없이 즉시 차단 콜백 호출
            self.callback("TITLE_MATCH", result, screenshot, target_hwnd, target_pid)
            return

        # ── 2·3단계: OCR 기반 URL / 콘텐츠 키워드 검사 ──
        # OCR 캡처 직전에 포커스를 다시 스냅샷한다.
        # (타이틀 검사와 OCR 사이에 사용자가 창을 전환했을 수 있음)
        target_hwnd, target_pid = self._get_current_focus_info()
        screenshot = self._capture_screen()

        url_text, body_text = self._split_zones(screenshot)

        # URL/본문 텍스트가 화이트리스트에 포함되면 통과한다.
        if self._is_whitelisted(url_text) or self._is_whitelisted(body_text):
            logger.debug(f"화이트리스트 통과 (OCR): {url_text or body_text}")
            return

        # ── 2단계: URL 키워드 블랙리스트 ──
        result = self._check_url_keywords(url_text)
        if result:
            self.callback("URL_MATCH", result, screenshot, target_hwnd, target_pid)
            return

        # ── 3단계: 본문 콘텐츠 키워드 ──
        result = self._check_content_keywords(body_text)
        if result:
            # 키워드 조합 탐지는 main.py에서 LLM 검증 후 최종 차단 여부를 결정한다.
            self.callback("KEYWORD_MATCH", result, screenshot, target_hwnd, target_pid)
            return

        logger.debug("탐지 없음 — 허용")

    def _get_active_window_title(self) -> str:
        """
        현재 활성(포커스된) 창의 제목을 반환한다.

        pygetwindow 호출 실패 시 빈 문자열을 반환하여 파이프라인을 계속 진행한다.

        Returns:
            활성 창 제목 문자열. 창이 없거나 오류 시 "".
        """
        try:
            win = gw.getActiveWindow()
            return win.title if win else ""
        except Exception:
            return ""

    def _check_window_title(self, title: str):
        """
        창 제목이 TITLE_BLACKLIST의 키워드를 포함하는지 검사한다.

        대소문자를 무시하고 부분 일치로 비교한다.

        Args:
            title: 검사할 창 제목 문자열.

        Returns:
            탐지된 경우 사유 문자열, 탐지되지 않은 경우 None.
        """
        if not title:
            return None
        title_lower = title.lower()
        for keyword in Config.TITLE_BLACKLIST:
            if keyword.lower() in title_lower:
                return f"창 타이틀 감지: '{keyword}' in '{title}'"
        return None

    def _capture_screen(self) -> np.ndarray:
        """
        주 모니터(monitors[1])의 전체 화면을 캡처하여 BGR 이미지로 반환한다.

        mss는 BGRA 형식으로 캡처하므로 cv2로 BGR로 변환한다.

        Returns:
            BGR 형식의 numpy 배열 이미지.
        """
        with mss.mss() as sct:
            monitor = sct.monitors[1]  # 0은 전체 가상 스크린, 1은 첫 번째 물리 모니터
            raw = sct.grab(monitor)
            img = np.array(raw)
            return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

    def _split_zones(self, img: np.ndarray):
        """
        캡처 이미지를 URL 영역과 본문 영역으로 분할하고 각각 OCR을 수행한다.

        화면 높이 기준:
            URL 영역  — 상단  0% ~ 8%  (브라우저 주소 표시줄 위치)
            본문 영역 — 상단  8% ~ 85% (페이지 본문, 하단 작업 표시줄 제외)

        Args:
            img: BGR 형식의 전체 화면 이미지.

        Returns:
            (url_text, body_text) — 각 영역의 OCR 결과 문자열 튜플.
        """
        h = img.shape[0]
        url_zone  = img[0           : int(h * 0.08), :]
        body_zone = img[int(h * 0.08): int(h * 0.85), :]
        return self._ocr_to_text(url_zone), self._ocr_to_text(body_zone)

    def _ocr_to_text(self, img: np.ndarray) -> str:
        """
        이미지 영역에 EasyOCR을 실행하여 텍스트를 추출한다.

        Config.OCR_CONFIDENCE_THRESHOLD 미만의 인식 결과는 제외하여
        오탐 가능성을 줄인다.

        Args:
            img: OCR을 수행할 BGR 이미지 영역.

        Returns:
            신뢰도 임계값 이상의 텍스트를 공백으로 연결한 문자열.
            빈 이미지이거나 오류 시 "".
        """
        try:
            if img.size == 0:
                return ""
            results = self.ocr.readtext(img, detail=1)
            # detail=1: [(bbox, text, confidence), ...] 형식으로 반환된다.
            lines = [
                text
                for (_, text, conf) in results
                if float(conf) >= Config.OCR_CONFIDENCE_THRESHOLD
            ]
            return " ".join(lines)
        except Exception as e:
            logger.error(f"OCR 오류: {e}")
            return ""

    def _check_url_keywords(self, url_text: str):
        """
        URL 영역 텍스트가 URL_BLACKLIST의 키워드를 포함하는지 검사한다.

        대소문자를 무시하고 부분 일치로 비교한다.

        Args:
            url_text: 화면 상단 영역의 OCR 텍스트.

        Returns:
            탐지된 경우 사유 문자열, 탐지되지 않은 경우 None.
        """
        if not url_text:
            return None
        url_lower = url_text.lower()
        for keyword in Config.URL_BLACKLIST:
            if keyword.lower() in url_lower:
                return f"URL 키워드 감지: '{keyword}'"
        return None

    def _check_content_keywords(self, body_text: str):
        """
        본문 텍스트에서 CONTENT_KEYWORDS와 일치하는 키워드를 수집하고,
        KEYWORD_THRESHOLD 이상이면 탐지로 판단한다.

        단일 키워드 오탐을 줄이기 위해 복수 키워드 동시 감지를 조건으로 한다.

        Args:
            body_text: 화면 본문 영역의 OCR 텍스트.

        Returns:
            KEYWORD_THRESHOLD 이상 감지 시 일치 키워드 목록을 포함한 사유 문자열,
            미감지 시 None.
        """
        if not body_text:
            return None
        matched = [kw for kw in Config.CONTENT_KEYWORDS if kw in body_text]
        if len(matched) >= Config.KEYWORD_THRESHOLD:
            return f"콘텐츠 키워드 감지: {matched}"
        return None

    def _is_whitelisted(self, text: str) -> bool:
        """
        텍스트에 URL_WHITELIST 항목이 포함되어 있는지 확인한다.

        창 타이틀, URL 영역 텍스트, 본문 텍스트에 대해 각각 호출된다.
        대소문자를 무시하고 부분 일치로 비교한다.

        Args:
            text: 검사할 텍스트 문자열.

        Returns:
            화이트리스트 항목이 포함되어 있으면 True, 아니면 False.
        """
        if not text:
            return False
        text_lower = text.lower()
        return any(wl.lower() in text_lower for wl in Config.URL_WHITELIST)
