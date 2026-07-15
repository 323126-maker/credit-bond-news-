import difflib
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import feedparser
import requests

DATA_FILE = "data.json"
WATCHLIST_FILE = "watchlist.json"
MAX_AGE_DAYS = 10
MAX_PER_CATEGORY = 40
TITLE_SIMILARITY_THRESHOLD = 0.72  # 이 이상 비슷하면 같은 기사로 간주해 중복 제거
WHEN_DAYS = 3  # 검색 시 몇 일치 뉴스까지 조회할지. 니치한 카테고리는 하루치(1d)로는 결과가 거의 안 나옴

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"

NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET")

ECOS_API_KEY = os.environ.get("ECOS_API_KEY")
ECOS_STAT_CODE = "817Y002"  # 한국은행 ECOS "시장금리(일별)" 통계표. 국고채 만기별 수익률이 여기 포함됨
KTB_MATURITIES = ["3년", "5년", "10년", "20년", "30년"]  # 상단 금리 패널에 보여줄 만기 구간

# 카테고리 정의. "keywords"만 있으면 단순 카테고리, "subgroups"가 있으면
# 하위 태그별로 나눠 검색하고 각 기사에 태그를 붙인다 (예: 글로벌 채권이슈 안에서 Fed/JGB/Global 구분).
CATEGORIES = {
    "watchlist": {
        "label": "Credit Watchlist (보유종목)",
        "keywords": [],  # watchlist.json 종목명으로 동적 생성
    },
    "credit_issue": {
        "label": "크레딧·채권",
        "keywords": [
            "크레딧 스프레드",
            "크레딧 채권",
            "채권 마감"
            "채권 장전"
            "회사채 신용등급 강등",
            "신용등급 전망 조정",
            "워크아웃 부도",
            "회사채 시장",
            "자금경색 유동성 위기",
            "단기자금시장 경색",
        ],
    },
    "perpetual": {
        "label": "신종자본증권",
        "keywords": [
            "신종자본증권 콜옵션",
            "신종자본증권",
            "코코본드 콜옵션 미행사",
            "영구채 콜옵션 스킵",
            "AT1 채권",
            "코코본드",
            "후순위채",
            "하이브리드채권",
        ],
    },
    "policy": {
        "label": "채권정책 · 추경",
        "keywords": [
            "한국은행 기준금리 채권시장",
            "국채 발행계획 기획재정부",
            "금융당국 회사채 시장 안정화",
            "추경 국채 발행",
            "채권 장전 site:newskom.co.kr",  # 뉴스콤의 [채권-장전] 시황 브리핑
            "채권 마감 site:newskom.co.kr",  # 뉴스콤의 [채권-마감] 시황 브리핑
        ],
    },
    "politics": {
        "label": "정책 발언 (대통령실 등)",
        "keywords": [
            "이재명 국채 발언",
            "이재명 재정 발언",
            "대통령실 국채 발언",
        ],
    },
    "global_bond": {
        "label": "글로벌 채권이슈",
        "subgroups": {
            "Fed": [
                "Fed chair Kevin Warsh",
                "연준 의장 후보 케빈 워시",
                "Federal Reserve policy bond market",
            ],
            "JGB": [
                "Japan government bond yield",
                "일본 국채 금리",
                "일본은행 통화정책",
            ],
            "Global": [
                "global bond market credit spread",
                "corporate bond market outlook",
                "high yield bond default risk",
                "emerging market bond selloff",
            ],
        },
    },
}


def is_korean(text: str) -> bool:
    return any("가" <= ch <= "힣" for ch in text)


def format_published(raw: str) -> str:
    """RSS의 RFC-2822 날짜 문자열을 'MM/DD HH:MM' (KST) 형태로 짧게 변환.
    파싱 실패 시 원본을 20자로 잘라 반환 (화면에서 헤드라인과 안 겹치도록)."""
    if not raw:
        return ""
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        kst = dt.astimezone(timezone.utc) + timedelta(hours=9)
        return kst.strftime("%m/%d %H:%M")
    except Exception:
        return raw[:20]


