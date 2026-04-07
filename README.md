# FocusGuard — 로컬 개발 버전

수업 방해 콘텐츠 탐지 및 차단 프로그램 (로컬 LLM 버전)

---

## 프로젝트 구조

```
focus_guard/
├── main.py           # 메인 컨트롤러 (진입점)
├── monitor.py        # 화면 캡처 + OCR 파이프라인
├── llm_client.py     # LLM 추상화 레이어 (로컬/클라우드 전환)
├── overlay.py        # 차단 오버레이 UI
├── event_logger.py   # 이벤트 로그 저장
├── config.py         # 전체 설정값
├── requirements.txt  # 의존성
└── logs/             # 자동 생성
    ├── focus_guard.log
    └── events.jsonl
```

---

## 탐지 흐름

```
1단계: 창 타이틀 블랙리스트 매칭   (즉시, ~1ms)
         ↓ 통과
2단계: URL 바 OCR + 키워드 매칭    (~100~300ms)
         ↓ 통과
3단계: 본문 OCR + 키워드 조합      (~200~400ms)
         ↓ 모호한 경우
4단계: Ollama 로컬 LLM 최종 판단   (~2~10초, 사양에 따라)
         ↓ BLOCK
차단 오버레이 표시 + 해제 요청 버튼
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
pip install paddlepaddle
pip install paddleocr
pip install -r requirements.txt
```

### 3. 실행

```bash
python main.py
```

---

## 설정 변경 (config.py)

| 항목 | 기본값 | 설명 |
|---|---|---|
| `POLL_INTERVAL` | 5.0초 | 화면 감지 주기 |
| `OLLAMA_MODEL` | gemma3:4b | 사용할 로컬 모델 |
| `KEYWORD_THRESHOLD` | 2 | 키워드 N개 이상 시 차단 |
| `USE_CLOUD_LLM` | False | 클라우드 전환 시 True |

### 블랙리스트 추가

`config.py` 의 `TITLE_BLACKLIST`, `URL_BLACKLIST`, `CONTENT_KEYWORDS` 에 항목 추가

### 화이트리스트 추가

`config.py` 의 `URL_WHITELIST` 에 허용할 도메인 추가

---

## 클라우드 전환 방법 (4월 말~)

`config.py` 에서:
```python
USE_CLOUD_LLM = True
```

`llm_client.py` 의 `CloudLLMClient.analyze()` 구현 후 전환 완료.
나머지 코드는 수정 불필요.

---

## 로그 확인

```bash
# 실시간 로그
tail -f logs/focus_guard.log

# 이벤트 로그 (JSON)
cat logs/events.jsonl
```

---

## 테스트 시나리오

| 시나리오 | 예상 결과 |
|---|---|
| 유튜브 탭 열기 | 창 타이틀 "YouTube" → 즉시 차단 |
| 디시인사이드 접속 | 창 타이틀 감지 → 차단 |
| VPN 우회 후 유튜브 | OCR URL 감지 → 차단 |
| 수업 관련 GitHub | 화이트리스트 통과 |
| 게임 실행 | 창 타이틀 or 프로세스 감지 → 차단 |
| 해제 요청 버튼 클릭 | logs/events.jsonl 에 UNLOCK_REQUEST 기록 |