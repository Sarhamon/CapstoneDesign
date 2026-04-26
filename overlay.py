"""
overlay.py
차단 오버레이 UI
- Tkinter를 메인 스레드에서만 실행 (Tcl_AsyncDelete 오류 해결)
- Queue 기반으로 서브 스레드에서 UI 이벤트 수신
"""

import tkinter as tk
import queue
import logging
import ctypes
import ctypes.wintypes
import secrets
import time
from datetime import datetime

import qrcode
from qrcode.constants import ERROR_CORRECT_M
from qrcode.image.pil import PilImage
from PIL import Image, ImageTk

from config import Config
from web_auth import WebAuthServer, get_lan_ip

logger = logging.getLogger(__name__)

_user32 = ctypes.windll.user32

# CallNextHookEx: lParam은 64비트 포인터 크기이므로 argtypes를 명시해야 OverflowError를 방지한다.
_user32.CallNextHookEx.restype  = ctypes.c_long
_user32.CallNextHookEx.argtypes = [
    ctypes.c_void_p,          # HHOOK hhk
    ctypes.c_int,             # int   nCode
    ctypes.wintypes.WPARAM,   # WPARAM wParam
    ctypes.wintypes.LPARAM,   # LPARAM lParam (64비트)
]
_user32.SetWindowsHookExA.restype  = ctypes.c_void_p
_user32.SetWindowsHookExA.argtypes = [
    ctypes.c_int,
    ctypes.c_void_p,          # HOOKPROC (콜백 포인터)
    ctypes.c_void_p,          # HINSTANCE hmod
    ctypes.wintypes.DWORD,    # DWORD dwThreadId
]
_user32.UnhookWindowsHookEx.restype  = ctypes.wintypes.BOOL
_user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
_user32.SetWindowPos.restype  = ctypes.wintypes.BOOL
_user32.SetWindowPos.argtypes = [
    ctypes.c_void_p,        # HWND hWnd
    ctypes.c_void_p,        # HWND hWndInsertAfter
    ctypes.c_int,           # int X
    ctypes.c_int,           # int Y
    ctypes.c_int,           # int cx (너비)
    ctypes.c_int,           # int cy (높이)
    ctypes.wintypes.UINT,   # UINT uFlags
]
_user32.GetSystemMetrics.restype  = ctypes.c_int
_user32.GetSystemMetrics.argtypes = [ctypes.c_int]


class _KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode",      ctypes.wintypes.DWORD),
        ("scanCode",    ctypes.wintypes.DWORD),
        ("flags",       ctypes.wintypes.DWORD),
        ("time",        ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),   # ULONG_PTR (포인터 크기)
    ]


_HOOKPROC = ctypes.WINFUNCTYPE(
    ctypes.c_long,
    ctypes.c_int,
    ctypes.wintypes.WPARAM,
    ctypes.wintypes.LPARAM,
)