def published_epoch(raw: str) -> float:
    """정렬 전용: RSS 원본 날짜 문자열을 epoch(초)로 변환. 최신순 정렬에 사용.
    파싱 실패 시 0을 반환해 맨 뒤로 밀려나게 한다."""
    if not raw:
        return 0
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return 0


def clean_headline(title: str, source: str) -> str:
    """구글/네이버 뉴스 제목 끝에 자동으로 붙는 ' - 출처명'을 제거.
    화면에서 출처를 이미 따로 보여주므로 중복 표시를 막기 위함."""
    if not title:
        return title
    title = title.strip()
    source = (source or "").strip()
    if source:
        pattern = r"[\s ]*[-–—][\s ]*" + re.escape(source) + r"[\s ]*$"
        title = re.sub(pattern, "", title, flags=re.IGNORECASE)
    return title.strip()


def normalize_title(title: str) -> str:
    """제목 유사도 비교용: 공백/기호 제거하고 소문자화."""
    return re.sub(r"[^\w가-힣]+", "", (title or "").lower())


def is_similar_title(a: str, b: str) -> bool:
    """서로 다른 소스(구글/네이버)가 같은 기사를 다른 제목으로 줄 때
    중복으로 판단하기 위한 유사도 체크."""
    if not a or not b:
        return False
    return difflib.SequenceMatcher(None, a, b).ratio() >= TITLE_SIMILARITY_THRESHOLD


def build_rss_url(query: str) -> str:
    korean = is_korean(query)
    hl = "ko" if korean else "en-US"
    gl = "KR" if korean else "US"
    ceid = f"{gl}:{'ko' if korean else 'en'}"
    q = quote(f"{query} when:{WHEN_DAYS}d")
    return f"https://news.google.com/rss/search?q={q}&hl={hl}&gl={gl}&ceid={ceid}"


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def summarize(title: str, snippet: str) -> str:
    """Claude API로 1~2문장 한국어 요약 (해외 영문 기사도 한국어로 요약됨).
    Google News RSS의 snippet 필드는 실제 기사 요약이 아니라
    '<a href=...>제목</a> 출처' 형태의 HTML 링크뿐이라, API 키가 없으면
    의미 없는 텍스트를 억지로 보여주는 대신 요약을 비워둔다."""
    if not ANTHROPIC_API_KEY:
        return ""

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": ANTHROPIC_MODEL,
                "max_tokens": 150,
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "다음 기사 제목과 스니펫을 바탕으로, 채권/크레딧 투자자가 "
                            "빠르게 이해할 수 있도록 한국어 1~2문장으로 핵심만 요약해줘. "
                            "원문이 영어여도 반드시 한국어로 요약해줘. "
                            "번역체 쓰지 말고 자연스럽게. 불필요한 서두 없이 요약문만 출력.\n\n"
                            f"제목: {title}\n스니펫: {snippet}"
                        ),
                    }
                ],
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["content"][0]["text"].strip()
    except Exception:
        return snippet[:120] if snippet else title


def fetch_google(query: str) -> list:
    url = build_rss_url(query)
    try:
        feed = feedparser.parse(url)
    except Exception:
        return []
    items = []
    for entry in feed.entries[:10]:
        link = getattr(entry, "link", None)
        title = getattr(entry, "title", "")
        snippet = getattr(entry, "summary", "")
        source = ""
        if getattr(entry, "source", None):
            source = getattr(entry.source, "title", "")
        published = getattr(entry, "published", "")
        if not link or not title:
            continue
        items.append(
            {
                "link": link,
                "title": clean_headline(title, source),
                "snippet": snippet,
                "source": source,
                "published": published,
            }
        )
    return items


