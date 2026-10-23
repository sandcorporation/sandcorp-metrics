"""봇 User-Agent 판정 목록. 대소문자를 가리지 않고 UA 안 어디든 들어 있으면 봇이다.

목록은 여기 한 곳에서만 고친다(`services.visitors.is_bot`이 쓴다).
"""

BOT_PATTERNS: tuple[str, ...] = (
    r"bot",
    r"crawl",
    r"spider",
    r"slurp",
    r"headless",
    r"lighthouse",
    r"preview",
    r"fetch",
    r"monitor",
    r"python-requests",
    r"python-urllib",
    r"aiohttp",
    r"httpx",
    r"go-http-client",
    r"java/",
    r"okhttp",
    r"axios",
    r"node-fetch",
    r"curl",
    r"wget",
    r"phantomjs",
    r"selenium",
    r"puppeteer",
    r"playwright",
    r"scrapy",
    r"facebookexternalhit",
    r"embedly",
    r"pingdom",
    r"uptime",
    r"archiver",
)
