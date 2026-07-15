import html
import json
import os
import time

DATA_FILE = "data.json"
WATCHLIST_FILE = "watchlist.json"
OUTPUT_FILE = "index.html"

CATEGORY_ORDER = [
    "credit_issue",
    "perpetual",
    "policy",
    "politics",
    "global_bond",
]

CATEGORY_META = {
    # watchlist는 더 이상 이 그리드에 카드로 안 나오고, 오른쪽 사이드바에 별도로 표시됨.
    # 여기 남겨둔 건 칩(chip) 색상/라벨을 재사용하기 위함.
    "watchlist": {"label": "Credit Watchlist (보유종목)", "color": "#2f6fed"},
    "credit_issue": {"label": "크레딧 이슈", "color": "#d1553d"},
    "perpetual": {"label": "신종자본증권", "color": "#c2790f"},
    "policy": {"label": "채권정책 · 추경", "color": "#1a7f4b"},
    "politics": {"label": "정책 발언 (대통령실 등)", "color": "#7a56c9"},
    "global_bond": {"label": "글로벌 채권이슈", "color": "#0f8f85", "full_width": True},
}

TAG_COLORS = {
    "Fed": "#4a8c1c",
    "JGB": "#c23e72",
    "Global": "#3f7ecf",
}

YIELD_UP_COLOR = "#d1553d"     # 금리 상승(전일比) 색
YIELD_DOWN_COLOR = "#2f6fed"   # 금리 하락(전일比) 색
YIELD_FLAT_COLOR = "#6b746f"

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


def sparkline_svg(values, width=100, height=30, color="#1a7f4b") -> str:
    """숫자 리스트를 아주 작은 꺾은선(스파크라인) SVG로 그려줌. 외부 차트 라이브러리 없이
    빌드 시점에 파이썬에서 직접 그림 (TradingView 위젯이 국고채 심볼을 임베드 못 해서 대체)."""
    if not values or len(values) < 2:
        return ""
    lo, hi = min(values), max(values)
    rng = (hi - lo) or 1
    step = width / (len(values) - 1)
    pts = []
    for i, v in enumerate(values):
        x = i * step
        y = height - ((v - lo) / rng) * (height - 4) - 2
        pts.append(f"{x:.1f},{y:.1f}")
    points = " ".join(pts)
    return (
        f'<svg class="spark" viewBox="0 0 {width} {height}" preserveAspectRatio="none">'
        f'<polyline points="{points}" fill="none" stroke="{color}" '
        f'stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/></svg>'
    )


def render_yield_panel(yields) -> str:
    """국고채 만기별(3/5/10/20/30년) 금리를 한 화면에 나란히(좌르륵) 보여주는 패널.
    ECOS_API_KEY가 없거나 조회 실패로 yields가 비어있으면 안내 문구만 표시."""
    if not yields:
        return '<p class="empty">ECOS_API_KEY가 설정되지 않았거나 국고채 금리를 아직 못 가져왔습니다. (설정 가이드 참고)</p>'

    cells = []
    for y in yields:
        chg = y.get("chg_bp", 0)
        if chg > 0:
            color = YIELD_UP_COLOR
            sign = "+"
        elif chg < 0:
            color = YIELD_DOWN_COLOR
            sign = ""
        else:
            color = YIELD_FLAT_COLOR
            sign = ""
        spark = sparkline_svg(y.get("series", []), color=color)
        cells.append(
            f"""<div class="yield-cell">
  <span class="yc-label">국고채 {html.escape(y.get('label',''))}</span>
  <span class="yc-value">{y.get('value', 0):.3f}%</span>
  <span class="yc-chg" style="color:{color}">{sign}{chg:.1f}bp</span>
  {spark}
</div>"""
        )
    return f'<div class="yield-grid">{"".join(cells)}</div>'


def normalize_watchlist(raw) -> list:
    """watchlist.json 항목은 문자열("삼성카드")도, 객체({"name":"삼성카드","rating":"AA+"})도 지원.
    rating은 자동 수집이 아니라 직접 적어 넣는 값 (무료 공개 API가 없어서).
    민평금리는 매일 바뀌어서 수동 관리가 비현실적이라 제외 (등급은 자주 안 바뀌어서 수동 관리 가능)."""
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


