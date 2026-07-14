import html
import json
import os

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
    "watchlist": {"label": "Credit Watchlist (보유종목)", "color": "#5b8dee", "full_width": True},
    "credit_issue": {"label": "크레딧 이슈", "color": "#e0664f"},
    "perpetual": {"label": "신종자본증권 · 콜옵션 미행사", "color": "#f0a84c"},
    "liquidity": {"label": "크레딧 경색", "color": "#e05a5a"},
    "policy": {"label": "채권정책 · 추경", "color": "#3fc48a"},
    "politics": {"label": "정책 발언 (대통령실 등)", "color": "#9b7de8"},
    "global_bond": {"label": "글로벌 채권이슈", "color": "#4fb8b0"},
}

TAG_COLORS = {
    "Fed": "#639922",
    "JGB": "#d4537e",
}


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


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
        tag = it.get("tag")
        title_attr = html.escape(f"{it.get('headline','')} — {it.get('summary','')}")

        tag_html = ""
        if tag:
            color = TAG_COLORS.get(tag, "#8a8fa3")
            tag_html = f'<span class="tag" style="background:{color}22;color:{color}">{html.escape(tag)}</span>'

        rows.append(
            f"""<div class="item" title="{title_attr}">
  <span class="time">{published}</span>
  {tag_html}
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
    <span class="count" style="background:{color}22;color:{color}">{count}</span>
  </div>
  {body}
</section>"""
        )

    page = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Credit & Bond News</title>
<style>
  :root {{
    --bg: #0d0f18;
    --panel: #151827;
    --text: #e7e9f2;
    --muted: #8a8fa3;
    --accent: #5b8dee;
    --border: #262b3d;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    padding: 20px 28px 40px;
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, "Pretendard", "Segoe UI", sans-serif;
    font-size: 13px;
    line-height: 1.4;
    overflow-x: hidden;
  }}
  .topbar {{
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    margin-bottom: 4px;
  }}
  h1 {{ font-size: 19px; margin: 0; font-weight: 600; }}
  .updated {{ color: var(--muted); font-size: 12px; }}
  .chips {{
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin: 12px 0 16px;
  }}
  .chip {{
    display: flex;
    align-items: center;
    gap: 6px;
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 999px;
    padding: 4px 10px;
    font-size: 11px;
    color: var(--muted);
  }}
  .chip b {{ color: var(--text); font-weight: 600; }}
  .dot {{ width: 7px; height: 7px; border-radius: 50%; display: inline-block; }}
  .grid {{
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 12px;
  }}
  @media (max-width: 760px) {{
    .grid {{ grid-template-columns: 1fr; }}
  }}
  .card {{
    background: var(--panel);
    border: 1px solid var(--border);
    border-top: 3px solid;
    border-radius: 10px;
    padding: 10px 14px 6px;
  }}
  .card.full {{ grid-column: 1 / -1; }}
  .card-head {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 4px;
  }}
  .card-head h2 {{ font-size: 13px; margin: 0; font-weight: 600; }}
  .count {{
    font-size: 10px;
    font-weight: 600;
    padding: 1px 7px;
    border-radius: 999px;
  }}
  .item-list {{
    display: flex;
    flex-direction: column;
    height: 420px;      /* 기본 높이. 사용자가 우측 하단을 드래그해서 직접 조절 가능 */
    min-height: 80px;
    overflow: auto;
    resize: vertical;   /* 카드 우측 하단 모서리를 드래그하면 높이 조절됨 */
  }}
  .item {{
    display: flex;
    align-items: baseline;
    flex-wrap: wrap;
    gap: 4px 8px;
    padding: 6px 0;
    border-bottom: 1px solid var(--border);
  }}
  .item:last-child {{ border-bottom: none; }}
  .time {{
    flex: 0 0 auto;
    color: var(--muted);
    font-size: 11px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    width: 76px;
  }}
  .tag {{
    flex: 0 0 auto;
    font-size: 10px;
    font-weight: 600;
    padding: 1px 6px;
    border-radius: 999px;
    white-space: nowrap;
  }}
  .headline {{
    flex: 0 1 auto;
    max-width: 100%;
    color: var(--text);
    text-decoration: none;
    font-weight: 500;
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
    margin-left: auto;
    color: var(--muted);
    font-size: 11px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .empty {{ color: var(--muted); font-size: 12px; margin: 4px 0 8px; }}
</style>
</head>
<body>
<div class="topbar">
  <h1>Credit &amp; Bond News</h1>
  <span class="updated">마지막 업데이트 {updated_at}</span>
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