def fetch_naver(query: str) -> list:
    """네이버 뉴스 검색 API. NAVER_CLIENT_ID/SECRET이 없으면 그냥 빈 리스트를
    돌려줘서 기능 자체가 꺼진 것처럼 동작 (기존 구글 전용 흐름 그대로 유지)."""
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        return []
    if not is_korean(query):
        return []  # 네이버는 국내 언론 위주라 한글 검색어에만 사용

    try:
        resp = requests.get(
            "https://openapi.naver.com/v1/search/news.json",
            headers={
                "X-Naver-Client-Id": NAVER_CLIENT_ID,
                "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
            },
            params={"query": query, "display": 10, "sort": "date"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []

    items = []
    for it in data.get("items", []):
        title = re.sub(r"<[^>]+>", "", it.get("title", ""))
        title = title.replace("&quot;", '"').replace("&amp;", "&").replace("&#39;", "'")
        link = it.get("originallink") or it.get("link") or ""
        snippet = re.sub(r"<[^>]+>", "", it.get("description", ""))
        pub_date = it.get("pubDate", "")
        if not link or not title:
            continue
        items.append(
            {
                "link": link,
                "title": title.strip(),
                "snippet": snippet,
                "source": "네이버뉴스",
                "published": pub_date,
            }
        )
    return items


def fetch_for_keyword(query: str) -> list:
    return fetch_google(query) + fetch_naver(query)


def fetch_ecos_item_codes() -> dict:
    """817Y002(시장금리 일별) 통계표 안에서 '국고채'가 들어간 항목을 만기별로 찾아
    {"3년": "통계항목코드", ...} 형태로 반환. 코드를 하드코딩하지 않고 매번 이름으로
    찾는 이유는 ECOS 항목코드가 바뀌거나 잘못 추측하면 조용히 빈 데이터만 나오기 때문."""
    if not ECOS_API_KEY:
        return {}
    url = f"https://ecos.bok.or.kr/api/StatisticItemList/{ECOS_API_KEY}/json/kr/1/1000/{ECOS_STAT_CODE}"
    try:
        resp = requests.get(url, timeout=15)
        rows = resp.json().get("StatisticItemList", {}).get("row", [])
    except Exception:
        return {}

    mapping = {}
    for row in rows:
        name = row.get("ITEM_NAME", "")
        if "국고채" not in name:
            continue
        for m in KTB_MATURITIES:
            if m in name and m not in mapping:
                mapping[m] = row.get("ITEM_CODE")
    return mapping


def fetch_ktb_yields() -> list:
    """국고채 만기별(3/5/10/20/30년) 최근 수익률과 전일 대비 변동(bp), 최근 20개 시계열을 반환.
    ECOS_API_KEY가 없거나 API 조회에 실패하면 빈 리스트를 반환 (기존 값 유지는 main()에서 처리)."""
    item_codes = fetch_ecos_item_codes()
    if not item_codes:
        return []

    end = datetime.now(timezone.utc) + timedelta(hours=9)
    start = end - timedelta(days=45)  # 주말/공휴일 감안해 넉넉히 조회
    start_s = start.strftime("%Y%m%d")
    end_s = end.strftime("%Y%m%d")

    results = []
    for maturity in KTB_MATURITIES:
        code = item_codes.get(maturity)
        if not code:
            continue
        url = (
            f"https://ecos.bok.or.kr/api/StatisticSearch/{ECOS_API_KEY}/json/kr/1/100/"
            f"{ECOS_STAT_CODE}/D/{start_s}/{end_s}/{code}"
        )
        try:
            resp = requests.get(url, timeout=15)
            rows = resp.json().get("StatisticSearch", {}).get("row", [])
        except Exception:
            continue
        if not rows:
            continue

        rows.sort(key=lambda r: r.get("TIME", ""))
        series = []
        for r in rows:
            try:
                series.append(float(r["DATA_VALUE"]))
            except (KeyError, ValueError, TypeError):
                continue
        if not series:
            continue

        latest = series[-1]
        prev = series[-2] if len(series) > 1 else latest
        chg_bp = round((latest - prev) * 100, 1)  # %p 차이를 bp(0.01%p)로 환산
        results.append(
            {
                "label": maturity,
                "value": round(latest, 3),
                "chg_bp": chg_bp,
                "series": series[-20:],
            }
        )
    return results


def normalize_watchlist(raw: list) -> list:
    """watchlist.json 항목은 문자열("삼성카드")도, 객체({"name":"삼성카드","rating":"AA+"})도 지원.
    신용등급은 자동으로 못 가져와서(무료 공개 API가 없음) 직접 적어 넣는 값이라
    문자열이면 이름만 있는 것으로 취급하고 rating은 빈 값으로 채운다.
    민평금리는 매일 바뀌어서 수동 입력이 비현실적이라 아예 제외 (등급은 자주 안 바뀌어서 수동 관리 가능)."""
    result = []
    for entry in raw:
        if isinstance(entry, str):
            name = entry.strip()
            if name:
                result.append({"name": name, "rating": ""})
        elif isinstance(entry, dict):
            name = (entry.get("name") or "").strip()
            if name:
                result.append({"name": name, "rating": entry.get("rating", "")})
    return result


def collect_for_category(cfg: dict, watchlist: list) -> list:
    """(item, tag) 튜플 리스트를 반환. tag는 subgroup 이름(글로벌 채권이슈) 또는
    보유 종목명(워치리스트) 또는 None."""
    results = []

    if "subgroups" in cfg:
        for tag, keywords in cfg["subgroups"].items():
            for query in keywords:
                for item in fetch_for_keyword(query):
                    results.append((item, tag))
        return results

    if cfg is CATEGORIES["watchlist"]:
        # 종목별로 검색해서 결과에 종목명을 태그로 붙임 -> 사이드바에서 종목별로 묶어 보여주는 데 사용
        for w in normalize_watchlist(watchlist):
            name = w["name"]
            for query in (f"{name} 회사채", f"{name} 신용등급"):
                for item in fetch_for_keyword(query):
                    results.append((item, name))
        return results

    for query in cfg.get("keywords", []):
        for item in fetch_for_keyword(query):
            results.append((item, None))

    return results


def main():
    watchlist = load_json(WATCHLIST_FILE, [])
    data = load_json(DATA_FILE, {"categories": {}, "updated_at": None})
    data.setdefault("categories", {})

    now = time.time()

    for cat_key, cfg in CATEGORIES.items():
        if cat_key == "watchlist" and not watchlist:
            continue

        existing = data["categories"].get(cat_key, [])
        existing_links = {it["link"] for it in existing}
        existing_norm_titles = [normalize_title(it.get("headline", "")) for it in existing]

        raw_pairs = collect_for_category(cfg, watchlist)

        new_items = []
        new_norm_titles = []
        for it, tag in raw_pairs:
            if it["link"] in existing_links:
                continue
            headline = clean_headline(it["title"], it["source"])
            norm = normalize_title(headline)
            if any(is_similar_title(norm, seen) for seen in existing_norm_titles + new_norm_titles):
                continue  # 이미 비슷한 제목의 기사가 있음 (다른 소스가 준 같은 기사)

            existing_links.add(it["link"])
            new_norm_titles.append(norm)

            summary = summarize(it["title"], it["snippet"])
            raw_published = it["published"]
            new_items.append(
                {
                    "link": it["link"],
                    "headline": headline,
                    "summary": summary,
                    "source": it["source"],
                    "published": format_published(raw_published),
                    "published_ts": published_epoch(raw_published),
                    "tag": tag,
                    "first_seen": now,
                }
            )

        merged = new_items + existing
        merged.sort(key=lambda it: it.get("published_ts", 0), reverse=True)  # 최신 기사가 위로
        cutoff = now - MAX_AGE_DAYS * 86400
        merged = [it for it in merged if it.get("first_seen", now) >= cutoff]
        merged = merged[:MAX_PER_CATEGORY]

        data["categories"][cat_key] = merged

    yields = fetch_ktb_yields()
    if yields:  # 조회 실패 시 기존 값을 그대로 유지 (화면이 갑자기 비지 않도록)
        data["yields"] = yields

    data["updated_at"] = (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y-%m-%d %H:%M:%S")
    save_json(DATA_FILE, data)


if __name__ == "__main__":
    main()
