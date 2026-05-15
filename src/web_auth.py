"""
web_auth.py
LAN 기반 해제 인증 + 관리자 대시보드 HTTP 서버 (Phase 1)
- / : 학생용 해제 인증 페이지 (교수자가 QR 스캔 후 코드 입력)
- /admin : 관리자 대시보드 (이벤트 로그, 실시간 상태, 목록 관리)
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
import yaml
from typing import Callable, Optional

from config import config, reload_lists

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
    <h1>FocusGuard 해제</h1>
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
                    msg.textContent = '해제되었습니다.';
                    msg.className = 'ok';
                    input.disabled = true;
                } else {
                    msg.textContent = data.error || '잘못된 코드입니다.';
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


_ADMIN_HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FocusGuard 관리자</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,"Apple SD Gothic Neo","Malgun Gothic",sans-serif;background:#0f0f1a;color:#e0e0e0;min-height:100vh}
header{background:#1a1a2e;padding:14px 24px;display:flex;justify-content:space-between;align-items:center;border-bottom:2px solid #e94560}
header h1{color:#e94560;font-size:18px}
#refresh-info{font-size:12px;color:#555}
.nav{display:flex;gap:8px;padding:12px 24px;background:#141425;border-bottom:1px solid #1e1e3a}
.nav-btn{padding:8px 16px;border:none;border-radius:6px;background:#0f3460;color:#e0e0e0;cursor:pointer;font-size:13px}
.nav-btn.active{background:#e94560;color:#fff}
.section{display:none;padding:20px 24px}
.section.active{display:block}
.card{background:#1a1a2e;border-radius:10px;padding:16px;margin-bottom:16px}
.card h2{font-size:12px;color:#666;margin-bottom:12px;text-transform:uppercase;letter-spacing:1px}
.status-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:10px}
.s-item{background:#0f1a2e;border-radius:8px;padding:12px}
.s-label{font-size:11px;color:#555;margin-bottom:4px}
.s-value{font-size:16px;font-weight:bold}
.ok{color:#4ade80}.warn{color:#fbbf24}.err{color:#f87171}
table{width:100%;border-collapse:collapse;font-size:12px}
th{text-align:left;padding:8px;color:#555;border-bottom:1px solid #1e1e3a;font-weight:normal}
td{padding:7px 8px;border-bottom:1px solid #141414;vertical-align:top;word-break:break-all}
tr:hover td{background:#111}
.badge{display:inline-block;padding:2px 7px;border-radius:3px;font-size:10px;font-weight:bold;white-space:nowrap}
.badge-BLOCK{background:#7f1d1d;color:#fca5a5}
.badge-ALLOW{background:#14532d;color:#86efac}
.badge-UNLOCK_REQUEST{background:#1e3a5f;color:#93c5fd}
.list-nav{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:14px}
.list-btn{padding:6px 12px;border:none;border-radius:5px;background:#0f3460;color:#999;cursor:pointer;font-size:12px}
.list-btn.active{background:#e94560;color:#fff}
.entry-row{display:flex;align-items:center;justify-content:space-between;padding:7px 10px;background:#0f1a2e;border-radius:5px;margin-bottom:5px}
.entry-text{font-family:Consolas,monospace;font-size:13px;flex:1}
.entry-btns{display:flex;gap:4px;flex-shrink:0}
.btn-rm{background:none;border:1px solid #333;color:#888;padding:2px 9px;border-radius:3px;cursor:pointer;font-size:11px}
.btn-rm:hover{border-color:#e94560;color:#e94560}
.btn-edit{background:none;border:1px solid #333;color:#888;padding:2px 9px;border-radius:3px;cursor:pointer;font-size:11px}
.btn-edit:hover{border-color:#60a5fa;color:#60a5fa}
.edit-row{display:flex;align-items:center;gap:6px;padding:5px 10px;background:#0f1a2e;border-radius:5px;margin-bottom:5px;border:1px solid #1e3a5f}
.edit-inp{flex:1;padding:5px 8px;background:#0f3460;border:none;border-radius:4px;color:#fff;font-size:13px;font-family:Consolas,monospace;min-width:0}
.btn-save{padding:3px 10px;background:#1d4ed8;border:none;border-radius:3px;color:#fff;cursor:pointer;font-size:11px}
.btn-cancel{background:none;border:1px solid #333;color:#666;padding:3px 8px;border-radius:3px;cursor:pointer;font-size:11px}
.add-row{display:flex;gap:8px;margin-top:10px}
.add-row input{flex:1;padding:8px 12px;background:#0f3460;border:none;border-radius:6px;color:#fff;font-size:13px;font-family:Consolas,monospace}
.btn-add{padding:8px 14px;background:#e94560;border:none;border-radius:6px;color:#fff;cursor:pointer;font-size:13px}
.empty{color:#444;font-style:italic;padding:12px 0;text-align:center}
#alert-banner{display:none;background:#450a0a;border-bottom:3px solid #e94560;padding:14px 24px;align-items:flex-start;gap:16px}
#alert-banner.active{display:flex}
.alert-label{font-size:11px;font-weight:bold;color:#fca5a5;letter-spacing:1px;text-transform:uppercase;margin-bottom:4px}
.alert-reason{font-size:13px;color:#fecaca;word-break:break-all}
.alert-time{font-size:11px;color:#991b1b;margin-top:4px}
@keyframes blink{0%,100%{border-color:#e94560}50%{border-color:#7f1d1d}}
#alert-banner.active{animation:blink 1.5s infinite}
</style>
</head>
<body>
<header>
  <h1>FocusGuard 관리자</h1>
  <span id="refresh-info"></span>
</header>
<div id="alert-banner">
  <div>
    <div class="alert-label">학생 차단 중 — 해제 코드 입력 대기</div>
    <div class="alert-reason" id="alert-reason"></div>
    <div class="alert-time" id="alert-time"></div>
  </div>
</div>
<div class="nav">
  <button class="nav-btn active" data-sec="status" onclick="showSection(this)">시스템 상태</button>
  <button class="nav-btn" data-sec="events" onclick="showSection(this)">이벤트 로그</button>
  <button class="nav-btn" data-sec="lists" onclick="showSection(this)">목록 관리</button>
</div>
<div id="status" class="section active">
  <div class="card">
    <h2>실시간 상태</h2>
    <div class="status-grid" id="status-grid">
      <div class="s-item"><div class="s-value" style="color:#333">로딩...</div></div>
    </div>
  </div>
</div>
<div id="events" class="section">
  <div class="card">
    <h2>최근 이벤트 (최대 100건 · 최신순)</h2>
    <table>
      <thead>
        <tr><th style="width:140px">시각</th><th style="width:80px">유형</th><th style="width:130px">단계</th><th>내용</th></tr>
      </thead>
      <tbody id="events-body">
        <tr><td colspan="4" style="color:#444;text-align:center;padding:20px">로딩...</td></tr>
      </tbody>
    </table>
  </div>
</div>
<div id="lists" class="section">
  <div class="card">
    <h2>블랙리스트 / 화이트리스트</h2>
    <div class="list-nav">
      <button class="list-btn active" data-list="process_blacklist" onclick="switchList(this)">프로세스 블랙</button>
      <button class="list-btn" data-list="title_blacklist" onclick="switchList(this)">타이틀 블랙</button>
      <button class="list-btn" data-list="url_blacklist" onclick="switchList(this)">URL 블랙</button>
      <button class="list-btn" data-list="content_keywords" onclick="switchList(this)">키워드</button>
      <button class="list-btn" data-list="process_whitelist" onclick="switchList(this)">프로세스 화이트</button>
      <button class="list-btn" data-list="url_whitelist" onclick="switchList(this)">URL 화이트</button>
    </div>
    <div id="list-content"></div>
  </div>
</div>
<script>
var allLists = {};
var curList = 'process_blacklist';

function showSection(btn) {
  var sec = btn.getAttribute('data-sec');
  document.querySelectorAll('.section').forEach(function(s){s.classList.remove('active');});
  document.querySelectorAll('.nav-btn').forEach(function(b){b.classList.remove('active');});
  document.getElementById(sec).classList.add('active');
  btn.classList.add('active');
  if (sec === 'events') refreshEvents();
  if (sec === 'lists') loadLists();
}

function switchList(btn) {
  curList = btn.getAttribute('data-list');
  document.querySelectorAll('.list-btn').forEach(function(b){b.classList.remove('active');});
  btn.classList.add('active');
  renderList();
}

function getEntries(listType) {
  if (!allLists.blacklists) return [];
  var map = {
    process_blacklist: (allLists.blacklists || {}).process,
    title_blacklist:   (allLists.blacklists || {}).title,
    url_blacklist:     (allLists.blacklists || {}).url,
    content_keywords:  (allLists.blacklists || {}).content_keywords,
    process_whitelist: (allLists.whitelists || {}).process,
    url_whitelist:     (allLists.whitelists || {}).url
  };
  return map[listType] || [];
}

function renderList() {
  var el = document.getElementById('list-content');
  el.innerHTML = '';
  var entries = getEntries(curList);
  if (entries.length === 0) {
    var d = document.createElement('div');
    d.className = 'empty';
    d.textContent = '항목 없음';
    el.appendChild(d);
  } else {
    entries.forEach(function(entry) {
      var row = document.createElement('div');
      row.className = 'entry-row';
      var span = document.createElement('span');
      span.className = 'entry-text';
      span.textContent = entry;
      var btns = document.createElement('div');
      btns.className = 'entry-btns';
      var editBtn = document.createElement('button');
      editBtn.className = 'btn-edit';
      editBtn.textContent = '편집';
      var rmBtn = document.createElement('button');
      rmBtn.className = 'btn-rm';
      rmBtn.textContent = '삭제';
      (function(e, r) {
        editBtn.onclick = function() { startEdit(r, e); };
        rmBtn.onclick = function() { removeEntry(curList, e); };
      })(entry, row);
      btns.appendChild(editBtn);
      btns.appendChild(rmBtn);
      row.appendChild(span);
      row.appendChild(btns);
      el.appendChild(row);
    });
  }
  var addRow = document.createElement('div');
  addRow.className = 'add-row';
  var inp = document.createElement('input');
  inp.id = 'new-entry';
  inp.type = 'text';
  inp.placeholder = '새 항목 입력...';
  inp.addEventListener('keypress', function(e) { if (e.key === 'Enter') addEntry(); });
  var addBtn = document.createElement('button');
  addBtn.className = 'btn-add';
  addBtn.textContent = '추가';
  addBtn.onclick = addEntry;
  addRow.appendChild(inp);
  addRow.appendChild(addBtn);
  el.appendChild(addRow);
}

function startEdit(row, oldEntry) {
  var editRow = document.createElement('div');
  editRow.className = 'edit-row';
  var inp = document.createElement('input');
  inp.className = 'edit-inp';
  inp.type = 'text';
  inp.value = oldEntry;
  var saveBtn = document.createElement('button');
  saveBtn.className = 'btn-save';
  saveBtn.textContent = '저장';
  var cancelBtn = document.createElement('button');
  cancelBtn.className = 'btn-cancel';
  cancelBtn.textContent = '취소';
  saveBtn.onclick = function() { saveEdit(row, editRow, oldEntry, inp.value.trim()); };
  cancelBtn.onclick = function() { row.style.display = ''; editRow.remove(); };
  inp.addEventListener('keypress', function(e) { if (e.key === 'Enter') saveBtn.click(); });
  inp.addEventListener('keydown',  function(e) { if (e.key === 'Escape') cancelBtn.click(); });
  editRow.appendChild(inp);
  editRow.appendChild(saveBtn);
  editRow.appendChild(cancelBtn);
  row.style.display = 'none';
  row.parentNode.insertBefore(editRow, row.nextSibling);
  inp.focus();
  inp.select();
}

function saveEdit(origRow, editRow, oldEntry, newEntry) {
  if (!newEntry || newEntry === oldEntry) { origRow.style.display = ''; editRow.remove(); return; }
  postForm('/admin/lists/edit', {list_type: curList, old_entry: oldEntry, new_entry: newEntry})
    .then(function(d) {
      if (d.success) { editRow.remove(); loadLists(); }
      else alert('오류: ' + d.error);
    });
}

function postForm(url, data) {
  var body = Object.keys(data).map(function(k) {
    return encodeURIComponent(k) + '=' + encodeURIComponent(data[k]);
  }).join('&');
  return fetch(url, {
    method: 'POST',
    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
    body: body
  }).then(function(r) { return r.json(); });
}

function addEntry() {
  var inp = document.getElementById('new-entry');
  var entry = inp.value.trim();
  if (!entry) return;
  postForm('/admin/lists/add', {list_type: curList, entry: entry}).then(function(d) {
    if (d.success) { inp.value = ''; loadLists(); }
    else alert('오류: ' + d.error);
  });
}

function removeEntry(listType, entry) {
  postForm('/admin/lists/remove', {list_type: listType, entry: entry}).then(function(d) {
    if (d.success) loadLists();
    else alert('오류: ' + d.error);
  });
}

function loadLists() {
  fetch('/admin/lists').then(function(r) { return r.json(); }).then(function(d) {
    allLists = d;
    renderList();
  });
}

function esc(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function refreshStatus() {
  fetch('/admin/status').then(function(r) { return r.json(); }).then(function(d) {
    // 알림 배너: 오버레이 활성 시 표시
    var banner = document.getElementById('alert-banner');
    if (d.overlay_active) {
      banner.classList.add('active');
      document.getElementById('alert-reason').textContent = d.last_detection || '';
      document.getElementById('alert-time').textContent   = d.last_detection_time || '';
    } else {
      banner.classList.remove('active');
    }
    var grid = document.getElementById('status-grid');
    var monCls = d.monitoring ? 'ok' : 'err';
    var ovCls  = d.overlay_active ? 'warn' : 'ok';
    grid.innerHTML =
      '<div class="s-item"><div class="s-label">모니터링</div>' +
        '<div class="s-value ' + monCls + '">' + (d.monitoring ? '실행 중' : '중지') + '</div></div>' +
      '<div class="s-item"><div class="s-label">오버레이</div>' +
        '<div class="s-value ' + ovCls + '">' + (d.overlay_active ? '차단 표시 중' : '정상') + '</div></div>' +
      '<div class="s-item" style="grid-column:1/-1"><div class="s-label">마지막 탐지</div>' +
        '<div class="s-value" style="font-size:13px;font-weight:normal">' + esc(d.last_detection || '없음') + '</div>' +
        (d.last_detection_time
          ? '<div style="font-size:11px;color:#444;margin-top:4px">' + esc(d.last_detection_time) + '</div>'
          : '') +
      '</div>';
    document.getElementById('refresh-info').textContent = '갱신: ' + new Date().toLocaleTimeString();
  }).catch(function() {});
}

function refreshEvents() {
  fetch('/admin/events?limit=100').then(function(r) { return r.json(); }).then(function(d) {
    var tbody = document.getElementById('events-body');
    if (!d.events || d.events.length === 0) {
      tbody.innerHTML = '<tr><td colspan="4" style="color:#444;text-align:center;padding:20px">이벤트 없음</td></tr>';
      return;
    }
    tbody.innerHTML = d.events.map(function(e) {
      var ts     = (e.timestamp || '').replace('T', ' ').substring(0, 19);
      var detail = e.reason || e.block_reason || e.window_title || '';
      var llm    = e.llm_result ? ' [' + e.llm_result + ']' : '';
      var stage  = e.stage || e.type || '';
      return '<tr>' +
        '<td style="color:#555;white-space:nowrap">' + esc(ts) + '</td>' +
        '<td><span class="badge badge-' + esc(e.type || '') + '">' + esc(e.type || '') + '</span></td>' +
        '<td style="color:#888">' + esc(stage) + '</td>' +
        '<td>' + esc(detail + llm) + '</td>' +
        '</tr>';
    }).join('');
  }).catch(function() {});
}

refreshStatus();
refreshEvents();
setInterval(refreshStatus, 3000);
setInterval(refreshEvents, 10000);
</script>
</body>
</html>
"""