class BlockOverlay:
    """
    화면 전체를 덮는 차단 오버레이 UI를 관리하는 클래스.

    Tkinter는 메인 스레드에서만 안전하게 호출할 수 있다.
    모니터/LLM 스레드에서 직접 Tkinter를 건드리면 Tcl_AsyncDelete 오류가 발생하므로,
    show()/hide() 메서드는 ui_queue에 이벤트를 넣기만 하고,
    실제 위젯 생성/제거는 메인 스레드의 _poll_queue()에서 처리한다.

    오버레이 UI 구성:
        - 전체 화면 반투명 어두운 배경 (alpha=0.93)
        - 탐지 사유 텍스트
        - "해제 요청" 버튼 → 클릭 시 랜덤 코드 + QR + 카운트다운으로 전환 (3분간)
        - 차단 시각 실시간 표시 (1초 갱신)
    """

    def __init__(
        self,
        on_unlock_callback=None,
        ui_queue: queue.Queue | None = None,
        web_auth_server: WebAuthServer | None = None,
    ):
        """
        Args:
            on_unlock_callback: 해제 인증 성공 시 호출할 콜백.
                signature: (block_reason: str) -> None
            ui_queue: 서브 스레드에서 UI 이벤트를 전달할 큐.
                      ("show", reason) / ("hide",) / ("web-unlock",) 튜플을 넣는다.
            web_auth_server: 웹 기반 해제 인증을 담당하는 HTTP 서버.
                             None이면 오버레이는 해제 불가 상태가 된다.
        """
        self.on_unlock = on_unlock_callback
        self._ui_queue = ui_queue
        self._web_auth = web_auth_server
        self._active = False    # 오버레이 표시 여부 상태 플래그
        self._reason = ""       # 현재 표시 중인 차단 사유

        # Tkinter 위젯 — 반드시 메인 스레드에서 생성·접근해야 한다.
        self.root = None
        self._overlay_frame = None  # 오버레이 컨텐츠를 담는 프레임 위젯
        self._action_frame = None   # 요청 버튼 / QR 패널을 담는 컨테이너
        self._countdown_label = None  # 코드 만료까지 남은 시간 표시 레이블
        self._time_label = None     # 차단 시각을 표시하는 레이블 위젯
        self._qr_photo = None       # QR ImageTk.PhotoImage (GC 방지)
        self._unlock_expires_at = 0.0  # 현재 발급된 코드 만료 시각 (epoch)
        self._kb_hook = None        # 저수준 키보드 훅 핸들
        self._kb_hook_func = None   # 훅 콜백 (GC 방지용 참조 유지)

    # ──────────────────────────────────────────
    # 메인 스레드 루프 (main.py의 run()에서 호출)
    # ──────────────────────────────────────────

    def run_mainloop(self):
        """
        Tkinter를 초기화하고 메인 이벤트 루프를 시작한다.

        이 메서드는 메인 스레드에서만 호출해야 하며,
        Tkinter 루프가 종료될 때까지 반환되지 않는다.
        UI 이벤트 큐는 __init__에서 주입된 self._ui_queue를 사용한다.
        """
        self.root = tk.Tk()
        self.root.withdraw()        # 초기엔 창을 숨겨 사용자에게 보이지 않게 한다.
        self.root.title("FocusGuard")

        # 큐 폴링을 100ms 간격으로 시작한다.
        self._poll_queue()

        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            logger.info("Tkinter 루프 종료")

    def _poll_queue(self):
        """
        ui_queue에서 UI 이벤트를 꺼내 처리한다. 메인 스레드에서만 실행된다.

        큐가 비어 있으면 즉시 종료하고, 100ms 후 재귀적으로 자신을 호출한다.
        Tkinter의 after()를 사용하여 메인 루프 안에서 주기적으로 실행된다.
        """
        if self._ui_queue is None:
            return
        try:
            while True:
                event, *args = self._ui_queue.get_nowait()
                if event == "show":
                    self._show(args[0])
                elif event == "hide":
                    self._hide()
                elif event == "web-unlock":
                    # WebAuthServer 스레드에서 인증 성공 시 큐로 전달됨.
                    logger.info("[큐 수신] web-unlock 이벤트")
                    self._on_web_unlock()
        except queue.Empty:
            pass
        finally:
            # root가 살아 있는 동안 100ms 후에 다시 이 메서드를 호출한다.
            if self.root:
                self.root.after(100, self._poll_queue)

    # ──────────────────────────────────────────
    # Public (서브 스레드에서 호출 → 큐로 전달)
    # ──────────────────────────────────────────

    def show(self, reason: str):
        """
        서브 스레드에서 오버레이 표시를 요청한다.

        실제 Tkinter 위젯 조작은 큐를 통해 메인 스레드에서 처리된다.

        Args:
            reason: 오버레이에 표시할 차단 사유 문자열.
        """
        if self._ui_queue:
            self._ui_queue.put(("show", reason))

    def hide(self):
        """
        서브 스레드에서 오버레이 숨김을 요청한다.

        실제 Tkinter 위젯 조작은 큐를 통해 메인 스레드에서 처리된다.
        """
        if self._ui_queue:
            self._ui_queue.put(("hide",))

    @property
    def is_active(self) -> bool:
        """오버레이가 현재 화면에 표시 중인지 반환한다."""
        return self._active

    # ──────────────────────────────────────────
    # 실제 UI 생성/제거 (메인 스레드에서만 실행)
    # ──────────────────────────────────────────

    def _show(self, reason: str):
        """
        오버레이를 화면에 표시한다. 메인 스레드에서만 호출해야 한다.

        이미 오버레이가 활성화된 경우 중복 생성을 방지하기 위해 즉시 반환한다.

        Args:
            reason: 화면에 표시할 차단 사유 문자열.
        """
        if self._active:
            return
        self._active = True
        self._reason = reason
        self._build_ui()
        # self._install_kb_hook()  # TODO: 테스트 완료 후 주석 해제

    def _hide(self):
        """
        오버레이를 화면에서 숨기고 위젯을 정리한다. 메인 스레드에서만 호출해야 한다.

        오버레이 프레임을 destroy()하고 루트 창을 withdraw()하여
        작업 표시줄에서도 사라지게 한다.
        활성 해제 코드도 함께 무효화하여 오버레이가 닫힌 뒤 재인증을 막는다.
        """
        self._active = False
        # self._uninstall_kb_hook()  # TODO: 테스트 완료 후 주석 해제
        self._unlock_expires_at = 0.0
        if self._web_auth:
            self._web_auth.clear_code()
        self._qr_photo = None
        self._countdown_label = None
        self._action_frame = None
        if self._overlay_frame:
            self._overlay_frame.destroy()
            self._overlay_frame = None
        if self.root:
            self.root.overrideredirect(False)
            self.root.withdraw()

    def _on_web_unlock(self):
        """
        WebAuthServer 스레드에서 인증 성공 시 ui_queue를 거쳐 메인 스레드에서 호출된다.

        오버레이가 이미 비활성화되었거나 현재 활성 코드가 없으면 (예: 만료 후 늦게 도착한
        요청) 무시한다. 정상 케이스에서는 on_unlock 콜백을 호출하고 오버레이를 닫는다.
        """
        if not self._active:
            logger.warning(
                "[웹 해제 무시] 오버레이 비활성 상태에서 web-unlock 도착 (active=False)"
            )
            return
        if self._unlock_expires_at == 0.0:
            logger.warning(
                "[웹 해제 무시] 활성 코드 없음 — 코드 만료 후 도착했거나 race condition"
            )
            return
        logger.info(f"[웹 해제 성공] 차단 원인: {self._reason}")
        if self.on_unlock:
            self.on_unlock(self._reason)
        self._hide()

    def _build_ui(self):
        """
        오버레이 UI 위젯을 생성하고 화면에 배치한다. 반드시 메인 스레드에서 실행해야 한다.

        전체 화면 / topmost / 반투명으로 설정하여 다른 창 위에 고정된다.
        WM_DELETE_WINDOW 이벤트를 무효화하여 Alt+F4로 닫히지 않도록 한다.
        """
        # run_mainloop() 이후에만 호출되므로 root는 반드시 초기화되어 있다.
        assert self.root is not None
        root = self.root

        # ── 전체화면 설정 순서 ──
        # 1) overrideredirect → geometry → deiconify 순서로 설정해야
        #    창이 표시될 때부터 올바른 크기로 나타난다.
        #    deiconify 이후에 geometry를 바꾸면 Windows가 무시하는 경우가 있다.
        # 2) 가상 화면(SM_*VIRTUALSCREEN)으로 모든 모니터를 합친 영역을 사용하여
        #    보조 모니터에 띄운 차단 대상도 가려진다.
        # 3) main.py에서 SetProcessDpiAwarenessContext 로 Per-Monitor-V2 설정한
        #    상태이므로 Tkinter geometry와 GetSystemMetrics 모두 물리 픽셀로 일치한다.
        HWND_TOPMOST       = -1
        SWP_SHOWWINDOW     = 0x0040
        SM_CXSCREEN        = 0
        SM_CYSCREEN        = 1
        SM_XVIRTUALSCREEN  = 76
        SM_YVIRTUALSCREEN  = 77
        SM_CXVIRTUALSCREEN = 78
        SM_CYVIRTUALSCREEN = 79

        # 가상 화면 영역(모든 모니터 통합) — 좌표는 음수일 수 있다
        # (예: 주 모니터 왼쪽에 보조 모니터가 배치된 경우 vx < 0).
        vx = _user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        vy = _user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        vw = _user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
        vh = _user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)

        root.overrideredirect(True)
        root.geometry(f"{vw}x{vh}+{vx}+{vy}")
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.93)
        root.configure(bg="#1a1a2e")
        root.deiconify()                  # 이미 올바른 크기/속성이 확정된 상태에서 표시
        root.update()                     # 모든 pending 이벤트 처리

        # Win32 API로 가상 화면 전체에 대해 위치/크기 + topmost를 강제
        hwnd = root.winfo_id()
        _user32.SetWindowPos(hwnd, HWND_TOPMOST, vx, vy, vw, vh, SWP_SHOWWINDOW)

        root.lift()
        root.focus_force()

        # 이전에 표시된 오버레이 프레임이 있으면 제거 후 새로 생성한다.
        if self._overlay_frame:
            self._overlay_frame.destroy()

        # 콘텐츠 프레임은 주 모니터 중앙에 배치한다.
        # 가상 화면 좌표계에서 주 모니터의 중앙 = (-vx + prim_w/2, -vy + prim_h/2).
        # relx/rely 0.5는 다중 모니터일 때 모니터 사이 공백에 떨어질 수 있어 사용 안 한다.
        prim_w = _user32.GetSystemMetrics(SM_CXSCREEN)
        prim_h = _user32.GetSystemMetrics(SM_CYSCREEN)
        content_x = -vx + prim_w // 2
        content_y = -vy + prim_h // 2

        self._overlay_frame = tk.Frame(root, bg="#1a1a2e")
        self._overlay_frame.place(x=content_x, y=content_y, anchor="center")
        frame = self._overlay_frame

        # 경고 아이콘
        tk.Label(
            frame, text="🚫",
            font=("Arial", 64), bg="#1a1a2e",
        ).pack(pady=(0, 10))

        # 제목 레이블
        tk.Label(
            frame,
            text="수업에 방해되는 화면이 감지되었습니다",
            font=("맑은 고딕", 22, "bold"),
            fg="#e94560", bg="#1a1a2e",
        ).pack(pady=(0, 8))

        # 탐지 사유 — 80자를 초과하면 말줄임표로 자른다.
        reason_short = self._reason[:80] + "..." if len(self._reason) > 80 else self._reason
        tk.Label(
            frame,
            text=f"사유: {reason_short}",
            font=("맑은 고딕", 13),
            fg="#a8a8b3", bg="#1a1a2e",
            wraplength=700,
        ).pack(pady=(0, 30))

        # 시각적 구분선
        tk.Frame(frame, bg="#e94560", height=2, width=500).pack(pady=(0, 24))

        # 액션 영역: 초기에는 "해제 요청" 버튼, 클릭 시 QR + 코드 + 카운트다운으로 전환된다.
        self._action_frame = tk.Frame(frame, bg="#1a1a2e")
        self._action_frame.pack()
        self._build_request_button()

        # 차단 시각 표시 레이블 — _update_time()이 1초마다 갱신한다.
        self._time_label = tk.Label(
            frame, text="",
            font=("맑은 고딕", 11),
            fg="#555577", bg="#1a1a2e",
        )
        self._time_label.pack(pady=(24, 0))
        self._update_time()
        self._enforce_topmost()

    def _clear_action_frame(self):
        """액션 영역의 모든 자식 위젯을 제거한다 (상태 전환 시 호출)."""
        if not self._action_frame:
            return
        for child in self._action_frame.winfo_children():
            child.destroy()

    def _build_request_button(self):
        """
        초기/만료 상태의 액션 영역을 구성한다.

        안내 문구와 "해제 요청" 버튼을 표시한다. 버튼 클릭 시 _request_unlock()이
        랜덤 코드를 발급하고 액션 영역을 QR 패널로 전환한다.
        """
        self._clear_action_frame()
        if not self._action_frame:
            return

        tk.Label(
            self._action_frame,
            text="해제하려면 교수자에게 요청하세요.",
            font=("맑은 고딕", 12),
            fg="#c0c0c0", bg="#1a1a2e",
        ).pack(pady=(0, 16))

        tk.Button(
            self._action_frame,
            text="🔓  해제 요청",
            font=("맑은 고딕", 13, "bold"),
            bg="#0f3460", fg="#ffffff",
            activebackground="#1a5276",
            relief="flat", padx=24, pady=12,
            cursor="hand2",
            command=self._request_unlock,
        ).pack()

    def _request_unlock(self):
        """
        "해제 요청" 버튼 클릭 시 호출된다.

        Config.UNLOCK_CODE_LENGTH 자릿수의 랜덤 숫자 코드를 생성하고
        WebAuthServer에 등록한 뒤, QR(LAN URL) + 코드 + 카운트다운 패널로 전환한다.
        """
        if self._web_auth is None:
            logger.error("WebAuthServer 미설정 — 해제 요청을 처리할 수 없습니다.")
            return

        # 항상 N자리, 앞자리는 1~9 인 숫자 코드.
        # 0-패딩 방식(예: "015932")을 쓰면 사용자가 앞 0을 빼고 입력해 인증이 실패하는
        # 사례가 자주 발생하므로 처음부터 앞자리에 0이 나오지 않게 범위를 좁힌다.
        # 자릿수에 맞춰 [10^(N-1), 10^N) 범위에서 균등 추출.
        lower = 10 ** (Config.UNLOCK_CODE_LENGTH - 1)
        span  = 10 ** Config.UNLOCK_CODE_LENGTH - lower
        code  = str(secrets.randbelow(span) + lower)

        ttl = Config.UNLOCK_CODE_TTL
        self._web_auth.set_code(code, ttl)
        self._unlock_expires_at = time.time() + ttl

        url = f"http://{get_lan_ip()}:{Config.WEB_AUTH_PORT}/"
        logger.info(f"[해제 요청] 코드 발급 (TTL {ttl}s) | URL: {url}")
        self._show_qr_panel(url, code)

    def _show_qr_panel(self, url: str, code: str):
        """QR 코드, 해제 코드, 남은 시간 카운트다운을 액션 영역에 그린다."""
        self._clear_action_frame()
        if not self._action_frame:
            return

        tk.Label(
            self._action_frame,
            text="교수자가 폰으로 QR을 스캔한 뒤, 아래 코드를 입력하면 해제됩니다.",
            font=("맑은 고딕", 12),
            fg="#c0c0c0", bg="#1a1a2e",
        ).pack(pady=(0, 12))

        # QR PhotoImage는 인스턴스 속성으로 보관해야 GC되지 않는다.
        self._qr_photo = self._make_qr_photo(url)
        tk.Label(
            self._action_frame,
            image=self._qr_photo,
            bg="#ffffff", bd=6,
        ).pack(pady=(0, 8))

        tk.Label(
            self._action_frame,
            text=url,
            font=("Consolas", 11),
            fg="#888899", bg="#1a1a2e",
        ).pack(pady=(0, 14))

        tk.Label(
            self._action_frame,
            text="해제 코드",
            font=("맑은 고딕", 10),
            fg="#a8a8b3", bg="#1a1a2e",
        ).pack()
        tk.Label(
            self._action_frame,
            text=code,
            font=("Consolas", 32, "bold"),
            fg="#ffffff", bg="#1a1a2e",
        ).pack(pady=(0, 6))

        self._countdown_label = tk.Label(
            self._action_frame,
            text="",
            font=("맑은 고딕", 11),
            fg="#a8a8b3", bg="#1a1a2e",
        )
        self._countdown_label.pack()
        self._update_countdown()

    def _update_countdown(self):
        """
        해제 코드 만료까지 남은 시간을 1초 간격으로 갱신한다.

        만료 시 활성 코드를 무효화하고 액션 영역을 다시 "해제 요청" 버튼 상태로 되돌린다.
        오버레이가 비활성화되었거나 카운트다운이 더 이상 필요 없으면 즉시 종료한다.
        """
        if not self._active or not self.root:
            return
        if self._unlock_expires_at == 0.0 or self._countdown_label is None:
            return

        remaining = int(self._unlock_expires_at - time.time())
        if remaining <= 0:
            logger.info("[해제 요청 만료] 코드 무효화, 요청 버튼 복귀")
            self._unlock_expires_at = 0.0
            if self._web_auth:
                self._web_auth.clear_code()
            self._build_request_button()
            return

        mins, secs = divmod(remaining, 60)
        try:
            self._countdown_label.config(text=f"남은 시간: {mins:02d}:{secs:02d}")
        except tk.TclError:
            # 카운트다운 도중 위젯이 destroy된 경우 (상태 전환 / hide 등)
            return
        self.root.after(1000, self._update_countdown)

    @staticmethod
    def _make_qr_photo(url: str, size: int = 220) -> ImageTk.PhotoImage:
        """주어진 URL을 담은 QR 코드를 ImageTk.PhotoImage로 반환한다."""
        qr = qrcode.QRCode(
            version=None,
            error_correction=ERROR_CORRECT_M,
            box_size=10,
            border=2,
        )
        qr.add_data(url)
        qr.make(fit=True)
        # PilImage 팩토리를 명시해야 .get_image()로 실제 PIL.Image 인스턴스에 접근할 수 있다.
        wrapper = qr.make_image(
            image_factory=PilImage,
            fill_color="black",
            back_color="white",
        )
        pil_img = wrapper.get_image().convert("RGB")
        pil_img = pil_img.resize((size, size), Image.Resampling.NEAREST)
        return ImageTk.PhotoImage(pil_img)

    def _update_time(self):
        """
        차단 시각 레이블을 현재 시각으로 갱신하고 1초 후 재귀 호출을 예약한다.

        오버레이가 비활성화되면 재귀 호출을 중단하여 타이머가 남지 않도록 한다.
        """
        if self._time_label and self._active and self.root:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._time_label.config(text=f"차단 시각: {now}")
            # after()는 Tkinter 메인 루프에서 실행되므로 스레드 안전하다.
            self.root.after(1000, self._update_time)

    def _enforce_topmost(self):
        """오버레이가 항상 최상위에 유지되도록 500ms마다 재확인한다."""
        if not self._active or not self.root:
            return
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(500, self._enforce_topmost)

    # ──────────────────────────────────────────
    # 키보드 훅 (Alt+Tab / Win 키 차단)
    # ──────────────────────────────────────────

    def _install_kb_hook(self):
        """Alt+Tab, Alt+F4, Win 키를 차단하는 저수준 키보드 훅을 설치한다."""
        VK_TAB  = 0x09
        VK_F4   = 0x73
        VK_LWIN = 0x5B
        VK_RWIN = 0x5C
        VK_MENU = 0x12  # Alt

        def _handler(nCode, wParam, lParam):
            if nCode >= 0:
                kb = ctypes.cast(lParam, ctypes.POINTER(_KBDLLHOOKSTRUCT)).contents
                vk = kb.vkCode
                alt = bool(_user32.GetAsyncKeyState(VK_MENU) & 0x8000)
                if alt and vk in (VK_TAB, VK_F4):
                    return 1  # 차단: CallNextHookEx 호출 생략
                if vk in (VK_LWIN, VK_RWIN):
                    return 1  # Win 키 차단 (Win+D, Win+Tab 등 우회 방지)
            return _user32.CallNextHookEx(self._kb_hook, nCode, wParam, lParam)

        self._kb_hook_func = _HOOKPROC(_handler)
        WH_KEYBOARD_LL = 13
        self._kb_hook = _user32.SetWindowsHookExA(WH_KEYBOARD_LL, self._kb_hook_func, None, 0)
        if self._kb_hook:
            logger.info("키보드 훅 설치 완료 (Alt+Tab, Alt+F4, Win 키 차단)")
        else:
            logger.warning("키보드 훅 설치 실패")

    def _uninstall_kb_hook(self):
        """저수준 키보드 훅을 제거한다."""
        if self._kb_hook:
            _user32.UnhookWindowsHookEx(self._kb_hook)
            self._kb_hook = None
            self._kb_hook_func = None
            logger.info("키보드 훅 제거 완료")

