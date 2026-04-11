"""
config.py
전체 설정값 중앙 관리
- 블랙리스트, 모델명, 타임아웃 등
- 클라우드 전환 시 USE_CLOUD_LLM = True 로 변경
"""


class Config:
    # ──────────────────────────────────────────
    # 해제 코드 (교수자가 학생에게 구두 전달)
    # ──────────────────────────────────────────
    UNLOCK_CODE: str = "1234"   # 실제 운영 시 변경 필요

    # ──────────────────────────────────────────
    # 모드 전환 (클라우드 전환 시 True)
    # ──────────────────────────────────────────
    USE_CLOUD_LLM: bool = False

    # ──────────────────────────────────────────
    # 모니터링 설정
    # ──────────────────────────────────────────
    POLL_INTERVAL: float = 5.0          # 화면 폴링 주기 (초)
    OCR_CONFIDENCE_THRESHOLD: float = 0.6

    # 콘텐츠 키워드 탐지 임계값 (N개 이상 동시 등장 시 차단)
    KEYWORD_THRESHOLD: int = 2

    # ──────────────────────────────────────────
    # Ollama 로컬 LLM
    # ──────────────────────────────────────────
    OLLAMA_HOST: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "gemma3:4b"     # gemma3:1b(초경량) / qwen2.5:3b 로 교체 가능
    LLM_TIMEOUT: int = 15               # 초

    # ──────────────────────────────────────────
    # 로그 저장 경로
    # ──────────────────────────────────────────
    LOG_DIR: str = "logs"

    # ──────────────────────────────────────────
    # 1단계: 창 타이틀 블랙리스트
    # ──────────────────────────────────────────
    TITLE_BLACKLIST: list = [
        # 영상 스트리밍
        "YouTube",
        "Twitch",
        "치지직",
        "아프리카TV",
        "Netflix",
        "왓챠", "Watcha",
        "웨이브", "Wavve",

        # 커뮤니티
        "디시인사이드",
        "에펨코리아", "FM코리아",
        "루리웹",
        "더쿠",
        "MLB파크",
        "인스티즈",
        "보배드림",
        "클리앙",
        "Reddit",
        "Twitter", "X.com",

        # SNS
        "Instagram",
        "Facebook",

        # 게임 런처 / 클라이언트
        "Steam",
        "Battle.net",
        "League of Legends",
        "VALORANT",
        "오버워치", "Overwatch",
        "로스트아크", "Lost Ark",
        "피파온라인", "FC 온라인",
        "메이플스토리",
        "리니지",

        # 쇼핑 / 웹툰
        "쿠팡",
        "네이버 웹툰",
        "카카오웹툰",
    ]

    # ──────────────────────────────────────────
    # 2단계: URL 키워드 블랙리스트
    # ──────────────────────────────────────────
    URL_BLACKLIST: list = [
        # 영상
        "youtube.com/watch",
        "youtube.com/shorts",
        "youtu.be",
        "twitch.tv",
        "chzzk.naver.com",
        "afreecatv.com",
        "netflix.com",
        "wavve.com",
        "watcha.com",

        # 커뮤니티
        "dcinside.com",
        "fmkorea.com",
        "ruliweb.com",
        "theqoo.net",
        "mlbpark.com",
        "instiz.net",
        "reddit.com",
        "twitter.com",
        "x.com",

        # SNS
        "instagram.com",
        "facebook.com",

        # 쇼핑
        "coupang.com",
        "gmarket.co.kr",
        "11st.co.kr",

        # 게임
        "store.steampowered.com",
        "op.gg",
        "neople.co.kr",      # 던파
    ]

    # ──────────────────────────────────────────
    # 2단계: 본문 콘텐츠 키워드 블랙리스트
    # ──────────────────────────────────────────
    CONTENT_KEYWORDS: list = [
        # 유튜브 UI
        "구독", "구독자", "조회수", "좋아요", "알림 설정",
        "자동재생", "다음 동영상", "댓글",

        # 커뮤니티 UI
        "갤러리", "개념글", "베스트글", "추천", "비추천",
        "짤", "ㅋㅋ", "ㄷㄷ",

        # 게임
        "인게임", "공략", "티어", "매칭 중", "배틀패스",
        "스킨", "아이템", "레이드",

        # 스트리밍 UI
        "팔로우", "후원", "채팅 참여", "라이브 중",

        # 쇼핑
        "장바구니", "바로구매", "무료배송",

        # SNS
        "팔로워", "팔로잉", "스토리",
    ]

    # ──────────────────────────────────────────
    # 화이트리스트 (차단 예외 URL)
    # ──────────────────────────────────────────
    URL_WHITELIST: list = [
        "ebs.co.kr",
        "khanacademy.org",
        "coursera.org",
        "github.com",
        "stackoverflow.com",
        "docs.python.org",
        # 학교 LMS 주소를 여기에 추가
        # "lms.university.ac.kr",
    ]