WATCHLIST_MAX_PER_COMPANY = 4  # 종목당 사이드바에 보여줄 최근 헤드라인 개수 (넘으면 스크롤)


def render_watchlist_sidebar(watchlist_raw, watchlist_items) -> str:
    """토스 앱 우측 '관심' 패널처럼, 보유 종목별로 블록을 나눠서 종목명(+등급) 아래에
    최근 헤드라인을 여러 개(WATCHLIST_MAX_PER_COMPANY개, 넘으면 스크롤) 보여줌.
    watchlist_items는 이미 main()에서 최신순 정렬돼 있으므로 그 순서 그대로 최신순 유지."""
    watchlist = normalize_watchlist(watchlist_raw)
    if not watchlist:
        return '<p class="empty">watchlist.json에 종목명을 추가하면 여기에 표시됩니다.</p>'

    by_company = {}
    for it in watchlist_items:
        name = it.get("tag")
        if not name:
            continue
        by_company.setdefault(name, []).append(it)

    blocks = []
    for w in watchlist:
        name = w["name"]
        rating = w.get("rating") or ""
        meta_html = f' <span class="wl-meta">{html.escape(rating)}</span>' if rating else ""
        items = by_company.get(name, [])[:WATCHLIST_MAX_PER_COMPANY]

        if items:
            rows = []
            for it in items:
                headline = html.escape(it.get("headline", ""))
                link = html.escape(it.get("link", "#"))
                ago = relative_time(it.get("first_seen"))
                rows.append(
                    f"""<a class="wl-item" href="{link}" target="_blank" rel="noopener">
  <span class="wl-item-headline">{headline}</span>
  <span class="wl-item-time">{ago}</span>
</a>"""
                )
            body = f'<div class="wl-item-list">{"".join(rows)}</div>'
        else:
            body = '<p class="wl-empty-text">최근 소식 없음</p>'

        blocks.append(
            f"""<div class="wl-block">
  <div class="wl-block-head">{html.escape(name)}{meta_html}</div>
  {body}
</div>"""
        )
    return "".join(blocks)


