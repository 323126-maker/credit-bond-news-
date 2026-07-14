import json
import os
import time
from urllib.parse import quote

import feedparser
import requests

DATA_FILE = "data.json"
WATCHLIST_FILE = "watchlist.json"
MAX_AGE_DAYS = 10
MAX_PER_CATEGORY = 40

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"

# 카테고리 정의. "keywords"만 있으면 단순 카테고리, "subgroups"가 있으면
# 하위 태그별로 나눠 검색하고 각 기사에 태그를 붙인다 (예: 글로벌 채권이슈 안에서 Fed/JGB 구분).
CATEGORIES = {
    "watchlist": {
        "label": "Credit Watchlist (보유종목)",
        "keywords": [],  # watchlist.json 종목명으로 동적 생성
    },
    "credit_issue": {
        "label": "크레딧 이슈",
        "keywords": [
            "회사채 신용등급 강등",
            "신용등급 전망 조정",
            "워크아웃 부도",
        ],
    },
    "perpetual": {
        "label": "신종자본증권 · 콜옵션 미행사",
        "keywords": [
            "신종자본증권 콜옵션",
            "코코본드 콜옵션 미행사",
            "영구채 콜옵션 스킵",
        ],
    },
    "liquidity": {
        "label": "크레딧 경색",
        "keywords": [
            "회사채 시장 경색",
            "자금경색 유동성 위기",
            "단기자금시장 경색",
        ],
    },
    "policy": {
        "label": "채권정책 · 추경",
        "keywords": [
            "한국은행 기준금리 채권시장",
            "국채 발행계획 기획재정부",
            "금융당국 회사채 시장 안정화",
            "추경 국채 발행",
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
        },
    },
}


def is_korean(text: str) -> bool:
    return any("가" <= ch <= "힣" for ch in text)


def build_rss_url(query: str) -> str:
    korean = is_korean(query)
    hl = "ko" if korean else "en-US"
    gl = "KR" if korean else "US"
    ceid = f"{gl}:{'ko' if korean else 'en'}"
    q = quote(f"{query} when:1d")
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
    """Claude API로 1~2문장 한국어 요약. 키가 없으면 원문 스니펫을 그대로 사용."""
    if not ANTHROPIC_API_KEY:
        return snippet[:120] if snippet else title

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


def fetch_for_keyword(query: str) -> list:
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
                "title": title,
                "snippet": snippet,
                "source": source,
                "published": published,
            }
        )
    return items


def collect_for_category(cfg: dict, watchlist: list) -> list:
    """(item, tag) 튜플 리스트를 반환. tag는 subgroup 이름 또는 None."""
    results = []

    if "subgroups" in cfg:
        for tag, keywords in cfg["subgroups"].items():
            for query in keywords:
                for item in fetch_for_keyword(query):
                    results.append((item, tag))
        return results

    keywords = list(cfg.get("keywords", []))
    if cfg is CATEGORIES["watchlist"]:
        for name in watchlist:
            name = name.strip()
            if not name:
                continue
            keywords.append(f"{name} 회사채")
            keywords.append(f"{name} 신용등급")

    for query in keywords:
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

        raw_pairs = collect_for_category(cfg, watchlist)

        new_items = []
        for it, tag in raw_pairs:
            if it["link"] in existing_links:
                continue
            existing_links.add(it["link"])
            summary = summarize(it["title"], it["snippet"])
            new_items.append(
                {
                    "link": it["link"],
                    "headline": it["title"],
                    "summary": summary,
                    "source": it["source"],
                    "published": it["published"],
                    "tag": tag,
                    "first_seen": now,
                }
            )

        merged = new_items + existing
        cutoff = now - MAX_AGE_DAYS * 86400
        merged = [it for it in merged if it.get("first_seen", now) >= cutoff]
        merged = merged[:MAX_PER_CATEGORY]

        data["categories"][cat_key] = merged

    data["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
    save_json(DATA_FILE, data)


if __name__ == "__main__":
    main()
