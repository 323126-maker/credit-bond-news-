import html
import json
import os
import time

DATA_FILE = "data.json"
WATCHLIST_FILE = "watchlist.json"
OUTPUT_FILE = "index.html"

CATEGORY_ORDER = [
    "watchlist",
    "credit_issue",
    "perpetual",
    "liquidity",
    "policy",
    "politics",
    "global_bond",
]

CATEGORY_META = {
    "watchlist": {"label": "Credit Watchlist (보유종목)", "color": "#2f6fed", "full_width": True},
    "credit_issue": {"label": "크레딧 이슈", "color": "#d1553d"},
    "perpetual": {"label": "신종자본증권 · 콜옵션 미행사", "color": "#c2790f"},
    "liquidity": {"label": "크레딧 경색", "color": "#c93f3f"},
    "policy": {"label": "채권정책 · 추경", "color": "#1a7f4b"},
    "politics": {"label": "정책 발언 (대통령실 등)", "color": "#7a56c9"},
    "global_bond": {"label": "글로벌 채권이슈", "color": "#0f8f85"},
}

TAG_COLORS = {
    "Fed": "#4a8c1c",
    "JGB": "#c23e72",
}

REFRESH_SECONDS = 600  # 워크플로 cron 주기와 맞춰두면 좋음 (10분)


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def relative_time(first_seen) -> str:
    if not first_seen:
        return ""
    try:
        delta = time.time() - float(first_seen)
    except (TypeError, ValueError):
        return ""
    if delta < 0:
        delta = 0
    minutes = int(delta // 60)
    if minutes < 1:
        return "방금"
    if minutes < 60:
        return f"{minutes}분 전"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}시간 전"
    days = hours // 24
    return f"{days}일 전"


def render_items(items):
    if not items:
        return '<p class="empty">최근 24시간 내 새 기사가 없습니다.</p>'

    rows = []
    for it in items:
        headline = html.escape(it.get("headline", ""))
        summary = html.escape(it.get("summary", ""))
        source = html.escape(it.get("source", ""))
        link = html.escape(it.get("link", "#"))
        published = html.escape(it.get("published", ""))
        ago = relative_time(it.get("first_seen"))
        tag = it.get("tag")
        title_attr = html.escape(f"{it.get('headline','')} — {it.get('summary','')}")

        tag_html = ""
        if tag:
            color = TAG_COLORS.get(tag, "#8a8fa3")
            tag_html = f'<span class="tag" style="background:{color}1a;color:{color}">{html.escape(tag)}</span>'

        new_badge = '<span class="new-badge">NEW</span>' if ago in ("방금", "1분 전") else ""

        rows.append(
            f"""<div class="item" title="{title_attr}">
  <span class="time">{published}<em>{ago}</em></span>
  {tag_html}{new_badge}
  <a class="headline" href="{link}" target="_blank" rel="noopener">{headline}</a>
  <span class="summary">{summary}</span>
  <span class="source">{source}</span>
</div>"""
        )

    return f'<div class="item-list">{"".join(rows)}</div>'


def main():
    data = load_json(DATA_FILE, {"categories": {}, "updated_at": ""})
    watchlist = load_json(WATCHLIST_FILE, [])
    categories = data.get("categories", {})
    updated_at = html.escape(data.get("updated_at") or "-")

    total_count = sum(len(v) for v in categories.values())

    chips = []
    cards = []

    for key in CATEGORY_ORDER:
        meta = CATEGORY_META[key]
        color = meta["color"]
        label = meta["label"]
        full_width = meta.get("full_width", False)

        if key == "watchlist" and not watchlist:
            body = '<p class="empty">watchlist.json에 종목명을 추가하면 여기에 표시됩니다.</p>'
            count = 0
        else:
            items = categories.get(key, [])
            body = render_items(items)
            count = len(items)

        chips.append(
            f'<div class="chip"><span class="dot" style="background:{color}"></span>{label} <b>{count}</b></div>'
        )

        card_class = "card full" if full_width else "card"
        cards.append(
            f"""<section class="{card_class}" style="border-top-color:{color}">
  <div class="card-head">
    <h2>{label}</h2>
    <span class="count" style="background:{color}1a;color:{color}">{count}</span>
  </div>
  {body}
</section>"""
        )

    page = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="refresh" content="{REFRESH_SECONDS}">
<title>Credit & Bond News</title>
<link rel="preconnect" href="https://cdn.jsdelivr.net">
<link rel="stylesheet" as="style" crossorigin
  href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css" />
