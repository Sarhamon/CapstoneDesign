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
from datetime import datetime
from config import Config

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
        - 해제 코드 입력 버튼 → _open_code_dialog() 팝업
        - 차단 시각 실시간 표시 (1초 갱신)
    """

    def __init__(self, on_unlock_callback=None, ui_queue: queue.Queue | None = None):
        """
        Args:
            on_unlock_callback: 해제 코드 인증 성공 시 호출할 콜백.
                signature: (block_reason: str) -> None
            ui_queue: 서브 스레드에서 UI 이벤트를 전달할 큐.
                      ("show", reason) 또는 ("hide",) 튜플을 넣는다.
        """
        self.on_unlock = on_unlock_callback
        self._ui_queue = ui_queue
        self._active = False    # 오버레이 표시 여부 상태 플래그
        self._reason = ""       # 현재 표시 중인 차단 사유

        # Tkinter 위젯 — 반드시 메인 스레드에서 생성·접근해야 한다.
        self.root = None
        self._overlay_frame = None  # 오버레이 컨텐츠를 담는 프레임 위젯
        self._time_label = None     # 차단 시각을 표시하는 레이블 위젯
        self._kb_hook = None        # 저수준 키보드 훅 핸들
        self._kb_hook_func = None   # 훅 콜백 (GC 방지용 참조 유지)

    # ──────────────────────────────────────────
    # 메인 스레드 루프 (main.py의 run()에서 호출)
    # ──────────────────────────────────────────

    def run_mainloop(self, ui_queue: queue.Queue):
        """
        Tkinter를 초기화하고 메인 이벤트 루프를 시작한다.

        이 메서드는 메인 스레드에서만 호출해야 하며,
        Tkinter 루프가 종료될 때까지 반환되지 않는다.

        Args:
            ui_queue: 서브 스레드로부터 UI 이벤트를 받을 큐.
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
        """
        self._active = False
        # self._uninstall_kb_hook()  # TODO: 테스트 완료 후 주석 해제
        if self._overlay_frame:
            self._overlay_frame.destroy()
            self._overlay_frame = None
        if self.root:
            self.root.overrideredirect(False)
            self.root.withdraw()

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
        # 2) Tkinter geometry 설정 후 SetWindowPos로 물리 픽셀 기준 전체화면을 강제하여
        #    DPI 스케일(125%, 150%) 환경에서도 항상 화면 전체를 덮는다.
        HWND_TOPMOST   = -1
        SWP_SHOWWINDOW = 0x0040

        root.overrideredirect(True)
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        root.geometry(f"{sw}x{sh}+0+0")  # Tkinter 논리 픽셀 기준
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.93)
        root.configure(bg="#1a1a2e")
        root.deiconify()                  # 이미 올바른 크기/속성이 확정된 상태에서 표시
        root.update()                     # 모든 pending 이벤트 처리

        # Win32 API로 물리 픽셀 기준 전체화면 강제 (DPI 스케일 무관)
        phys_w = _user32.GetSystemMetrics(0)  # SM_CXSCREEN
        phys_h = _user32.GetSystemMetrics(1)  # SM_CYSCREEN
        hwnd   = root.winfo_id()
        _user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, phys_w, phys_h, SWP_SHOWWINDOW)

        root.lift()
        root.focus_force()

        # 이전에 표시된 오버레이 프레임이 있으면 제거 후 새로 생성한다.
        if self._overlay_frame:
            self._overlay_frame.destroy()

        # 중앙에 배치되는 컨텐츠 프레임
        self._overlay_frame = tk.Frame(root, bg="#1a1a2e")
        self._overlay_frame.place(relx=0.5, rely=0.5, anchor="center")
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
        tk.Frame(frame, bg="#e94560", height=2, width=500).pack(pady=(0, 30))

        # 해제 코드 안내 텍스트
        tk.Label(
            frame,
            text="교수자로부터 해제 코드를 받아 입력하세요.",
            font=("맑은 고딕", 12),
            fg="#c0c0c0", bg="#1a1a2e",
        ).pack(pady=(0, 16))

        # 해제 코드 입력 팝업을 여는 버튼
        tk.Button(
            frame,
            text="🔓  해제 코드 입력",
            font=("맑은 고딕", 13, "bold"),
            bg="#0f3460", fg="#ffffff",
            activebackground="#1a5276",
            relief="flat", padx=24, pady=12,
            cursor="hand2",
            command=self._open_code_dialog,
        ).pack()

        # 차단 시각 표시 레이블 — _update_time()이 1초마다 갱신한다.
        self._time_label = tk.Label(
            frame, text="",
            font=("맑은 고딕", 11),
            fg="#555577", bg="#1a1a2e",
        )
        self._time_label.pack(pady=(24, 0))
        self._update_time()
        self._enforce_topmost()

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

    # ──────────────────────────────────────────
    # 해제 코드 입력 팝업
    # ──────────────────────────────────────────

    def _open_code_dialog(self):
        """
        해제 코드를 입력받는 모달 팝업 창을 생성한다.

        grab_set()으로 포커스를 팝업에 고정하여 뒤에 있는 오버레이와 상호작용을 막는다.
        WM_DELETE_WINDOW를 무효화하여 닫기 버튼으로 팝업이 사라지지 않게 한다.
        올바른 코드 입력 시 오버레이를 숨기고 on_unlock 콜백을 호출한다.
        """
        dialog = tk.Toplevel(self.root)
        dialog.title("해제 코드 입력")
        dialog.attributes("-topmost", True)
        dialog.resizable(False, False)
        dialog.configure(bg="#16213e")
        dialog.grab_set()  # 이 창에 포커스를 고정한다.

        # 화면 중앙에 팝업을 배치한다.
        w, h = 420, 260
        sw = dialog.winfo_screenwidth()
        sh = dialog.winfo_screenheight()
        dialog.geometry(f"{w}x{h}+{(sw - w)//2}+{(sh - h)//2}")

        frame = tk.Frame(dialog, bg="#16213e", padx=30, pady=24)
        frame.pack(fill="both", expand=True)

        tk.Label(
            frame,
            text="🔑  해제 코드를 입력하세요",
            font=("맑은 고딕", 14, "bold"),
            fg="#ffffff", bg="#16213e",
        ).pack(pady=(0, 20))

        code_var = tk.StringVar()
        code_entry = tk.Entry(
            frame,
            textvariable=code_var,
            font=("맑은 고딕", 18),
            width=16,
            bg="#0f3460", fg="#ffffff",
            insertbackground="white",
            relief="flat", bd=10,
            justify="center",
            show="●",          # 입력 문자를 마스킹하여 코드가 노출되지 않게 한다.
        )
        code_entry.pack(pady=(0, 8))
        code_entry.focus_set()  # 팝업이 열리자마자 입력 필드에 커서를 위치시킨다.

        # 잘못된 코드 입력 시 오류 메시지를 표시하는 레이블
        error_label = tk.Label(
            frame, text="",
            font=("맑은 고딕", 11),
            fg="#e94560", bg="#16213e",
        )
        error_label.pack(pady=(0, 16))

        def attempt_unlock():
            """
            입력된 코드를 Config.UNLOCK_CODE와 비교하여 해제 여부를 결정한다.

            성공: 팝업을 닫고, on_unlock 콜백을 호출하며, 오버레이를 숨긴다.
            실패: 오류 메시지를 표시하고 입력 필드를 초기화한다.
            """
            code = code_var.get().strip()
            if code == Config.UNLOCK_CODE:
                logger.info(f"[해제 성공] 코드 인증 완료 | 차단 원인: {self._reason}")
                dialog.destroy()
                if self.on_unlock:
                    self.on_unlock(self._reason)
                self._hide()
            else:
                logger.warning(f"[해제 실패] 잘못된 코드 입력")
                error_label.config(text="코드가 올바르지 않습니다. 다시 확인하세요.")
                code_var.set("")
                code_entry.focus_set()

        tk.Button(
            frame,
            text="확인",
            font=("맑은 고딕", 12, "bold"),
            bg="#e94560", fg="#ffffff",
            activebackground="#c0392b",
            relief="flat", padx=20, pady=8,
            cursor="hand2",
            command=attempt_unlock,
        ).pack()

        # Enter 키로도 코드를 제출할 수 있도록 바인딩한다.
        code_entry.bind("<Return>", lambda e: attempt_unlock())
        # 팝업의 닫기 버튼을 비활성화하여 코드 없이 닫히지 않도록 한다.
        dialog.protocol("WM_DELETE_WINDOW", lambda: None)
