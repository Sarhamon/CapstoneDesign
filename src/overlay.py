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
import threading
import time
import uuid
from datetime import datetime

import requests

from config import config

logger = logging.getLogger(__name__)

_user32 = ctypes.windll.user32


_user32.CallNextHookEx.restype  = ctypes.c_long
_user32.CallNextHookEx.argtypes = [
    ctypes.c_void_p,
    ctypes.c_int,
    ctypes.wintypes.WPARAM,
    ctypes.wintypes.LPARAM,
]
_user32.SetWindowsHookExA.restype  = ctypes.c_void_p
_user32.SetWindowsHookExA.argtypes = [
    ctypes.c_int,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.wintypes.DWORD,
]
_user32.UnhookWindowsHookEx.restype  = ctypes.wintypes.BOOL
_user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
_user32.SetWindowPos.restype  = ctypes.wintypes.BOOL
_user32.SetWindowPos.argtypes = [
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.wintypes.UINT,
]
_user32.GetSystemMetrics.restype  = ctypes.c_int
_user32.GetSystemMetrics.argtypes = [ctypes.c_int]


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
    ):
        """
        Args:
            on_unlock_callback: 해제 인증 성공 시 호출할 콜백.
                signature: (block_reason: str) -> None
            ui_queue: 서브 스레드에서 UI 이벤트를 전달할 큐.
                      ("show", reason) / ("hide",) / ("web-unlock",) 튜플을 넣는다.
        """
        self.on_unlock = on_unlock_callback
        self._ui_queue = ui_queue
        self._active = False
        self._reason = ""

        self.root = None
        self._overlay_frame = None
        self._action_frame = None
        self._countdown_label = None
        self._time_label = None
        self._unlock_expires_at = 0.0
        self._kb_hook = None
        self._kb_hook_func = None


    def run_mainloop(self):
        """
        Tkinter를 초기화하고 메인 이벤트 루프를 시작한다.

        이 메서드는 메인 스레드에서만 호출해야 하며,
        Tkinter 루프가 종료될 때까지 반환되지 않는다.
        UI 이벤트 큐는 __init__에서 주입된 self._ui_queue를 사용한다.
        """
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("FocusGuard")


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

                    logger.info("[큐 수신] web-unlock 이벤트")
                    self._on_web_unlock()

        except queue.Empty:
            pass
        finally:

            if self.root:
                self.root.after(100, self._poll_queue)


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
        if config.KEYBOARD_BLOCK_ENABLED:
            self._install_kb_hook()

    def _hide(self):
        """
        오버레이를 화면에서 숨기고 위젯을 정리한다. 메인 스레드에서만 호출해야 한다.

        오버레이 프레임을 destroy()하고 루트 창을 withdraw()하여
        작업 표시줄에서도 사라지게 한다.
        활성 해제 코드도 함께 무효화하여 오버레이가 닫힌 뒤 재인증을 막는다.
        """
        self._active = False
        if config.KEYBOARD_BLOCK_ENABLED:
            self._uninstall_kb_hook()
        self._unlock_expires_at = 0.0
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

        서버 측 _validate()에서 이미 만료 여부를 검증했으므로 여기서는 오버레이 활성
        여부만 확인한다. _unlock_expires_at 재확인은 카운트다운 타이머와의 race condition
        (마지막 1초 내 제출 시 타이머가 먼저 0으로 초기화)을 일으키므로 제거한다.
        """
        if not self._active:
            logger.warning(
                "[웹 해제 무시] 오버레이 비활성 상태에서 web-unlock 도착 (active=False)"
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

        assert self.root is not None
        root = self.root


        HWND_TOPMOST       = -1
        SWP_SHOWWINDOW     = 0x0040
        SM_CXSCREEN        = 0
        SM_CYSCREEN        = 1
        SM_XVIRTUALSCREEN  = 76
        SM_YVIRTUALSCREEN  = 77
        SM_CXVIRTUALSCREEN = 78
        SM_CYVIRTUALSCREEN = 79


        vx = _user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        vy = _user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        vw = _user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
        vh = _user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)

        root.overrideredirect(True)
        root.geometry(f"{vw}x{vh}+{vx}+{vy}")
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.93)
        root.configure(bg="#1a1a2e")
        root.deiconify()
        root.update()


        hwnd = root.winfo_id()
        _user32.SetWindowPos(hwnd, HWND_TOPMOST, vx, vy, vw, vh, SWP_SHOWWINDOW)

        root.lift()
        root.focus_force()


        if self._overlay_frame:
            self._overlay_frame.destroy()


        prim_w = _user32.GetSystemMetrics(SM_CXSCREEN)
        prim_h = _user32.GetSystemMetrics(SM_CYSCREEN)
        content_x = -vx + prim_w // 2
        content_y = -vy + prim_h // 2

        self._overlay_frame = tk.Frame(root, bg="#1a1a2e")
        self._overlay_frame.place(x=content_x, y=content_y, anchor="center")
        frame = self._overlay_frame


        tk.Label(
            frame, text="🚫",
            font=("Arial", 64), bg="#1a1a2e",
        ).pack(pady=(0, 10))


        tk.Label(
            frame,
            text="수업에 방해되는 화면이 감지되었습니다",
            font=("맑은 고딕", 22, "bold"),
            fg="#e94560", bg="#1a1a2e",
        ).pack(pady=(0, 8))


        reason_short = self._reason[:80] + "..." if len(self._reason) > 80 else self._reason
        tk.Label(
            frame,
            text=f"사유: {reason_short}",
            font=("맑은 고딕", 13),
            fg="#a8a8b3", bg="#1a1a2e",
            wraplength=700,
        ).pack(pady=(0, 30))


        tk.Frame(frame, bg="#e94560", height=2, width=500).pack(pady=(0, 24))


        self._action_frame = tk.Frame(frame, bg="#1a1a2e")
        self._action_frame.pack()
        self._build_request_button()


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

    @staticmethod
    def _get_device_id() -> str:
        try:
            mac_bytes = uuid.getnode().to_bytes(6, byteorder="big")
            return ":".join(f"{b:02x}" for b in mac_bytes)
        except Exception:
            return "unknown"

    def _request_unlock(self):
        """해제 요청 버튼 클릭 시 클라우드 해제 요청을 전송하고 승인 폴링을 시작한다."""
        device_id = self._get_device_id()
        self._unlock_expires_at = time.time() + config.UNLOCK_CODE_TTL
        threading.Thread(
            target=self._send_cloud_unlock_request,
            args=(device_id,),
            daemon=True,
        ).start()
        threading.Thread(
            target=self._poll_cloud_approval,
            args=(device_id, self._unlock_expires_at),
            daemon=True,
        ).start()
        self._show_waiting_panel()

    def _send_cloud_unlock_request(self, device_id: str) -> None:
        try:
            url = config.CLOUD_API_URL.rstrip("/") + f"/unlock/{device_id}"
            resp = requests.post(
                url,
                json={"action": "request", "device_id": device_id, "reason": self._reason},
                timeout=10,
            )
            resp.raise_for_status()
            logger.info(f"[클라우드 해제 요청] 전송 완료 | device_id={device_id}")
        except Exception as e:
            logger.error(f"[클라우드 해제 요청] 전송 실패: {e}")

    def _poll_cloud_approval(self, device_id: str, expires_at: float) -> None:
        url = config.CLOUD_API_URL.rstrip("/") + f"/unlock/{device_id}"
        while time.time() < expires_at:
            time.sleep(3)
            if not self._active:
                return
            try:
                resp = requests.get(url, timeout=5)
                if resp.ok and resp.json().get("status") == "approved":
                    logger.info("[클라우드 승인] 관리자가 해제 승인함")
                    if self._ui_queue:
                        self._ui_queue.put(("web-unlock",))
                    return
            except Exception as e:
                logger.warning(f"[클라우드 폴링] 오류: {e}")
        logger.info("[클라우드 폴링] TTL 만료 → 폴링 종료")

    def _show_waiting_panel(self):
        """클라우드 해제 요청 전송 후 교수자 승인 대기 상태 UI를 그린다."""
        self._clear_action_frame()
        if not self._action_frame:
            return
        tk.Label(
            self._action_frame,
            text="해제 요청을 전송했습니다.",
            font=("맑은 고딕", 14, "bold"),
            fg="#4ade80", bg="#1a1a2e",
        ).pack(pady=(0, 8))
        tk.Label(
            self._action_frame,
            text="교수자가 승인하면 자동으로 해제됩니다.",
            font=("맑은 고딕", 12),
            fg="#c0c0c0", bg="#1a1a2e",
        ).pack(pady=(0, 16))
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
            logger.info("[해제 요청 만료] 요청 버튼 복귀")
            self._unlock_expires_at = 0.0
            self._build_request_button()
            return

        mins, secs = divmod(remaining, 60)
        try:
            self._countdown_label.config(text=f"남은 시간: {mins:02d}:{secs:02d}")
        except tk.TclError:

            return
        self.root.after(1000, self._update_countdown)

    def _update_time(self):
        """
        차단 시각 레이블을 현재 시각으로 갱신하고 1초 후 재귀 호출을 예약한다.

        오버레이가 비활성화되면 재귀 호출을 중단하여 타이머가 남지 않도록 한다.
        """
        if self._time_label and self._active and self.root:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._time_label.config(text=f"차단 시각: {now}")

            self.root.after(1000, self._update_time)

    def _enforce_topmost(self):
        """오버레이가 항상 최상위에 유지되도록 500ms마다 재확인한다."""
        if not self._active or not self.root:
            return
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(500, self._enforce_topmost)


    def _install_kb_hook(self):
        """
        오버레이가 표시된 동안 모든 키보드 입력을 차단한다.

        설계 의도:
            오버레이가 화면 전체를 덮은 상태에서는 학생이 어떤 앱과도 상호작용할 수
            없으므로 키보드 입력이 의미를 가지는 곳이 없다. 따라서 특정 단축키만
            골라 막는 대신 모든 키를 차단해 알려지지 않은 우회 단축키(신규 Win11
            단축키, 보조 입력 도구 등)까지 일괄 봉쇄한다. 오버레이가 닫히면
            _uninstall_kb_hook()이 훅을 제거해 키보드는 즉시 정상 동작한다.

            마우스는 막지 않는다 — "해제 요청" 버튼 클릭이 필요하기 때문이다.

        한계:
            Ctrl+Alt+Del 은 Windows 보안 화면을 거치는 OS 레벨 단축키라 user-mode
            훅으로 차단할 수 없다. 의도적으로 백도어 역할을 하므로 디버깅 시
            python.exe 강제 종료 경로로 활용한다. 진정한 방어를 위해선 서비스화 +
            UAC + Group Policy 수준의 조치가 필요하다.
        """
        def _handler(nCode, wParam, lParam):
            if nCode >= 0:

                return 1
            return _user32.CallNextHookEx(self._kb_hook, nCode, wParam, lParam)

        self._kb_hook_func = _HOOKPROC(_handler)
        WH_KEYBOARD_LL = 13
        self._kb_hook = _user32.SetWindowsHookExA(WH_KEYBOARD_LL, self._kb_hook_func, None, 0)
        if self._kb_hook:
            logger.info("키보드 훅 설치 완료 (전체 차단 — Ctrl+Alt+Del 제외)")
        else:
            logger.warning("키보드 훅 설치 실패")

    def _uninstall_kb_hook(self):
        """저수준 키보드 훅을 제거한다."""
        if self._kb_hook:
            _user32.UnhookWindowsHookEx(self._kb_hook)
            self._kb_hook = None
            self._kb_hook_func = None
            logger.info("키보드 훅 제거 완료")
