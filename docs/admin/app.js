/* ══════════════════════════════════════════
   [1] 전역 상태
   ══════════════════════════════════════════ */

let API_URL = (localStorage.getItem('FG_API_URL') || '').trim();

const KEY_TO_LIST_TYPE = {
  pb: 'process_blacklist',
  pw: 'process_whitelist',
  tb: 'title_blacklist',
  ub: 'url_blacklist',
  uw: 'url_whitelist',
  ck: 'content_keywords',
};

const LISTS = {
  pb: ["KakaoTalk.exe","Discord.exe","LeagueClient.exe","VALORANT-Win64-Shipping.exe","Steam.exe","NexonPlug.exe","Melon.exe","Nox.exe","dnplayer.exe","HD-Player.exe","NemuPlayer.exe","MinecraftLauncher.exe","Minecraft.Windows.exe"],
  pw: ["Code.exe","Cursor.exe","idea64.exe","eclipse.exe","STS.exe","pycharm64.exe","python.exe","FocusGuard.exe","cmd.exe","powershell.exe","WindowsTerminal.exe"],
  tb: ["YouTube","Twitch","치지직","아프리카TV","Netflix","왓챠","Watcha","웨이브","Wavve","디시인사이드","에펨코리아","FM코리아","루리웹","더쿠","MLB파크","인스티즈","보배드림","클리앙","Reddit","Twitter","X.com","일베","ilbe","Instagram","Facebook","Steam","League of Legends","Nexon","VALORANT","Minecraft","Fortnite","PUBG","Roblox"],
  ub: ["youtube.com/watch","youtube.com/shorts","youtu.be","twitch.tv","chzzk.naver.com","afreecatv.com","netflix.com","wavve.com","watcha.com","dcinside.com","fmkorea.com","reddit.com","twitter.com","x.com","instagram.com","facebook.com","store.steampowered.com","riotgames.com","leagueoflegends.com","minecraft.net","roblox.com"],
  uw: ["ebs.co.kr","khanacademy.org","coursera.org","github.com","stackoverflow.com","docs.python.org","yeonsung.ac.kr","eclass.yeonsung.ac.kr"],
  ck: ["구독","구독자","조회수","좋아요","알림 설정","자동재생","다음 동영상","댓글","갤러리","개념글","베스트글","짤","ㅋㅋ","ㄷㄷ","인게임","공략","티어","매칭 중","배틀패스","스킨","아이템","레이드","트로피","팔로우","후원","채팅 참여","라이브 중","장바구니","바로구매","무료배송","팔로워","팔로잉","스토리"],
};

let allEvents  = [];
let filterType = 'ALL';

/* ══════════════════════════════════════════
   [2] API URL 관리
   ══════════════════════════════════════════ */

function setApiUrl() {
  const val = document.getElementById('api-url-inp').value.trim().replace(/\/$/, '');
  API_URL = val;
  localStorage.setItem('FG_API_URL', val);
  updateApiStatus(null);
  if (val) loadListsFromAPI();
  else toast('🔌 API 연결 해제');
}

function updateApiStatus(ok) {
  const el = document.getElementById('api-status');
  if (!el) return;
  if (!API_URL) {
    el.textContent = '미연결'; el.style.color = 'var(--ink3)';
  } else if (ok === true) {
    el.textContent = '✓ 연결됨'; el.style.color = 'var(--mint-d)';
  } else if (ok === false) {
    el.textContent = '✗ 연결 실패'; el.style.color = 'var(--rose-d)';
  } else {
    el.textContent = '확인 중...'; el.style.color = 'var(--peach-d)';
  }
}

/* ══════════════════════════════════════════
   [3] API — 목록 로드 (GET /list)
   ══════════════════════════════════════════ */

async function loadListsFromAPI() {
  if (!API_URL) { toast('⚠️ API URL을 먼저 설정하세요'); return; }
  updateApiStatus(null);
  try {
    const resp = await fetch(API_URL + '/list');
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    const bl = data.blacklists || {};
    const wl = data.whitelists || {};
    if (bl.process)          LISTS.pb = bl.process;
    if (wl.process)          LISTS.pw = wl.process;
    if (bl.title)            LISTS.tb = bl.title;
    if (bl.url)              LISTS.ub = bl.url;
    if (wl.url)              LISTS.uw = wl.url;
    if (bl.content_keywords) LISTS.ck = bl.content_keywords;
    renderAllLists();
    updateApiStatus(true);
    const total = Object.values(LISTS).reduce((s, a) => s + a.length, 0);
    toast(`✅ 목록 로드 완료 (${total}개)`);
  } catch (e) {
    updateApiStatus(false);
    toast(`❌ 목록 로드 실패: ${e.message}`);
  }
}

/* ══════════════════════════════════════════
   [4] API — 이벤트 로드 (GET /events)
   ══════════════════════════════════════════ */

