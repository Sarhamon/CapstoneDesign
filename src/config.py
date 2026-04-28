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


    WEB_AUTH_PORT: int = 8080


    UNLOCK_CODE_TTL: int = 120


    UNLOCK_CODE_LENGTH: int = 6


    UNLOCK_MAX_FAILED_ATTEMPTS: int = 5


    KEYBOARD_BLOCK_ENABLED: bool = False


    USE_CLOUD_LLM: bool = False


    FAST_POLL_INTERVAL: float = 1.0


    POLL_INTERVAL: float = 12.0


    OCR_CONFIDENCE_THRESHOLD: float = 0.6


    KEYWORD_THRESHOLD: int = 2


    OLLAMA_HOST: str = "http://localhost:11434"


    OLLAMA_MODEL: str = "gemma3:4b"


    LLM_TIMEOUT: int = 60


    LOG_DIR: str = "logs"


    PROCESS_BLACKLIST: list = [

        "KakaoTalk.exe",
        "Discord.exe",


        "LeagueClient.exe",
        "VALORANT-Win64-Shipping.exe",
        "Steam.exe",
        "NexonPlug.exe",


        "Melon.exe",


        "Nox.exe",
        "dnplayer.exe",
        "HD-Player.exe",
        "NemuPlayer.exe",


        "MinecraftLauncher.exe",
        "Minecraft.Windows.exe",
    ]


    PROCESS_WHITELIST: list = [

        "Code.exe",
        "Cursor.exe",
        "idea64.exe",
        "eclipse.exe",
        "STS.exe",
        "pycharm64.exe",


        "python.exe",
        "FocusGuard.exe",
        "cmd.exe",
        "powershell.exe",
        "WindowsTerminal.exe",
    ]


    TITLE_BLACKLIST: list = [

        "YouTube",
        "Twitch",
        "치지직",
        "아프리카TV",
        "Netflix",
        "왓챠", "Watcha",
        "웨이브", "Wavve",


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


        "Instagram",
        "Facebook",


        "PlayStation", "PlayStation Store",
        "Xbox", "Xbox Game Pass",
        "Nintendo Switch", "Nintendo eShop",


        "Steam",
        "Battle.net",
        "Epic Games Launcher", "Epic Games",
        "Origin",
        "EA app",
        "Ubisoft Connect", "Uplay",
        "GOG Galaxy",
        "Rockstar Games Launcher",


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


        "IGN",
        "GameSpot",
        "인벤",
        "게임조선",


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


        "쿠팡",
        "네이버 웹툰",
        "카카오웹툰",
        "레진코믹스",
        "뉴토끼"
    ]


    URL_BLACKLIST: list = [

        "youtube.com/watch",
        "youtube.com/shorts",
        "youtu.be",
        "twitch.tv",
        "chzzk.naver.com",
        "afreecatv.com",
        "netflix.com",
        "wavve.com",
        "watcha.com",


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


        "instagram.com",
        "facebook.com",


        "coupang.com",
        "gmarket.co.kr",
        "11st.co.kr",


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


        "op.gg",
        "fow.kr",
        "blitz.gg",
        "u.gg",
        "dotabuff.com",
        "hltv.org",
        "tracker.gg",
        "psnprofiles.com",
        "howlongtobeat.com",


        "ign.com",
        "gamespot.com",
        "polygon.com",
        "kotaku.com",
        "pcgamer.com",
        "eurogamer.net",
        "gameinformer.com",
        "inven.co.kr",
        "gamechosun.co.kr",


        "poki.com",
        "crazygames.com",
        "miniclip.com",
        "coolmathgames.com",
        "kongregate.com",
        "addictinggames.com",
        "newgrounds.com",
        "kizi.com",


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


        "gameple.co.kr",
        "playforum.net",
    ]


    CONTENT_KEYWORDS: list = [

        "구독", "구독자", "조회수", "좋아요", "알림 설정",
        "자동재생", "다음 동영상", "댓글",


        "갤러리", "개념글", "베스트글", "추천", "비추천",
        "짤", "ㅋㅋ", "ㄷㄷ",


        "인게임", "공략", "티어", "매칭 중", "배틀패스",
        "스킨", "아이템", "레이드",
        "트로피", "업적 달성", "게임패스",
        "시즌패스", "캐릭터 선택", "로비",
        "파티 참가", "파티 초대", "플레이 시간",
        "퀘스트", "던전", "보스",


        "팔로우", "후원", "채팅 참여", "라이브 중",


        "장바구니", "바로구매", "무료배송",


        "팔로워", "팔로잉", "스토리",
    ]


    URL_WHITELIST: list = [
        "ebs.co.kr",
        "khanacademy.org",
        "coursera.org",
        "github.com",
        "stackoverflow.com",
        "docs.python.org",

        "yeonsung.ac.kr",
        "eclass.yeonsung.ac.kr",

    ]
