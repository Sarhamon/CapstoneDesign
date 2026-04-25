"""
config.py
전체 설정값 중앙 관리
- 블랙리스트, 모델명, 타임아웃 등
- 클라우드 전환 시 USE_CLOUD_LLM = True 로 변경
"""


class Config:
    """
    FocusGuard 애플리케이션 전역 설정 클래스.

    모든 설정값은 클래스 변수로 선언되어 인스턴스 생성 없이 Config.변수명으로 접근한다.
    운영 환경에 맞게 아래 값들을 변경하여 동작을 제어한다.
    """

    # ──────────────────────────────────────────
    # 해제 코드 (교수자가 학생에게 구두 전달)
    # ──────────────────────────────────────────

    # 차단 오버레이를 해제할 때 입력하는 코드.
    # 교수자가 수업 중 학생에게 구두로 알려주며, 운영 시 반드시 변경해야 한다.
    UNLOCK_CODE: str = "1234"   # 실제 운영 시 변경 필요

    # ──────────────────────────────────────────
    # 모드 전환 (클라우드 전환 시 True)
    # ──────────────────────────────────────────

    # False: Ollama 로컬 LLM 사용 (인터넷 불필요)
    # True:  CloudLLMClient 사용 (Anthropic / OpenAI API 호출)
    USE_CLOUD_LLM: bool = False

    # ──────────────────────────────────────────
    # 모니터링 설정
    # ──────────────────────────────────────────

    # 화면 폴링 주기(초). 값이 작을수록 탐지가 빠르지만 CPU 사용량이 증가한다.
    POLL_INTERVAL: float = 3.0

    # EasyOCR 인식 결과 중 이 신뢰도(0~1) 이상인 텍스트만 분석에 사용한다.
    # 값이 너무 낮으면 오탐이 늘고, 너무 높으면 정상 텍스트가 누락될 수 있다.
    OCR_CONFIDENCE_THRESHOLD: float = 0.6

    # 콘텐츠 키워드 탐지 임계값.
    # CONTENT_KEYWORDS 목록에서 이 개수 이상의 키워드가 동시에 감지되면 차단한다.
    # 단일 키워드 오탐을 줄이기 위해 2 이상으로 설정한다.
    KEYWORD_THRESHOLD: int = 2

    # ──────────────────────────────────────────
    # Ollama 로컬 LLM
    # ──────────────────────────────────────────

    # Ollama 서버 주소. 기본 포트는 11434이며 로컬 실행을 전제로 한다.
    OLLAMA_HOST: str = "http://localhost:11434"

    # 사용할 Ollama 모델명.
    # gemma3:4b (기본) / gemma3:1b (초경량, 저사양 PC) / qwen2.5:3b (대안 모델)
    OLLAMA_MODEL: str = "gemma3:4b"

    # LLM API 호출 최대 대기 시간(초). 초과 시 UNSURE로 처리하여 차단하지 않는다.
    LLM_TIMEOUT: int = 60

    # ──────────────────────────────────────────
    # 로그 저장 경로
    # ──────────────────────────────────────────

    # 이벤트 로그 파일(.jsonl)이 저장될 디렉토리.
    # .gitignore에 등록되어 있으므로 저장소에 업로드되지 않는다.
    LOG_DIR: str = "logs"

    # ──────────────────────────────────────────
    # 프로세스 블랙/화이트리스트 (실행 파일명 기준)
    # ──────────────────────────────────────────

    # 포커스된 프로세스명이 여기에 있으면 OCR 없이 즉시 차단한다.
    PROCESS_BLACKLIST: list = [
        # 메신저 / 소셜
        "KakaoTalk.exe",
        "Discord.exe",

        # 게임 클라이언트
        "LeagueClient.exe",
        "VALORANT-Win64-Shipping.exe",
        "Steam.exe",
        "NexonPlug.exe",

        # 미디어
        "Melon.exe",

        # 앱 플레이어 (안드로이드)
        "Nox.exe",
        "dnplayer.exe",
        "HD-Player.exe",
        "NemuPlayer.exe",

        # 마인크래프트 (javaw.exe는 수업용 가능성 있어 제외)
        "MinecraftLauncher.exe",
        "Minecraft.Windows.exe",
    ]

    # 포커스된 프로세스명이 여기에 있으면 모든 검사를 건너뛰고 허용한다.
    PROCESS_WHITELIST: list = [
        # IDE / 텍스트 에디터
        "Code.exe",           # Visual Studio Code
        "Cursor.exe",         # Cursor IDE
        "idea64.exe",         # IntelliJ IDEA
        "eclipse.exe",        # Eclipse
        "STS.exe",            # Spring Tool Suite
        "pycharm64.exe",      # PyCharm

        # 시스템 / FocusGuard 자체
        "python.exe",
        "FocusGuard.exe",
        "cmd.exe",
        "powershell.exe",
        "WindowsTerminal.exe",
    ]

    # ──────────────────────────────────────────
    # 1단계: 창 타이틀 블랙리스트
    # ──────────────────────────────────────────
    # monitor.py의 _check_window_title()에서 활성 창 제목과 대소문자 무관 부분 일치로 비교한다.
    # 일치하면 LLM 검증 없이 즉시 차단한다.
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
        "일베", "ilbe",

        # SNS
        "Instagram",
        "Facebook",

        # 콘솔 플랫폼
        "PlayStation", "PlayStation Store",
        "Xbox", "Xbox Game Pass",
        "Nintendo Switch", "Nintendo eShop",

        # 게임 런처 / 클라이언트
        "Steam",
        "Battle.net",
        "Epic Games Launcher", "Epic Games",
        "Origin",
        "EA app",
        "Ubisoft Connect", "Uplay",
        "GOG Galaxy",
        "Rockstar Games Launcher",

        # 한국 게임
        "League of Legends",
        "Nexon",
        "VALORANT",
        "오버워치", "Overwatch",
        "로스트아크", "Lost Ark",
        "피파온라인", "FC 온라인",
        "메이플스토리", "MapleStory",
        "리니지",
        "블레이드 앤 소울", "Blade & Soul",
        "검은사막", "Black Desert",
        "던전앤파이터", "Dungeon Fighter",
        "서든어택",
        "사이퍼즈",
        "카트라이더",
        "바람의나라",

        # 글로벌 인기 게임
        "Minecraft",
        "Fortnite",
        "PUBG", "PlayerUnknown",
        "Apex Legends",
        "Call of Duty",
        "Grand Theft Auto", "GTA V", "GTA VI",
        "Elden Ring",
        "Dark Souls",
        "Counter-Strike", "CS2", "CS:GO",
        "Dota 2",
        "Hearthstone",
        "World of Warcraft",
        "Starcraft", "스타크래프트",
        "Diablo",
        "Cyberpunk 2077",
        "Destiny 2",
        "Rainbow Six Siege",
        "Battlefield",
        "Warframe",
        "Path of Exile",
        "Genshin Impact", "원신",
        "Honkai: Star Rail", "붕괴: 스타레일",
        "Arknights", "명일방주",
        "Blue Archive", "블루 아카이브",
        "Roblox",
        "Among Us",
        "Fall Guys",
        "Rocket League",
        "Clash of Clans",
        "Clash Royale",
        "Pokémon",

        # 게임 뉴스 / 정보 사이트
        "IGN",
        "GameSpot",
        "인벤",
        "게임조선",

        # 게임 할인 / 딜 사이트
        "IsThereAnyDeal",
        "GG.deals",
        "G2A",
        "Kinguin",
        "CDKeys",
        "Eneba",
        "Fanatical",
        "Green Man Gaming",
        "Humble Bundle", "Humble Store",
        "itch.io",
        "IndieGala",

        # 쇼핑 / 웹툰
        "쿠팡",
        "네이버 웹툰",
        "카카오웹툰",
        "레진코믹스",
        "뉴토끼"
    ]

    # ──────────────────────────────────────────
    # 2단계: URL 키워드 블랙리스트
    # ──────────────────────────────────────────
    # monitor.py의 _check_url_keywords()에서 화면 상단(주소 표시줄 영역) OCR 텍스트와
    # 대소문자 무관 부분 일치로 비교한다. 일치하면 즉시 차단한다.
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
        "ilbe.com",

        # SNS
        "instagram.com",
        "facebook.com",

        # 쇼핑
        "coupang.com",
        "gmarket.co.kr",
        "11st.co.kr",

        # 게임 플랫폼 / 런처
        "store.steampowered.com",
        "steamcommunity.com",
        "playstation.com",
        "xbox.com",
        "nintendo.com",
        "epicgames.com",
        "ea.com",
        "origin.com",
        "ubisoft.com",
        "rockstargames.com",
        "gog.com",
        "bethesda.net",
        "battlenet.com",

        # 게임 퍼블리셔 / 개발사
        "riotgames.com",
        "leagueoflegends.com",
        "minecraft.net",
        "fortnite.com",
        "pubg.com",
        "dota2.com",
        "hoyoverse.com",
        "mihoyo.com",
        "arknights.global",
        "bluearchive.jp",
        "roblox.com",
        "rocketleague.com",
        "supercell.com",
        "nexon.com",
        "ncsoft.com",
        "plaync.com",
        "pmang.com",
        "hangame.com",
        "neople.co.kr",

        # 게임 통계 / 공략
        "op.gg",
        "fow.kr",
        "blitz.gg",
        "u.gg",
        "dotabuff.com",
        "hltv.org",
        "tracker.gg",
        "psnprofiles.com",
        "howlongtobeat.com",

        # 게임 뉴스 / 정보
        "ign.com",
        "gamespot.com",
        "polygon.com",
        "kotaku.com",
        "pcgamer.com",
        "eurogamer.net",
        "gameinformer.com",
        "inven.co.kr",
        "gamechosun.co.kr",

        # 브라우저 게임
        "poki.com",
        "crazygames.com",
        "miniclip.com",
        "coolmathgames.com",
        "kongregate.com",
        "addictinggames.com",
        "newgrounds.com",
        "kizi.com",

        # 게임 할인 / 딜 사이트 (글로벌)
        "isthereanydeal.com",
        "gg.deals",
        "cheapshark.com",
        "allkeyshop.com",
        "keyforsteam.com",
        "g2a.com",
        "g2play.net",
        "kinguin.net",
        "cdkeys.com",
        "eneba.com",
        "fanatical.com",
        "greenmangaming.com",
        "wingamestore.com",
        "gamebillet.com",
        "voidu.com",
        "gamesplanet.com",
        "2game.com",
        "dlgamer.com",
        "indiegala.com",
        "bundlestars.com",
        "humblebundle.com",
        "humblestore.com",
        "itch.io",

        # 게임 할인 / 딜 사이트 (한국)
        "gameple.co.kr",
        "playforum.net",
    ]

    # ──────────────────────────────────────────
    # 2단계: 본문 콘텐츠 키워드 블랙리스트
    # ──────────────────────────────────────────
    # monitor.py의 _check_content_keywords()에서 화면 본문 OCR 텍스트와 비교한다.
    # KEYWORD_THRESHOLD 개수 이상 동시에 감지되었을 때만 LLM 검증 단계로 넘어간다.
    # 단일 키워드로는 차단하지 않으므로, 일상 문서 작업 중 오탐 가능성을 낮춘다.
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
        "트로피", "업적 달성", "게임패스",
        "시즌패스", "캐릭터 선택", "로비",
        "파티 참가", "파티 초대", "플레이 시간",
        "퀘스트", "던전", "보스",

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
    # 이 목록에 포함된 도메인/텍스트가 감지되면 블랙리스트 검사를 건너뛰고 허용한다.
    # 학교 LMS, 교육 사이트 등 수업에 필요한 주소를 추가한다.
    # monitor.py의 _is_whitelisted()에서 창 타이틀·URL 영역·본문 영역에 대해 각각 확인한다.
    URL_WHITELIST: list = [
        "ebs.co.kr",
        "khanacademy.org",
        "coursera.org",
        "github.com",
        "stackoverflow.com",
        "docs.python.org",
        # 학교 도메인
        "yeonsung.ac.kr",
        "eclass.yeonsung.ac.kr",
        # 학교 LMS 주소를 여기에 추가
    ]