async function loadEventsFromAPI() {
  if (!API_URL) { toast('⚠️ API URL을 먼저 설정하세요'); return; }
  toast('⏳ 이벤트 로드 중...');
  try {
    const resp = await fetch(API_URL + '/events?limit=200&days=7');
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    allEvents = (data.events || []).sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
    updateKPI(); renderLogs(); renderStats();
    toast(`✅ ${allEvents.length}개 이벤트 로드 완료`);
  } catch (e) {
    toast(`❌ 이벤트 로드 실패: ${e.message}`);
  }
}

/* ══════════════════════════════════════════
   [5] API — 목록 변경 (POST /list/update)
   ══════════════════════════════════════════ */

async function callListUpdate(action, key, entry, oldEntry, newEntry) {
  if (!API_URL) return true;
  const body = { action, list_type: KEY_TO_LIST_TYPE[key] };
  if (action === 'edit') {
    body.old_entry = oldEntry;
    body.new_entry = newEntry;
  } else {
    body.entry = entry;
  }
  try {
    const resp = await fetch(API_URL + '/list/update', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return true;
  } catch (e) {
    toast(`❌ API 반영 실패: ${e.message}`);
    return false;
  }
}

/* ══════════════════════════════════════════
   [6] 내비게이션
   ══════════════════════════════════════════ */

function navigate(section, el) {
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  el.classList.add('active');
  document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
  document.getElementById('section-' + section).classList.add('active');
  if (section === 'lists')  renderAllLists();
  if (section === 'stats')  renderStats();
  if (section === 'unlock') loadUnlockRequests();
}

/* ══════════════════════════════════════════
   [6-1] 해제 요청 알림
   ══════════════════════════════════════════ */

let requestsData    = [];
let approveHistory  = [];
let reqApprovedToday = 0;

async function loadUnlockRequests() {
  if (!API_URL) { toast('⚠️ API URL을 먼저 설정하세요'); return; }
  try {
    const resp = await fetch(API_URL + '/unlock');
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    requestsData = data.pending || [];
    renderRequests();
    document.getElementById('badge-requests').textContent    = requestsData.length || '0';
    document.getElementById('req-pending-count').textContent = requestsData.length;
  } catch (e) {
    toast(`❌ 요청 목록 로드 실패: ${e.message}`);
  }
}

function renderRequests() {
  const tbody = document.getElementById('requests-tbody');
  if (!requestsData.length) {
    tbody.innerHTML = '<tr><td colspan="4"><div class="empty"><div class="empty-ico">✅</div>대기 중인 요청 없음</div></td></tr>';
    return;
  }
  tbody.innerHTML = requestsData.map(r => {
    const ts = new Date(r.requested_at).toLocaleString('ko-KR', {
      month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
    });
    return `<tr>
      <td><span style="font-family:var(--fm);color:var(--sky-d)">${esc(r.device_id)}</span></td>
      <td style="color:var(--ink3);white-space:nowrap">${ts}</td>
      <td style="color:var(--ink)">${esc(r.reason || '—')}</td>
      <td>
        <button class="btn btn-mint" style="padding:5px 14px;font-size:12px"
                onclick="approveRequest('${esc(r.device_id)}', '${esc(r.reason || '')}')">✅ 승인</button>
      </td>
    </tr>`;
  }).join('');
}

async function approveRequest(device_id, reason) {
  if (!API_URL) { toast('⚠️ API URL을 먼저 설정하세요'); return; }
  try {
    const resp = await fetch(`${API_URL}/unlock/${device_id}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'approve', device_id }),
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    requestsData = requestsData.filter(r => r.device_id !== device_id);
    reqApprovedToday++;
    approveHistory.unshift({ time: new Date().toLocaleString('ko-KR'), device_id, reason });
    renderRequests();
    renderApproveHistory();
    document.getElementById('badge-requests').textContent     = requestsData.length || '0';
    document.getElementById('req-pending-count').textContent  = requestsData.length;
    document.getElementById('req-approved-count').textContent = reqApprovedToday;
    toast(`✅ ${device_id} 승인 완료`);
  } catch (e) {
    toast(`❌ 승인 실패: ${e.message}`);
  }
}

function renderApproveHistory() {
  const tbody = document.getElementById('approve-history');
  if (!approveHistory.length) {
    tbody.innerHTML = '<tr><td colspan="3"><div class="empty" style="padding:18px"><div class="empty-ico">📜</div>승인 이력 없음</div></td></tr>';
    return;
  }
  tbody.innerHTML = approveHistory.slice(0, 20).map(h => `
    <tr>
      <td style="color:var(--ink3)">${h.time}</td>
      <td><span style="font-family:var(--fm);color:var(--sky-d)">${esc(h.device_id)}</span></td>
      <td style="color:var(--ink)">${esc(h.reason || '—')}</td>
    </tr>`).join('');
}

/* ══════════════════════════════════════════
   [7] 사이드바 시계
   ══════════════════════════════════════════ */

function tick() {
  document.getElementById('sidebar-time').textContent =
    new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}
setInterval(tick, 1000);
tick();

/* ══════════════════════════════════════════
   [8] 토스트 알림
   ══════════════════════════════════════════ */

function toast(msg, dur = 2300) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), dur);
}

/* ══════════════════════════════════════════
   [9] 로그 파일 로드 (파일 폴백)
   ══════════════════════════════════════════ */

function loadLogFile() {
  document.getElementById('file-input').click();
}

function onFileSelected(e) {
  const file = e.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = ev => {
    const lines = ev.target.result.split('\n').filter(l => l.trim());
    allEvents = [];
    for (const line of lines) {
      try { allEvents.push(JSON.parse(line)); } catch {}
    }
    allEvents.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
    updateKPI(); renderLogs(); renderStats();
    toast(`✅ ${allEvents.length}개 이벤트 로드 완료`);
  };
  reader.readAsText(file, 'utf-8');
  e.target.value = '';
}

/* ══════════════════════════════════════════
   [10] KPI 카드 업데이트
   ══════════════════════════════════════════ */

function updateKPI() {
  const blocks  = allEvents.filter(e => e.type === 'BLOCK');
  const allows  = allEvents.filter(e => e.type === 'ALLOW');
  const unlocks = allEvents.filter(e => e.type === 'UNLOCK_REQUEST');
  const llm     = blocks.filter(e => e.llm_result === 'BLOCK');

  document.getElementById('stat-blocks').textContent  = blocks.length;
  document.getElementById('stat-allows').textContent  = allows.length;
  document.getElementById('stat-unlocks').textContent = unlocks.length;
  document.getElementById('stat-llm').textContent     = llm.length;
  document.getElementById('badge-total').textContent  = allEvents.length;

  const total = blocks.length + allows.length;
  const rate  = total ? Math.round(blocks.length / total * 100) : 0;
  document.getElementById('stat-rate').textContent     = rate + '%';
  document.getElementById('stat-rule').textContent     = blocks.filter(e => e.llm_result === 'RULE_BASED').length;
  document.getElementById('stat-llm2').textContent     = llm.length;
  document.getElementById('stat-unlocks2').textContent = unlocks.length;
}

/* ══════════════════════════════════════════
   [11] 이벤트 로그 테이블
   ══════════════════════════════════════════ */

function renderLogs() {
  const search = document.getElementById('log-search').value.toLowerCase();
  const filtered = allEvents.filter(e => {
    if (filterType !== 'ALL' && e.type !== filterType) return false;
    return !search || JSON.stringify(e).toLowerCase().includes(search);
  });

  const tbody = document.getElementById('log-tbody');
  if (!filtered.length) {
    tbody.innerHTML = '<tr><td colspan="5"><div class="empty"><div class="empty-ico">🔍</div>표시할 이벤트 없음</div></td></tr>';
    return;
  }

  tbody.innerHTML = filtered.slice(0, 500).map(e => {
    const t  = new Date(e.timestamp);
    const ts = t.toLocaleString('ko-KR', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' });
    const tb = e.type === 'BLOCK' ? '<span class="badge badge-block">BLOCK</span>'
             : e.type === 'ALLOW' ? '<span class="badge badge-allow">ALLOW</span>'
             :                      '<span class="badge badge-unlock">UNLOCK</span>';
    const stg = e.stage ? `<span class="stage-tag">${e.stage}</span>` : '<span style="color:var(--ink3)">—</span>';
    const rsn = esc(e.reason || e.window_title || e.block_reason || '');
    const lb  = e.llm_result
      ? (e.llm_result === 'RULE_BASED' ? '<span class="badge badge-rule">RULE</span>'
       : e.llm_result === 'BLOCK'      ? '<span class="badge badge-block">BLOCK</span>'
       :                                  `<span class="badge badge-allow">${e.llm_result}</span>`)
      : '<span style="color:var(--ink3)">—</span>';
    return `<tr>
      <td style="color:var(--ink3);white-space:nowrap">${ts}</td>
      <td>${tb}</td><td>${stg}</td>
      <td style="max-width:340px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--ink)">${rsn}</td>
      <td>${lb}</td>
    </tr>`;
  }).join('');
}

function setFilter(type, el) {
  filterType = type;
  document.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
  el.classList.add('active');
  renderLogs();
}

function filterLogs() { renderLogs(); }

function clearLogs() {
  allEvents = [];
  updateKPI(); renderLogs(); renderStats();
  toast('🗑 로그가 초기화되었습니다');
}

/* ══════════════════════════════════════════
   [12] 통계 차트
   ══════════════════════════════════════════ */

function renderStats() {
  const blocks = allEvents.filter(e => e.type === 'BLOCK');

  const sc = {};
  blocks.forEach(e => { const k = e.stage || '기타'; sc[k] = (sc[k] || 0) + 1; });
  renderBars('stage-chart', sc, 'var(--rose-d)');

  const rc = {};
  blocks.forEach(e => { const r = (e.reason || '').slice(0, 30); rc[r] = (rc[r] || 0) + 1; });
  const top = Object.fromEntries(Object.entries(rc).sort((a, b) => b[1] - a[1]).slice(0, 10));
  renderBars('reason-chart', top, 'var(--sky-d)');

  const h = new Array(24).fill(0);
  blocks.forEach(e => { try { h[new Date(e.timestamp).getHours()]++; } catch {} });
  const mx = Math.max(...h, 1);
  document.getElementById('hourly-chart').innerHTML = h.map((c, i) =>
    `<div class="h-bar" title="${i}시: ${c}건"
          style="height:${Math.max(4, c / mx * 100)}%;opacity:${0.2 + 0.8 * (c / mx)}"></div>`
  ).join('');
}

function renderBars(id, obj, color) {
  const el      = document.getElementById(id);
  const entries = Object.entries(obj);
  if (!entries.length) {
    el.innerHTML = '<div class="empty" style="padding:14px"><div class="empty-ico">📊</div>데이터 없음</div>';
    return;
  }
  const max = Math.max(...entries.map(([, v]) => v), 1);
  el.innerHTML = entries.map(([k, v]) =>
    `<div class="bar-row">
      <div class="bar-lbl" title="${esc(k)}">${esc(k)}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${v / max * 100}%;background:${color}"></div></div>
      <div class="bar-num">${v}</div>
    </div>`
  ).join('');
}

/* ══════════════════════════════════════════
   [13] 목록 편집 CRUD
   ══════════════════════════════════════════ */

const listDefs = {
  pb: { el: 'list-pb', count: 'pb-count' },
  pw: { el: 'list-pw', count: 'pw-count' },
  tb: { el: 'list-tb', count: 'tb-count' },
  ub: { el: 'list-ub', count: 'ub-count' },
  uw: { el: 'list-uw', count: 'uw-count' },
  ck: { el: 'list-ck', count: 'ck-count' },
};

function renderList(key) {
  const { el, count } = listDefs[key];
  const items = LISTS[key];
  document.getElementById(count).textContent = `(${items.length})`;
  document.getElementById(el).innerHTML = items.map((item, i) =>
    `<div class="list-item">
      <span class="list-item-txt" title="${esc(item)}">${esc(item)}</span>
      <button class="rm-btn" onclick="removeItem('${key}',${i})" title="삭제">✕</button>
    </div>`
  ).join('') || '<div class="empty" style="padding:10px;font-size:12px">항목 없음</div>';
}

function renderAllLists() { Object.keys(listDefs).forEach(renderList); }

async function addItem(key, inputId) {
  const inp = document.getElementById(inputId);
  const val = inp.value.trim();
  if (!val) return;
  if (LISTS[key].includes(val)) { toast('⚠️ 이미 존재하는 항목입니다'); return; }
  const ok = await callListUpdate('add', key, val);
  if (ok) {
    LISTS[key].push(val);
    inp.value = '';
    renderList(key);
    toast(`✅ "${val}" 추가됨`);
  }
}

async function removeItem(key, idx) {
  const entry = LISTS[key][idx];
  const ok = await callListUpdate('remove', key, entry);
  if (ok) {
    LISTS[key].splice(idx, 1);
    renderList(key);
    toast(`🗑 "${entry}" 삭제됨`);
  }
}

function switchListTab(name, el) {
  document.querySelectorAll('.sub-tab').forEach(t => t.classList.remove('active'));
  el.classList.add('active');
  document.querySelectorAll('.list-tab').forEach(t => t.style.display = 'none');
  document.getElementById('list-' + name).style.display = '';
}

/* ══════════════════════════════════════════
   [14] (예약)
   ══════════════════════════════════════════ */

/* ══════════════════════════════════════════
   [15] 유틸
   ══════════════════════════════════════════ */

function esc(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

/* ══════════════════════════════════════════
   [16] 페이지 초기화
   ══════════════════════════════════════════ */

// 시간대 레이블 생성
const hLabels = document.getElementById('h-labels');
if (hLabels) {
  for (let i = 0; i < 24; i++) {
    const d = document.createElement('div');
    d.className = 'h-label';
    d.textContent = i;
    hLabels.appendChild(d);
  }
}

// 저장된 API URL 복원
if (API_URL) {
  document.getElementById('api-url-inp').value = API_URL;
  loadListsFromAPI();
} else {
  renderAllLists();
}
updateApiStatus(API_URL ? null : null);
updateKPI();