# 목록 유형 → (YAML 파일명, YAML 키) 매핑
_LIST_MAP = {
    "process_blacklist": ("blacklists.yaml", "process"),
    "title_blacklist":   ("blacklists.yaml", "title"),
    "url_blacklist":     ("blacklists.yaml", "url"),
    "content_keywords":  ("blacklists.yaml", "content_keywords"),
    "process_whitelist": ("whitelists.yaml", "process"),
    "url_whitelist":     ("whitelists.yaml", "url"),
}


class WebAuthServer:
    """
    LAN HTTP 서버. 해제 인증(/unlock)과 관리자 대시보드(/admin)를 함께 제공한다.

    스레드 안전성:
        - set_code/clear_code/_validate 는 _lock 으로 보호된다.
        - YAML 읽기/쓰기는 _yaml_lock 으로 직렬화한다.
        - HTTP 핸들러는 별도 스레드에서 실행되므로 콜백도 별도 스레드에서 호출된다.
    """

    def __init__(self, port: int = 8080, max_failed_attempts: int = 5):
        self.port = port
        self._max_failed_attempts = max_failed_attempts
        self._lock = threading.Lock()
        self._yaml_lock = threading.Lock()
        self._current_code: Optional[str] = None
        self._expires_at: float = 0.0
        self._failed_attempts: int = 0
        self._on_success: Optional[Callable[[], None]] = None
        self._on_lockout: Optional[Callable[[], None]] = None
        self._status_provider: Optional[Callable[[], dict]] = None
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

    def set_status_provider(self, provider: Callable[[], dict]) -> None:
        """관리자 대시보드 /admin/status 에 노출할 시스템 상태 딕셔너리를 반환하는 콜백을 등록한다."""
        self._status_provider = provider

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
                self._current_code = None
                self._failed_attempts = 0
                return True, ""

            self._failed_attempts += 1
            remaining = self._max_failed_attempts - self._failed_attempts
            if remaining <= 0:
                self._current_code = None
                self._failed_attempts = 0
                triggered_lockout = True
                msg = "잘못된 코드를 여러 번 입력하여 무효화되었습니다. 학생에게 새 코드를 요청하세요."
            else:
                msg = f"잘못된 코드입니다. (남은 시도 {remaining}회)"

        if triggered_lockout:
            logger.warning("[브루트포스 방어] 연속 실패 한도 초과 → 활성 코드 무효화")
            if self._on_lockout:
                try:
                    self._on_lockout()
                except Exception:
                    logger.exception("on_lockout 콜백 처리 중 오류")
        return False, msg

    @staticmethod
    def _read_events(limit: int = 100) -> list[dict]:
        """events.jsonl 파일의 마지막 limit 줄을 읽어 최신순 리스트로 반환한다."""
        path = config.LOG_DIR / "events.jsonl"
        if not path.exists():
            return []
        events: list[dict] = []
        try:
            with open(path, encoding="utf-8") as f:
                lines = f.readlines()
            for line in reversed(lines[-limit:]):
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        except Exception as e:
            logger.error(f"이벤트 로그 읽기 오류: {e}")
        return events

    @staticmethod
    def _read_lists() -> dict:
        """blacklists.yaml / whitelists.yaml의 현재 내용을 dict로 반환한다."""
        data_dir = config.BASE_DIR / "data"

        def _load(filename: str) -> dict:
            try:
                with open(data_dir / filename, encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
            except Exception:
                return {}

        bl = _load("blacklists.yaml")
        wl = _load("whitelists.yaml")
        return {
            "blacklists": {
                "process":          bl.get("process", []),
                "title":            bl.get("title", []),
                "url":              bl.get("url", []),
                "content_keywords": bl.get("content_keywords", []),
            },
            "whitelists": {
                "process": wl.get("process", []),
                "url":     wl.get("url", []),
            },
        }

    def _add_list_entry(self, list_type: str, entry: str) -> tuple[bool, str]:
        """list_type에 해당하는 YAML 파일에 entry를 추가하고 config 메모리를 갱신한다."""
        if list_type not in _LIST_MAP:
            return False, "잘못된 목록 유형입니다."
        filename, key = _LIST_MAP[list_type]
        path = config.BASE_DIR / "data" / filename
        with self._yaml_lock:
            try:
                with open(path, encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                lst = data.setdefault(key, [])
                if entry not in lst:
                    lst.append(entry)
                    with open(path, "w", encoding="utf-8") as f:
                        yaml.safe_dump(data, f, allow_unicode=True,
                                       default_flow_style=False, sort_keys=False)
                reload_lists()
                return True, ""
            except Exception as e:
                logger.error(f"목록 추가 오류 ({list_type}): {e}")
                return False, str(e)

    def _edit_list_entry(self, list_type: str, old_entry: str, new_entry: str) -> tuple[bool, str]:
        """list_type YAML 파일에서 old_entry를 new_entry로 교체하고 config 메모리를 갱신한다."""
        if list_type not in _LIST_MAP:
            return False, "잘못된 목록 유형입니다."
        if not new_entry:
            return False, "새 항목이 비어 있습니다."
        filename, key = _LIST_MAP[list_type]
        path = config.BASE_DIR / "data" / filename
        with self._yaml_lock:
            try:
                with open(path, encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                lst = data.get(key, [])
                if old_entry not in lst:
                    return False, "기존 항목을 찾을 수 없습니다."
                data[key] = [new_entry if e == old_entry else e for e in lst]
                with open(path, "w", encoding="utf-8") as f:
                    yaml.safe_dump(data, f, allow_unicode=True,
                                   default_flow_style=False, sort_keys=False)
                reload_lists()
                return True, ""
            except Exception as e:
                logger.error(f"목록 편집 오류 ({list_type}): {e}")
                return False, str(e)

    def _remove_list_entry(self, list_type: str, entry: str) -> tuple[bool, str]:
        """list_type에 해당하는 YAML 파일에서 entry를 제거하고 config 메모리를 갱신한다."""
        if list_type not in _LIST_MAP:
            return False, "잘못된 목록 유형입니다."
        filename, key = _LIST_MAP[list_type]
        path = config.BASE_DIR / "data" / filename
        with self._yaml_lock:
            try:
                with open(path, encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                if key in data and isinstance(data[key], list):
                    data[key] = [e for e in data[key] if e != entry]
                    with open(path, "w", encoding="utf-8") as f:
                        yaml.safe_dump(data, f, allow_unicode=True,
                                       default_flow_style=False, sort_keys=False)
                reload_lists()
                return True, ""
            except Exception as e:
                logger.error(f"목록 제거 오류 ({list_type}): {e}")
                return False, str(e)

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
        """HTTP 핸들러 클래스를 생성해 반환한다. 클로저로 outer(WebAuthServer)를 캡처한다."""
        outer = self

        class _Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                """기본 stderr 출력을 Python logging(DEBUG)으로 교체한다."""
                logger.debug("HTTP %s - %s", self.address_string(), format % args)

            def _write(self, status: int, content_type: str, body: bytes) -> None:
                """공통 HTTP 응답 헤더와 바디를 작성한다."""
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def _json(self, status: int, payload: dict) -> None:
                """JSON 응답을 작성하는 편의 메서드."""
                self._write(status, "application/json",
                            json.dumps(payload, ensure_ascii=False).encode("utf-8"))

            def do_GET(self):
                """GET 요청 처리: 학생용 해제 페이지 및 관리자 API 엔드포인트를 제공한다."""
                parts = self.path.split("?", 1)
                route = parts[0]
                query = parts[1] if len(parts) > 1 else ""

                if route in ("/", "/index.html"):
                    self._write(200, "text/html; charset=utf-8",
                                _HTML_PAGE.encode("utf-8"))

                elif route == "/admin":
                    self._write(200, "text/html; charset=utf-8",
                                _ADMIN_HTML.encode("utf-8"))

                elif route == "/admin/status":
                    status: dict = {}
                    if outer._status_provider:
                        try:
                            status = outer._status_provider()
                        except Exception as e:
                            logger.error(f"status_provider 오류: {e}")
                    self._json(200, status)

                elif route == "/admin/events":
                    params = urllib.parse.parse_qs(query)
                    try:
                        limit = int((params.get("limit") or ["100"])[0])
                    except ValueError:
                        limit = 100
                    limit = min(max(limit, 1), 500)
                    events = outer._read_events(limit)
                    self._json(200, {"events": events})

                elif route == "/admin/lists":
                    self._json(200, outer._read_lists())

                else:
                    self.send_error(404)

            def do_POST(self):
                """POST 요청 처리: 해제 코드 검증 및 관리자 목록 추가/제거를 처리한다."""
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length).decode("utf-8", errors="replace")
                params = urllib.parse.parse_qs(raw)

                if self.path == "/unlock":
                    submitted = (params.get("code") or [""])[0].strip()
                    ok, err = outer._validate(submitted)
                    if ok:
                        logger.info("[웹 해제 성공] 원격 인증 완료")
                        if outer._on_success:
                            try:
                                outer._on_success()
                            except Exception:
                                logger.exception("on_success 콜백 처리 중 오류")
                        self._json(200, {"success": True})
                    else:
                        logger.warning("[웹 해제 실패] %s", err)
                        self._json(200, {"success": False, "error": err})

                elif self.path in ("/admin/lists/add", "/admin/lists/remove"):
                    list_type = (params.get("list_type") or [""])[0].strip()
                    entry     = (params.get("entry") or [""])[0].strip()
                    if not entry:
                        self._json(400, {"success": False, "error": "항목이 비어 있습니다."})
                        return
                    if self.path.endswith("/add"):
                        ok, err = outer._add_list_entry(list_type, entry)
                    else:
                        ok, err = outer._remove_list_entry(list_type, entry)
                    if ok:
                        self._json(200, {"success": True})
                    else:
                        self._json(200, {"success": False, "error": err})

                elif self.path == "/admin/lists/edit":
                    list_type = (params.get("list_type") or [""])[0].strip()
                    old_entry = (params.get("old_entry") or [""])[0].strip()
                    new_entry = (params.get("new_entry") or [""])[0].strip()
                    if not old_entry or not new_entry:
                        self._json(400, {"success": False, "error": "항목이 비어 있습니다."})
                        return
                    ok, err = outer._edit_list_entry(list_type, old_entry, new_entry)
                    if ok:
                        self._json(200, {"success": True})
                    else:
                        self._json(200, {"success": False, "error": err})

                else:
                    self.send_error(404)

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