<style>
  :root {{
    --bg: #f4f6f5;
    --panel: #ffffff;
    --text: #16201c;
    --muted: #6b746f;
    --accent: #1a7f4b;
    --accent-bg: #e7f5ec;
    --border: #e2e6e3;
    --shadow: 0 1px 2px rgba(22,32,28,0.04), 0 4px 12px rgba(22,32,28,0.05);
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    padding: 24px 32px 48px;
    background: var(--bg);
    color: var(--text);
    font-family: 'Pretendard', -apple-system, "Segoe UI", sans-serif;
    font-size: 13px;
    line-height: 1.5;
    overflow-x: hidden;
  }}
  .topbar {{
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    margin-bottom: 2px;
  }}
  .brand {{ display: flex; align-items: baseline; gap: 8px; }}
  h1 {{ font-size: 20px; margin: 0; font-weight: 700; letter-spacing: -0.2px; }}
  .tagline {{ font-size: 12px; color: var(--muted); }}
  .updated {{ color: var(--muted); font-size: 12px; white-space: nowrap; }}
  .updated b {{ color: var(--accent); font-weight: 600; }}
  .chips {{
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin: 14px 0 18px;
  }}
  .chip {{
    display: flex;
    align-items: center;
    gap: 6px;
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 999px;
    padding: 5px 12px;
    font-size: 11.5px;
    color: var(--muted);
    box-shadow: var(--shadow);
  }}
  .chip b {{ color: var(--text); font-weight: 700; }}
  .dot {{ width: 7px; height: 7px; border-radius: 50%; display: inline-block; }}
  .grid {{
    display: flex;
    flex-wrap: wrap;
    align-items: flex-start;
    gap: 14px;
  }}
  @media (max-width: 760px) {{
    .card {{ width: 100% !important; resize: none !important; }}
  }}
  .card {{
    background: var(--panel);
    border: 1px solid var(--border);
    border-top: 3px solid;
    border-radius: 12px;
    padding: 12px 16px 8px;
    flex: 0 0 auto;
    width: calc(50% - 7px);   /* 기본 폭. 카드 우측 모서리를 가로로 드래그하면 폭 조절 가능 */
    min-width: 260px;
    max-width: 100%;
    overflow: hidden;
    resize: horizontal;
    box-shadow: var(--shadow);
    transition: box-shadow 0.15s ease;
  }}
  .card.full {{ width: 100%; resize: none; }}
  .card-head {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 6px;
  }}
  .card-head h2 {{ font-size: 13.5px; margin: 0; font-weight: 700; }}
  .count {{
    font-size: 10.5px;
    font-weight: 700;
    padding: 2px 8px;
    border-radius: 999px;
  }}
  .item-list {{
    display: flex;
    flex-direction: column;
    height: 420px;      /* 기본 높이. 우측 하단 점선 부분을 드래그해서 조절 가능 */
    min-height: 80px;
    overflow: auto;
    resize: vertical;
    border-bottom: 2px dashed var(--border);
    padding-bottom: 10px;
  }}
  .item {{
    display: flex;
    align-items: baseline;
    flex-wrap: wrap;
    gap: 4px 8px;
    padding: 7px 4px;
    border-bottom: 1px solid var(--border);
    border-radius: 6px;
  }}
  .item:hover {{ background: var(--accent-bg); }}
  .item:last-child {{ border-bottom: none; }}
  .time {{
    flex: 0 0 auto;
    color: var(--muted);
    font-size: 11px;
    white-space: nowrap;
    width: 92px;
  }}
  .time em {{
    display: block;
    font-style: normal;
    font-size: 10px;
    color: var(--accent);
  }}
  .tag {{
    flex: 0 0 auto;
    font-size: 10px;
    font-weight: 700;
    padding: 1px 6px;
    border-radius: 999px;
    white-space: nowrap;
  }}
  .new-badge {{
    flex: 0 0 auto;
    font-size: 9.5px;
    font-weight: 700;
    color: #fff;
    background: var(--accent);
    padding: 1px 6px;
    border-radius: 999px;
    letter-spacing: 0.3px;
  }}
  .headline {{
    flex: 0 1 auto;
    max-width: 100%;
    color: var(--text);
    text-decoration: none;
    font-weight: 600;
    font-size: 12.5px;
    white-space: normal;
    overflow-wrap: anywhere;
  }}
  .headline:hover {{ color: var(--accent); text-decoration: underline; }}
  .summary {{
    flex: 0 1 auto;
    max-width: 45%;
    min-width: 0;
    color: var(--muted);
    font-size: 12px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    padding-top: 1px;
  }}
  .source {{
    flex: 0 0 auto;
    max-width: 90px;
    color: var(--muted);
    font-size: 11px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .source::before {{ content: "· "; }}
  .empty {{ color: var(--muted); font-size: 12px; margin: 4px 0 8px; }}
</style>
</head>
<body>
<div class="topbar">
  <div class="brand">
    <h1>Credit &amp; Bond News</h1>
    <span class="tagline">채권·크레딧 뉴스 대시보드 · 총 {total_count}건</span>
  </div>
  <span class="updated">마지막 업데이트 <b>{updated_at}</b></span>
</div>
<div class="chips">
{''.join(chips)}
</div>
<div class="grid">
{''.join(cards)}
</div>
</body>
</html>
"""

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(page)


if __name__ == "__main__":
    main()
