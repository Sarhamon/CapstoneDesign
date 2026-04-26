"""
web_auth.py
LAN 기반 해제 인증 HTTP 서버 (Phase 1)
- 학생 PC에서 0.0.0.0:WEB_AUTH_PORT 로 바인드
- 교수자가 본인 폰으로 QR 스캔 → 페이지 접속 → 화면의 코드 입력 → 해제
- 추후 Phase 2: AWS EC2 중앙 서버로 이전 (이 모듈은 클라이언트 어댑터로 축소될 예정)
"""

import http.server
import json
import logging
import secrets
import socket
import threading
import time
import urllib.parse
from typing import Callable, Optional

logger = logging.getLogger(__name__)


_HTML_PAGE = """<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>FocusGuard 해제</title>
    <style>
        * { box-sizing: border-box; }
        body {
            font-family: -apple-system, "Apple SD Gothic Neo", "Malgun Gothic", sans-serif;
            max-width: 420px; margin: 0 auto; padding: 32px 20px;
            background: #1a1a2e; color: #fff; min-height: 100vh;
        }
        h1 { color: #e94560; text-align: center; margin: 0 0 8px; }
        p { text-align: center; color: #c0c0c0; margin: 0 0 24px; }
        input {
            width: 100%; padding: 18px; font-size: 28px; text-align: center;
            margin: 8px 0; border-radius: 10px; border: none;
            background: #0f3460; color: #fff; letter-spacing: 8px;
            font-family: Consolas, monospace;
        }
        button {
            width: 100%; padding: 16px; font-size: 18px; font-weight: bold;
            background: #e94560; color: #fff; border: none; border-radius: 10px;
            cursor: pointer; margin-top: 8px;
        }
        button:active { background: #c0392b; }
        #msg { text-align: center; margin-top: 20px; font-size: 16px; min-height: 24px; }
        .ok { color: #4ade80; }
        .err { color: #f87171; }
    </style>
</head>
<body>
    <h1>🔓 FocusGuard 해제</h1>
    <p>학생 화면의 해제 코드를 입력하세요.</p>
    <input id="code" type="text" inputmode="numeric" autocomplete="off"
           placeholder="000000" maxlength="12" autofocus>
    <button id="btn" onclick="submit()">해제</button>
    <div id="msg"></div>
    <script>
        const input = document.getElementById('code');
        const btn = document.getElementById('btn');
        const msg = document.getElementById('msg');
        function submit() {
            const code = input.value.trim();
            if (!code) return;
            btn.disabled = true;
            fetch('/unlock', {
                method: 'POST',
                headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                body: 'code=' + encodeURIComponent(code)
            }).then(r => r.json()).then(data => {
                if (data.success) {
                    msg.textContent = '✓ 해제되었습니다.';
                    msg.className = 'ok';
                    input.disabled = true;
                } else {
                    msg.textContent = '✗ ' + (data.error || '잘못된 코드입니다.');
                    msg.className = 'err';
                    btn.disabled = false;
                    input.select();
                }
            }).catch(e => {
                msg.textContent = '오류: ' + e;
                msg.className = 'err';
                btn.disabled = false;
            });
        }
        input.addEventListener('keypress', e => { if (e.key === 'Enter') submit(); });
    </script>
</body>
</html>
"""


