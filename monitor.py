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
from config import Config

logger = logging.getLogger(__name__)


class ScreenMonitor:
    def __init__(self, on_detect_callback):
        self.callback = on_detect_callback

        logger.info("OCR 모델 초기화 중...")
        self.ocr = easyocr.Reader(["ko", "en"], gpu=False, verbose=False)
        logger.info("OCR 모델 초기화 완료")

        self.running = False
        self._thread = None
        self._last_window_title = ""

    def start(self):
        self.running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("모니터링 시작")

    def stop(self):
        self.running = False
        logger.info("모니터링 중지")

    def _loop(self):
        while self.running:
            try:
                self._check()
            except Exception as e:
                logger.error(f"모니터링 루프 오류: {e}")
            time.sleep(Config.POLL_INTERVAL)

    # monitor.py 클래스 내부에 헬퍼 함수 추가
    def _get_current_focus_info(self) -> tuple[int | None, int | None]:
        """현재 포커스된 창의 HWND와 PID를 반환"""
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

    # _check 메서드 전체 수정
    def _check(self):
        # 1. 검사 시작 시점의 포커스 창 정보를 '스냅샷'으로 박제
        target_hwnd, target_pid = self._get_current_focus_info()
        
        # 2. 타이틀 검사
        title = self._get_active_window_title()
        if title and title != self._last_window_title:
            logger.debug(f"활성 창: {title}")
            self._last_window_title = title

        result = self._check_window_title(title)
        if result:
            screenshot = self._capture_screen()
            # 박제해둔 포커스 정보를 함께 넘김
            self.callback("TITLE_MATCH", result, screenshot, target_hwnd, target_pid)
            return

        # 3. OCR 분석을 위한 스크린샷 캡처
        # (캡처하는 순간에도 포커스가 바뀌었을 수 있으므로 다시 한번 박제)
        target_hwnd, target_pid = self._get_current_focus_info()
        screenshot = self._capture_screen()
        
        url_text, body_text = self._split_zones(screenshot)

        result = self._check_url_keywords(url_text)
        if result:
            self.callback("URL_MATCH", result, screenshot, target_hwnd, target_pid)
            return

        result = self._check_content_keywords(body_text)
        if result:
            self.callback("KEYWORD_MATCH", result, screenshot, target_hwnd, target_pid)
            return

        logger.debug("탐지 없음 — 허용")

    def _get_active_window_title(self) -> str:
        try:
            win = gw.getActiveWindow()
            return win.title if win else ""
        except Exception:
            return ""

    def _check_window_title(self, title: str):
        if not title:
            return None
        title_lower = title.lower()
        for keyword in Config.TITLE_BLACKLIST:
            if keyword.lower() in title_lower:
                return f"창 타이틀 감지: '{keyword}' in '{title}'"
        return None

    def _capture_screen(self) -> np.ndarray:
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            raw = sct.grab(monitor)
            img = np.array(raw)
            return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

    def _split_zones(self, img: np.ndarray):
        h = img.shape[0]
        url_zone  = img[0           : int(h * 0.08), :]
        body_zone = img[int(h * 0.08): int(h * 0.85), :]
        return self._ocr_to_text(url_zone), self._ocr_to_text(body_zone)

    def _ocr_to_text(self, img: np.ndarray) -> str:
        try:
            if img.size == 0:
                return ""
            results = self.ocr.readtext(img, detail=1)
            lines = [
                text
                for (_, text, conf) in results
                if conf >= Config.OCR_CONFIDENCE_THRESHOLD
            ]
            return " ".join(lines)
        except Exception as e:
            logger.error(f"OCR 오류: {e}")
            return ""

    def _check_url_keywords(self, url_text: str):
        if not url_text:
            return None
        url_lower = url_text.lower()
        for keyword in Config.URL_BLACKLIST:
            if keyword.lower() in url_lower:
                return f"URL 키워드 감지: '{keyword}'"
        return None

    def _check_content_keywords(self, body_text: str):
        if not body_text:
            return None
        matched = [kw for kw in Config.CONTENT_KEYWORDS if kw in body_text]
        if len(matched) >= Config.KEYWORD_THRESHOLD:
            return f"콘텐츠 키워드 감지: {matched}"
        return None