def main():
    data = load_json(DATA_FILE, {"categories": {}, "updated_at": ""})
    watchlist = load_json(WATCHLIST_FILE, [])
    categories = data.get("categories", {})
    updated_at = html.escape(data.get("updated_at") or "-")

    total_count = sum(len(v) for v in categories.values())
    yield_panel_html = render_yield_panel(data.get("yields", []))

    watchlist_items = categories.get("watchlist", [])
    watchlist_sidebar_html = render_watchlist_sidebar(watchlist, watchlist_items)
    wl_color = CATEGORY_META["watchlist"]["color"]
    wl_label = CATEGORY_META["watchlist"]["label"]
    watchlist_count = len(watchlist_items)

    chips = [
        f'<div class="chip"><span class="dot" style="background:{wl_color}"></span>{wl_label} <b>{watchlist_count}</b></div>'
    ]
    cards = []

    for key in CATEGORY_ORDER:
        meta = CATEGORY_META[key]
        color = meta["color"]
        label = meta["label"]
        full_width = meta.get("full_width", False)

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
    position: sticky;
    top: 0;
    z-index: 20;
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    margin: -24px -32px 14px;
    padding: 16px 32px 10px;
    background: rgba(244,246,245,0.88);
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
    border-bottom: 1px solid var(--border);
  }}
  .brand {{ display: flex; align-items: baseline; gap: 8px; }}
  h1 {{ font-size: 20px; margin: 0; font-weight: 700; letter-spacing: -0.2px; }}
  .tagline {{ font-size: 12px; color: var(--muted); }}
  .updated {{ color: var(--muted); font-size: 12px; white-space: nowrap; }}
  .updated b {{ color: var(--accent); font-weight: 600; }}
  .yield-panel {{
    background: var(--panel);
    border-radius: 12px;
    box-shadow: var(--shadow);
    padding: 10px 14px 2px;
    margin-bottom: 16px;
  }}
  .yield-panel-head {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 4px;
  }}
  .yield-panel-head h2 {{ font-size: 12.5px; margin: 0; font-weight: 700; color: var(--muted); }}
  .yield-grid {{
    display: flex;
    flex-wrap: wrap;
    gap: 0;
  }}
  .yield-cell {{
    flex: 1 1 0;
    min-width: 110px;
    display: flex;
    flex-direction: column;
    padding: 6px 12px 10px;
    border-right: 1px solid var(--border);
  }}
  .yield-cell:last-child {{ border-right: none; }}
  .yc-label {{ font-size: 11px; color: var(--muted); }}
  .yc-value {{ font-size: 17px; font-weight: 700; margin-top: 2px; }}
  .yc-chg {{ font-size: 11px; font-weight: 700; margin-top: 1px; }}
  .spark {{ width: 100%; height: 26px; margin-top: 4px; }}
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
    transition: box-shadow 0.15s ease, transform 0.15s ease;
  }}
  .card:hover {{
    box-shadow: 0 2px 4px rgba(22,32,28,0.06), 0 10px 24px rgba(22,32,28,0.09);
    transform: translateY(-1px);
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
    max-width: 110px;
    margin-left: auto;
    color: var(--muted);
    font-size: 11px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .source::before {{ content: "· "; }}
  .empty {{ color: var(--muted); font-size: 12px; margin: 4px 0 8px; }}
  .layout {{
    display: flex;
    align-items: flex-start;
    gap: 16px;
  }}
  .main {{ flex: 1; min-width: 0; }}
  .sidebar {{
    flex: 0 0 300px;
    position: sticky;
    top: 72px;
    background: var(--panel);
    border-radius: 12px;
    box-shadow: var(--shadow);
    padding: 12px 14px;
    max-height: calc(100vh - 96px);
    overflow: auto;
  }}
  @media (max-width: 900px) {{
    .layout {{ flex-direction: column; }}
    .sidebar {{ position: static; width: 100%; flex: none; max-height: none; }}
  }}
  .sidebar-head {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 6px;
  }}
  .sidebar-head h2 {{ font-size: 13.5px; margin: 0; font-weight: 700; }}
  .wl-block {{
    padding: 8px 2px;
    border-bottom: 1px solid var(--border);
  }}
  .wl-block:last-child {{ border-bottom: none; }}
  .wl-block-head {{
    font-size: 12px;
    font-weight: 700;
    color: var(--text);
    margin-bottom: 4px;
  }}
  .wl-meta {{ font-size: 10.5px; font-weight: 600; color: var(--accent); margin-left: 4px; }}
  .wl-item-list {{
    display: flex;
    flex-direction: column;
    max-height: 116px;   /* 대략 4줄. 더 있으면 스크롤 */
    overflow-y: auto;
  }}
  .wl-item {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 8px;
    padding: 4px 2px;
    border-radius: 6px;
    text-decoration: none;
    color: inherit;
  }}
  .wl-item:hover {{ background: var(--accent-bg); }}
  .wl-item-headline {{
    font-size: 12px;
    color: var(--text);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
    flex: 1 1 auto;
  }}
  .wl-item-time {{ font-size: 10px; color: var(--muted); flex: 0 0 auto; }}
  .wl-empty-text {{ color: var(--muted); font-size: 12px; margin: 0; }}
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
<div class="layout">
  <div class="main">
    <div class="yield-panel">
      <div class="yield-panel-head"><h2>국고채 금리 (KTB) · 구간별 · 당일 변동</h2></div>
      {yield_panel_html}
    </div>
    <div class="chips">
    {''.join(chips)}
    </div>
    <div class="grid">
    {''.join(cards)}
    </div>
  </div>
  <aside class="sidebar">
    <div class="sidebar-head">
      <h2>{wl_label}</h2>
      <span class="count" style="background:{wl_color}1a;color:{wl_color}">{watchlist_count}</span>
    </div>
    {watchlist_sidebar_html}
  </aside>
</div>
</body>
</html>
"""

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(page)


if __name__ == "__main__":
    main()