class WebAuthServer:
    """
    LAN HTTP 서버. 단일 활성 코드를 메모리에 보관하고 일치 시 콜백을 호출한다.

    스레드 안전성:
        - set_code/clear_code/_validate 는 _lock 으로 보호된다.
        - HTTP 핸들러는 별도 스레드에서 실행되므로 _on_success 콜백도 별도 스레드에서 호출된다.
        - 콜백 구현 측에서 메인 스레드 작업이 필요하면 큐를 통해 마샬링해야 한다.
    """

    def __init__(self, port: int = 8080, max_failed_attempts: int = 5):
        self.port = port
        self._max_failed_attempts = max_failed_attempts
        self._lock = threading.Lock()
        self._current_code: Optional[str] = None
        self._expires_at: float = 0.0
        self._failed_attempts: int = 0
        self._on_success: Optional[Callable[[], None]] = None
        self._on_lockout: Optional[Callable[[], None]] = None
        self._server: Optional[http.server.HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def set_on_success(self, callback: Callable[[], None]) -> None:
        """해제 코드 인증 성공 시 호출할 콜백을 등록한다."""
        self._on_success = callback

    def set_on_lockout(self, callback: Callable[[], None]) -> None:
        """
        연속 실패 임계 초과로 활성 코드가 무효화되었을 때 호출할 콜백을 등록한다.
        오버레이가 QR 패널 → 요청 버튼 상태로 즉시 복귀하도록 신호를 보낼 때 사용한다.
        """
        self._on_lockout = callback

    def set_code(self, code: str, ttl_seconds: int) -> None:
        """단일 활성 해제 코드를 설정한다. 기존 코드와 실패 카운터는 즉시 리셋된다."""
        with self._lock:
            self._current_code = code
            self._expires_at = time.time() + ttl_seconds
            self._failed_attempts = 0

    def clear_code(self) -> None:
        """활성 해제 코드를 제거한다 (만료/취소 시)."""
        with self._lock:
            self._current_code = None
            self._expires_at = 0.0
            self._failed_attempts = 0

    def _validate(self, submitted: str) -> tuple[bool, str]:
        """
        제출된 코드를 활성 코드와 비교한다.

        성공 시 코드는 즉시 소멸한다 (일회성).
        연속 실패가 max_failed_attempts에 도달하면 코드를 무효화하고 lockout 콜백을 호출한다.
        콜백은 락 해제 후에 호출하여 데드락 위험을 차단한다.
        """
        triggered_lockout = False
        with self._lock:
            if not self._current_code:
                return False, "활성화된 해제 요청이 없습니다."
            if time.time() > self._expires_at:
                self._current_code = None
                self._failed_attempts = 0
                return False, "해제 코드가 만료되었습니다."

            if secrets.compare_digest(submitted, self._current_code):
                self._current_code = None  # 일회성 — 재사용 금지
                self._failed_attempts = 0
                return True, ""

            # 실패 — 카운터 증가 후 임계값 도달 시 코드 무효화
            self._failed_attempts += 1
            remaining = self._max_failed_attempts - self._failed_attempts
            if remaining <= 0:
                self._current_code = None
                self._failed_attempts = 0
                triggered_lockout = True
                msg = "잘못된 코드를 여러 번 입력하여 무효화되었습니다. 학생에게 새 코드를 요청하세요."
            else:
                msg = f"잘못된 코드입니다. (남은 시도 {remaining}회)"

        # 락 밖에서 콜백 호출 (콜백이 락을 다시 잡으려 할 가능성 배제)
        if triggered_lockout:
            logger.warning(
                "[브루트포스 방어] 연속 실패 한도 초과 → 활성 코드 무효화"
            )
            if self._on_lockout:
                try:
                    self._on_lockout()
                except Exception:
                    logger.exception("on_lockout 콜백 처리 중 오류")
        return False, msg

    def start(self) -> None:
        """HTTP 서버를 백그라운드 스레드에서 시작한다 (LAN 전체에 노출)."""
        handler_cls = self._make_handler_cls()
        self._server = http.server.HTTPServer(("0.0.0.0", self.port), handler_cls)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="WebAuthServer",
            daemon=True,
        )
        self._thread.start()
        logger.info(f"WebAuthServer 시작: 0.0.0.0:{self.port}")

    def stop(self) -> None:
        """서버를 중지한다 (보통 호출되지 않음 — daemon 스레드)."""
        if self._server:
            self._server.shutdown()
            self._server = None

    def _make_handler_cls(self):
        outer = self

        class _Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format, *args):  # noqa: A002 - BaseHTTPRequestHandler 시그니처 유지
                # 기본 stderr 로그를 logger로 우회. 파라미터명은 베이스 클래스와 동일하게 둔다
                # (Pylance reportIncompatibleMethodOverride 회피 + 키워드 호출 호환성).
                logger.debug("HTTP %s - %s", self.address_string(), format % args)

            def _write(self, status: int, content_type: str, body: bytes) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                path = self.path.split("?", 1)[0]
                if path in ("/", "/index.html"):
                    self._write(200, "text/html; charset=utf-8",
                                _HTML_PAGE.encode("utf-8"))
                else:
                    self.send_error(404)

            def do_POST(self):
                if self.path != "/unlock":
                    self.send_error(404)
                    return
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length).decode("utf-8", errors="replace")
                params = urllib.parse.parse_qs(raw)
                submitted = (params.get("code") or [""])[0].strip()

                ok, err = outer._validate(submitted)
                if ok:
                    logger.info("[웹 해제 성공] 원격 인증 완료")
                    if outer._on_success:
                        try:
                            outer._on_success()
                        except Exception:
                            logger.exception("on_success 콜백 처리 중 오류")
                    payload = {"success": True}
                else:
                    logger.warning("[웹 해제 실패] %s", err)
                    payload = {"success": False, "error": err}
                self._write(200, "application/json",
                            json.dumps(payload).encode("utf-8"))

        return _Handler


def get_lan_ip() -> str:
    """
    LAN 내 다른 기기가 이 PC에 접근할 때 사용할 IP를 반환한다.

    외부 주소로 UDP 소켓을 연결 시도하면 OS가 라우팅에 사용할 인터페이스의
    IP를 자동으로 선택해준다 (실제 패킷은 전송되지 않는다).
    실패 시 127.0.0.1 (loopback)을 반환한다 — QR이 동작하지 않으므로
    사용자가 네트워크 환경을 점검해야 한다.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()
