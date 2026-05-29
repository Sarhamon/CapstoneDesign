# FocusGuard

수업 방해 콘텐츠 탐지 및 차단 시스템

- **Phase 1 (완료)** — 학생 PC 로컬 실행. Ollama LLM + EasyOCR 기반 4단계 탐지
- **Phase 2 (진행 중)** — AWS 클라우드 연동. Lambda + DynamoDB + S3 + EC2 LLM 서버

---

## 프로젝트 구조

```
CapstoneDesign/
├── src/                  # 학생 PC 실행 코드
│   ├── main.py           # 메인 컨트롤러 (진입점)
│   ├── monitor.py        # 화면 캡처 + OCR 파이프라인
│   ├── llm_client.py     # LLM 추상화 (로컬 Ollama / EC2 Ollama)
│   ├── overlay.py        # 차단 오버레이 UI (Tkinter)
│   ├── event_logger.py   # 이벤트 저장 (로컬 JSONL + 원격 API)
│   ├── web_auth.py       # 해제 인증 HTTP 서버 + 관리자 대시보드
│   └── config.py         # 설정 관리 (pydantic-settings)
├── lambda/               # AWS Lambda 함수 코드
│   ├── fg_log_event.py   # POST /event/log — 이벤트 인제스트 (S3)
│   ├── fg_update_lists.py # POST /list/update — blocklist/allowlist CRUD (DynamoDB)
│   ├── fg_get_lists.py   # GET /list — blocklist/allowlist 조회 (DynamoDB)
│   ├── fg_get_events.py  # GET /events — 이벤트 로그 조회 (S3)
│   └── fg_unlock.py      # POST /unlock/{device_id} — 해제 인증 (S3)
├── scripts/              # 유틸리티 스크립트
│   └── seed_dynamodb.py  # DynamoDB 초기 데이터 적재
├── data/
│   ├── blacklists.yaml   # 프로세스·타이틀·URL·키워드 블랙리스트
│   └── whitelists.yaml   # 프로세스·URL 화이트리스트
├── docs/
│   └── index.html        # 프로젝트 진행 현황 리포트
├── .env.example          # 환경변수 설정 예시
└── requirements.txt
```

---

## 탐지 흐름

```
1단계: 창 타이틀 / 프로세스명 블랙리스트 매칭   (~1ms)
         ↓ 통과
2단계: URL 바 OCR + 키워드 매칭                (~100~300ms)
         ↓ 통과
3단계: 본문 OCR + 키워드 조합                  (~200~400ms)
         ↓ 모호한 경우
4단계: Ollama LLM 최종 판단                    (~2~10초)
         ↓ BLOCK
차단 오버레이 표시 + 웹 기반 해제 인증
```

---

## 설치 방법

### 1. Ollama 설치 및 모델 다운로드

```bash
# https://ollama.com/download 에서 설치

# 모델 다운로드 (택 1)
ollama pull gemma3:4b        # 권장 (균형)
ollama pull gemma3:1b        # 초경량 (저사양 PC)
ollama pull qwen2.5:3b       # 한국어 우수
```

### 2. Python 패키지 설치

```bash
pip install -r requirements.txt
```

### 3. 환경변수 설정

```bash
cp .env.example .env
# .env 파일을 열어 필요한 값 수정
```

### 4. 실행

```bash
cd src
python main.py
```

---

## 주요 설정 (.env)

| 항목 | 기본값 | 설명 |
|---|---|---|
| `POLL_INTERVAL` | 12.0 | OCR 포함 전체 검사 주기 (초) |
| `FAST_POLL_INTERVAL` | 1.0 | 포커스 창 변경 감지 주기 (초) |
| `OLLAMA_MODEL` | gemma3:4b | 사용할 로컬 LLM 모델 |
| `KEYWORD_THRESHOLD` | 2 | LLM 검증 트리거 최소 키워드 수 |
| `USE_CLOUD_LLM` | false | true 시 EC2 Ollama 서버 사용 |
| `CLOUD_LLM_HOST` | (없음) | EC2 Ollama 서버 주소 |
| `CLOUD_API_URL` | (없음) | API Gateway URL (이벤트 원격 전송) |
| `WEB_AUTH_PORT` | 8080 | 해제 인증 페이지 포트 |

### 블랙리스트 / 화이트리스트 수정

`data/blacklists.yaml` 과 `data/whitelists.yaml` 을 직접 편집한다.
앱 실행 중 변경하면 관리자 대시보드에서 **목록 갱신** 버튼으로 즉시 반영된다.

---

## 클라우드 LLM 전환 (Phase 2)

EC2에 Ollama가 설치된 후 `.env` 두 줄만 변경하면 전환된다.

```env
USE_CLOUD_LLM=true
CLOUD_LLM_HOST=http://ec2-xx-xx-xx-xx.ap-northeast-2.compute.amazonaws.com:11434
```

---

## 이벤트 클라우드 전송 (Phase 2)

`CLOUD_API_URL` 이 설정되면 차단 이벤트가 로컬 JSONL과 S3에 동시 기록된다.

```env
CLOUD_API_URL=https://xxxxxxxxxx.execute-api.ap-northeast-2.amazonaws.com
```

---

## 로그 확인

```bash
# 실시간 로그 (Windows PowerShell)
Get-Content logs/focus_guard.log -Wait

# 이벤트 로그 (JSON Lines)
Get-Content logs/events.jsonl
```

---

## 테스트 시나리오

| 시나리오 | 예상 결과 |
|---|---|
| 유튜브 탭 열기 | 창 타이틀 "YouTube" → 즉시 차단 |
| 디시인사이드 접속 | 창 타이틀 감지 → 차단 |
| VPN 우회 후 유튜브 | OCR URL 감지 → 차단 |
| 수업 관련 GitHub | 화이트리스트 통과 |
| 게임 실행 | 프로세스명 감지 → 차단 |
| 해제 인증 성공 | `logs/events.jsonl` 에 UNLOCK_REQUEST 기록 |

---

## Phase 2 클라우드 구조

```
[학생 PC]
  ├── 4단계 탐지 (타이틀 → OCR → LLM)
  ├── EventLogger → RemoteSink → POST /event/log
  └── BlockOverlay → 해제 요청 → POST /unlock/{device_id}
              ↓ HTTPS
       [API Gateway: focusguard-api-v2]
              ↓
          [Lambda × 5]
           │            │
           ▼            ▼
     [S3: focusguard-data]   [DynamoDB]
       (이벤트 로그)          (blocklist/allowlist)
                        ▲
               [EC2: Ollama LLM 서버]
```

진행 현황 상세: [docs/index.html](docs/index.html)

관리자 대시보드 (캡스톤 기간 한정): [docs/admin/index.html](docs/admin/index.html)
