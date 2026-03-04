import json
import re
import requests
from datetime import datetime, timezone

SHEET_URL = "https://docs.google.com/spreadsheets/d/1MGVNAW1nkRyMA0N05XZhgSXAr4lXudxPx4J1I4agGWo/gviz/tq?tqx=out:json"

SCORE_MAP = {"Yes": 100, "Sorta": 50, "No": 0}

def simplify_response(raw):
    if raw is None:
        return "No"
    if raw.startswith("Yes"):
        return "Yes"
    if raw.startswith("Sorta"):
        return "Sorta"
    return "No"

def fetch_data():
    resp = requests.get(SHEET_URL, timeout=30)
    resp.raise_for_status()
    text = resp.text
    match = re.search(r"setResponse\((\{.*\})\)", text, re.DOTALL)
    if not match:
        raise ValueError("Could not find JSON in response")
    data = json.loads(match.group(1))
    table = data["table"]
    cols = table["cols"]
    rows = table["rows"]

    # Find and exclude any non-topic columns (e.g. "Phone Number")
    EXCLUDED_LABELS = {"phone number"}
    phone_col = None  # column index (absolute) of phone number field
    topic_col_indices = []  # absolute column indices that are real topics
    for i in range(2, len(cols)):
        label = cols[i]["label"].strip()
        if label.lower() in EXCLUDED_LABELS:
            phone_col = i
        else:
            topic_col_indices.append(i)

    topics = [cols[i]["label"] for i in topic_col_indices]

    people = []
    for row in rows:
        cells = row.get("c", [])
        name_cell = cells[1] if len(cells) > 1 else None
        name = (name_cell.get("v") or name_cell.get("f") or "Unknown") if name_cell else "Unknown"
        ts_cell = cells[0] if cells else None
        timestamp = (ts_cell.get("f") or "") if ts_cell else ""
        # Extract phone if present
        phone = ""
        if phone_col is not None and phone_col < len(cells):
            phone_cell = cells[phone_col]
            phone = (phone_cell.get("v") or "") if phone_cell else ""
        responses = []
        for i in topic_col_indices:
            raw = cells[i].get("v") if i < len(cells) and cells[i] else None
            responses.append(simplify_response(raw))
        people.append({"name": name, "timestamp": timestamp, "responses": responses, "phone": str(phone).strip()})

    return topics, people

def compute_topic_stats(topics, people):
    stats = []
    n = len(people)
    for i, topic in enumerate(topics):
        yes = sum(1 for p in people if i < len(p["responses"]) and p["responses"][i] == "Yes")
        sorta = sum(1 for p in people if i < len(p["responses"]) and p["responses"][i] == "Sorta")
        no = sum(1 for p in people if i < len(p["responses"]) and p["responses"][i] == "No")
        score = round((yes * 100 + sorta * 50) / (n * 100) * 100, 1) if n > 0 else 0
        yes_pct = round(yes / n * 100, 1) if n > 0 else 0
        sorta_pct = round(sorta / n * 100, 1) if n > 0 else 0
        no_pct = round(no / n * 100, 1) if n > 0 else 0
        values = ([100] * yes) + ([50] * sorta) + ([0] * no)
        mean = score
        variance = sum((v - mean) ** 2 for v in values) / n if n > 0 else 0
        stats.append({
            "topic": topic,
            "score": score,
            "yes_pct": yes_pct,
            "sorta_pct": sorta_pct,
            "no_pct": no_pct,
            "variance": round(variance, 1),
            "yes": yes,
            "sorta": sorta,
            "no": no,
        })
    return stats

def compute_person_scores(topics, people):
    result = []
    n = len(topics)
    for p in people:
        r = p["responses"]
        total = sum(SCORE_MAP.get(r[i], 0) for i in range(min(len(r), n)))
        score = round(total / (n * 100) * 100, 1) if n > 0 else 0
        yes = sum(1 for x in r if x == "Yes")
        sorta = sum(1 for x in r if x == "Sorta")
        no = sum(1 for x in r if x == "No")
        result.append({
            "name": p["name"],
            "timestamp": p["timestamp"],
            "score": score,
            "yes": yes,
            "sorta": sorta,
            "no": no,
        })
    return result

def score_color_css(score):
    s = max(0, min(100, score))
    if s <= 50:
        r = 220
        g = int(s / 50 * 200)
        b = 60
    else:
        r = int((100 - s) / 50 * 200)
        g = 200
        b = 60
    return f"rgb({r},{g},{b})"

def compute_correlations(topics, topic_stats, people):
    # Build 6 cards, 3+3 layout, with no topic appearing as "b" more than once
    high_no_indices = [i for i, t in enumerate(topic_stats) if t["no_pct"] >= 30]
    high_no_indices = high_no_indices[:30]
    candidates = []
    for i in range(len(high_no_indices)):
        for j in range(i + 1, len(high_no_indices)):
            ti = high_no_indices[i]
            tj = high_no_indices[j]
            both_no = sum(
                1 for p in people
                if ti < len(p["responses"]) and p["responses"][ti] == "No"
                and tj < len(p["responses"]) and p["responses"][tj] == "No"
            )
            base_no = topic_stats[ti]["no"]
            if base_no >= 3:
                pct = round(both_no / base_no * 100)
                if pct >= 60 and both_no >= 3:
                    candidates.append({
                        "a": topics[ti],
                        "b": topics[tj],
                        "pct": pct,
                        "count": both_no,
                    })
    candidates.sort(key=lambda x: x["pct"], reverse=True)

    # Pick 6 cards where no topic appears as "a" or "b" more than once
    selected = []
    used_a = set()
    used_b = set()
    for c in candidates:
        if len(selected) >= 6:
            break
        if c["a"] not in used_a and c["b"] not in used_b:
            selected.append(c)
            used_a.add(c["a"])
            used_b.add(c["b"])
    return selected

def generate_html(topics, people, topic_stats, person_scores):
    updated = datetime.now(timezone.utc).strftime("%B %d, %Y at %H:%M UTC")
    n_people = len(people)
    n_topics = len(topics)

    sorted_topics_asc = sorted(topic_stats, key=lambda x: x["score"])
    bottom5_topics = sorted_topics_asc[:5]
    top5_topics = sorted_topics_asc[-5:][::-1]
    most_polarizing = sorted(topic_stats, key=lambda x: x["variance"], reverse=True)[:5]
    sorted_people_asc = sorted(person_scores, key=lambda x: x["score"])
    bottom5_people = sorted_people_asc[:5]
    top5_people = sorted_people_asc[-5:][::-1]
    avg_score = round(sum(t["score"] for t in topic_stats) / len(topic_stats), 1) if topic_stats else 0
    avg_color = score_color_css(avg_score)

    correlations = compute_correlations(topics, topic_stats, people)

    topic_stats_js = json.dumps(topic_stats)
    person_scores_js = json.dumps(person_scores)
    topics_js = json.dumps(topics)
    people_js = json.dumps([
        {"name": p["name"], "responses": p["responses"], "phone": p.get("phone", "")} for p in people
    ])
    correlations_js = json.dumps(correlations)

    def wrap_label(text, max_chars=35):
        # Split long labels into multiple lines for Chart.js (returns list of strings)
        words = text.split()
        lines = []
        current = ""
        for word in words:
            if len(current) + len(word) + 1 <= max_chars:
                current = (current + " " + word).strip()
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines if len(lines) > 1 else text

    top5_t_labels = json.dumps([wrap_label(t["topic"]) for t in top5_topics])
    top5_t_scores = json.dumps([t["score"] for t in top5_topics])
    bot5_t_labels = json.dumps([wrap_label(t["topic"]) for t in bottom5_topics])
    bot5_t_scores = json.dumps([t["score"] for t in bottom5_topics])
    polar_labels = json.dumps([wrap_label(t["topic"]) for t in most_polarizing])
    polar_scores = json.dumps([t["variance"] for t in most_polarizing])
    top5_p_labels = json.dumps([p["name"] for p in top5_people])
    top5_p_scores = json.dumps([p["score"] for p in top5_people])
    bot5_p_labels = json.dumps([p["name"] for p in bottom5_people])
    bot5_p_scores = json.dumps([p["score"] for p in bottom5_people])

    # Avg score breakdown for 6th chart
    avg_yes_pct = round(sum(t["yes_pct"] for t in topic_stats) / len(topic_stats), 1) if topic_stats else 0
    avg_sorta_pct = round(sum(t["sorta_pct"] for t in topic_stats) / len(topic_stats), 1) if topic_stats else 0
    avg_no_pct = round(sum(t["no_pct"] for t in topic_stats) / len(topic_stats), 1) if topic_stats else 0

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Strait Is The Gate Iron Sharpener</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  :root {{
    --bg: #0f1117;
    --surface: #1a1d27;
    --surface2: #22263a;
    --accent: #4f8ef7;
    --accent2: #7c5cbf;
    --text: #e8eaf0;
    --muted: #8b92a8;
    --yes: #3dba6e;
    --sorta: #e6b84a;
    --no: #e05353;
    --border: #2e3247;
    --radius: 10px;
  }}
  body.light {{
    --bg: #f4f6fb;
    --surface: #ffffff;
    --surface2: #eef0f7;
    --accent: #2563eb;
    --accent2: #6d3fc0;
    --text: #1a1d27;
    --muted: #5a6070;
    --yes: #1e8a4a;
    --sorta: #b07d0a;
    --no: #c0272d;
    --border: #d0d5e8;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: 'Segoe UI', system-ui, sans-serif; min-height: 100vh; transition: background 0.2s, color 0.2s; }}

  /* NAV */
  nav {{ background: var(--surface); border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 0; padding: 0 24px; position: sticky; top: 0; z-index: 100; }}
  .tab-btn {{ background: none; border: none; color: var(--muted); cursor: pointer; font-size: 0.95rem; padding: 18px 18px; border-bottom: 3px solid transparent; transition: all 0.2s; font-family: inherit; }}
  .tab-btn:hover {{ color: var(--text); }}
  .tab-btn.active {{ color: var(--accent); border-bottom-color: var(--accent); }}
  .nav-right {{ margin-left: auto; display: flex; align-items: center; gap: 16px; }}
  .updated {{ font-size: 0.75rem; color: var(--muted); white-space: nowrap; }}
  .theme-toggle {{ background: var(--surface2); border: 1px solid var(--border); border-radius: 20px; cursor: pointer; font-size: 0.8rem; color: var(--muted); padding: 5px 12px; font-family: inherit; transition: all 0.2s; white-space: nowrap; }}
  .theme-toggle:hover {{ color: var(--text); border-color: var(--accent); }}

  /* TABS */
  .tab {{ display: none; padding: 28px 24px; max-width: 1400px; margin: 0 auto; }}
  .tab.active {{ display: block; }}

  /* HOME */
  .hero {{ text-align: center; padding: 28px 0 20px; }}
  .hero h1 {{ font-size: 2.2rem; font-weight: 800; background: linear-gradient(135deg, var(--accent), var(--accent2)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; white-space: nowrap; }}
  .verse {{ color: var(--muted); font-size: 0.9rem; font-style: italic; max-width: 680px; margin: 12px auto 0; line-height: 1.65; }}
  .stats-row {{ display: flex; gap: 14px; justify-content: center; margin: 20px 0; flex-wrap: wrap; }}
  .stat-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 16px 28px; text-align: center; }}
  .stat-card .val {{ font-size: 1.8rem; font-weight: 700; }}
  .stat-card .lbl {{ color: var(--muted); font-size: 0.82rem; margin-top: 3px; }}
  .section {{ background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 20px 24px; margin-bottom: 18px; }}
  .section h2 {{ font-size: 1rem; font-weight: 700; margin-bottom: 14px; color: var(--accent); text-transform: uppercase; letter-spacing: 0.05em; }}
  .link-grid {{ display: flex; gap: 10px; flex-wrap: wrap; }}
  .link-card {{ background: var(--surface2); border: 1px solid var(--border); border-radius: 8px; padding: 12px 18px; text-decoration: none; color: var(--text); transition: border-color 0.2s, transform 0.15s; display: flex; align-items: center; gap: 10px; }}
  .link-card:hover {{ border-color: var(--accent); transform: translateY(-2px); }}
  .link-card .link-name {{ font-weight: 600; font-size: 0.92rem; }}
  .link-card .link-url {{ font-size: 0.73rem; color: var(--muted); }}
  .how-to {{ line-height: 1.75; color: var(--muted); font-size: 0.9rem; }}
  .how-to strong {{ color: var(--text); }}

  /* OVERVIEW TABLE */
  .toolbar {{ display: flex; gap: 12px; margin-bottom: 14px; align-items: center; flex-wrap: wrap; }}
  .search-box {{ background: var(--surface2); border: 1px solid var(--border); border-radius: 8px; color: var(--text); font-size: 0.9rem; padding: 9px 14px; outline: none; flex: 1; min-width: 200px; font-family: inherit; }}
  .search-box:focus {{ border-color: var(--accent); }}
  .table-wrap {{ overflow-x: auto; border-radius: var(--radius); border: 1px solid var(--border); }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.88rem; }}
  th {{ background: var(--surface2); color: var(--muted); font-weight: 600; padding: 11px 14px; text-align: left; cursor: pointer; user-select: none; white-space: nowrap; border-bottom: 1px solid var(--border); }}
  th:hover {{ color: var(--text); }}
  th .sort-arrow {{ margin-left: 4px; opacity: 0.4; }}
  th.sorted .sort-arrow {{ opacity: 1; color: var(--accent); }}
  td {{ padding: 10px 14px; border-bottom: 1px solid var(--border); vertical-align: middle; }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover td {{ background: rgba(79,142,247,0.04); }}
  .score-cell {{ font-weight: 700; border-radius: 6px; padding: 4px 10px; display: inline-block; color: #fff; font-size: 0.85rem; min-width: 52px; text-align: center; text-shadow: 0 1px 2px rgba(0,0,0,0.4); }}
  .pct-bar {{ display: flex; height: 8px; border-radius: 4px; overflow: hidden; width: 120px; gap: 1px; }}
  .pct-bar .seg-yes {{ background: var(--yes); }}
  .pct-bar .seg-sorta {{ background: var(--sorta); }}
  .pct-bar .seg-no {{ background: var(--no); }}

  /* CHARTS */
  .charts-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 18px; margin-bottom: 24px; }}
  @media (max-width: 1100px) {{ .charts-grid {{ grid-template-columns: repeat(2, 1fr); }} }}
  @media (max-width: 700px) {{ .charts-grid {{ grid-template-columns: 1fr; }} }}
  .chart-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 18px; }}
  .chart-card h3 {{ font-size: 0.88rem; font-weight: 700; color: var(--accent); margin-bottom: 14px; text-transform: uppercase; letter-spacing: 0.04em; }}
  .chart-wrap {{ position: relative; height: 220px; }}

  /* CORRELATIONS */
  .correlation-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }}
  @media (max-width: 900px) {{ .correlation-grid {{ grid-template-columns: repeat(2, 1fr); }} }}
  @media (max-width: 600px) {{ .correlation-grid {{ grid-template-columns: 1fr; }} }}
  .corr-card {{ background: var(--surface2); border: 1px solid var(--border); border-radius: 8px; padding: 14px 16px; }}
  .corr-pct {{ font-size: 1.5rem; font-weight: 800; color: var(--accent2); }}
  .corr-text {{ font-size: 0.82rem; color: var(--muted); margin-top: 6px; line-height: 1.5; }}
  .corr-text strong {{ color: var(--text); }}

  /* SHARPEN IRON */
  .sharpen-row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; align-items: start; }}
  @media (max-width: 800px) {{ .sharpen-row {{ grid-template-columns: 1fr; }} }}
  .search-panel {{ background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 20px 22px; }}
  .search-panel h2 {{ font-size: 0.95rem; font-weight: 700; color: var(--accent); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.05em; }}
  .search-panel p {{ color: var(--muted); font-size: 0.83rem; margin-bottom: 12px; }}
  .select-wrap {{ position: relative; }}
  .input-row {{ display: flex; gap: 8px; }}
  .searchable-input {{ flex: 1; background: var(--surface2); border: 1px solid var(--border); border-radius: 8px; color: var(--text); font-size: 0.9rem; padding: 9px 12px; outline: none; font-family: inherit; min-width: 0; }}
  .searchable-input:focus {{ border-color: var(--accent); }}
  .clear-btn {{ background: var(--surface2); border: 1px solid var(--border); border-radius: 8px; color: var(--muted); cursor: pointer; font-size: 0.82rem; padding: 9px 12px; font-family: inherit; white-space: nowrap; display: none; transition: all 0.15s; }}
  .clear-btn:hover {{ color: var(--no); border-color: var(--no); }}
  .clear-btn.visible {{ display: block; }}
  .dropdown {{ position: absolute; top: calc(100% + 4px); left: 0; right: 0; background: var(--surface2); border: 1px solid var(--border); border-radius: 8px; max-height: 240px; overflow-y: auto; z-index: 200; display: none; }}
  .dropdown.open {{ display: block; }}
  .dd-item {{ padding: 9px 12px; cursor: pointer; font-size: 0.86rem; }}
  .dd-item:hover, .dd-item.focused {{ background: rgba(79,142,247,0.12); color: var(--accent); }}
  .result-table-wrap {{ overflow-x: auto; border-radius: var(--radius); border: 1px solid var(--border); margin-top: 14px; display: none; }}
  .result-table-wrap.visible {{ display: block; }}
  .three-col {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 0; }}
  .three-col .col-head {{ background: var(--surface2); padding: 9px 12px; font-weight: 700; font-size: 0.82rem; border-bottom: 1px solid var(--border); }}
  .col-head.yes {{ color: var(--yes); }}
  .col-head.sorta {{ color: var(--sorta); }}
  .col-head.no {{ color: var(--no); }}
  .three-col .col-body {{ padding: 8px 12px; border-bottom: 1px solid var(--border); font-size: 0.83rem; }}

  /* VIDEOS TAB */
  .videos-search-bar {{ display: flex; gap: 12px; margin-bottom: 20px; align-items: center; flex-wrap: wrap; }}
  .videos-search-bar .search-box {{ max-width: 380px; }}
  .topic-filter-wrap {{ display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }}
  .topic-filter-wrap label {{ color: var(--muted); font-size: 0.85rem; white-space: nowrap; }}
  .topic-select {{ background: var(--surface2); border: 1px solid var(--border); border-radius: 8px; color: var(--text); font-size: 0.88rem; padding: 9px 12px; outline: none; font-family: inherit; cursor: pointer; min-width: 200px; max-width: 320px; }}
  .topic-select:focus {{ border-color: var(--accent); }}
  .video-count {{ color: var(--muted); font-size: 0.85rem; white-space: nowrap; }}
  .video-topics-list {{ display: flex; flex-direction: column; gap: 24px; }}
  .video-topic-group {{ background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); overflow: hidden; }}
  .video-topic-header {{ padding: 14px 20px; border-bottom: 1px solid var(--border); }}
  .video-topic-header h3 {{ font-size: 0.95rem; font-weight: 700; color: var(--accent); }}
  .video-topic-header .subtopics {{ color: var(--muted); font-size: 0.78rem; margin-top: 3px; font-style: italic; }}
  .video-cards {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 12px; padding: 14px 16px; }}
  .video-card {{ background: var(--surface2); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; transition: border-color 0.2s, transform 0.15s; display: flex; flex-direction: column; }}
  .video-card:hover {{ border-color: var(--accent); transform: translateY(-2px); }}
  .video-thumb {{ position: relative; width: 100%; aspect-ratio: 16/9; background: #000; overflow: hidden; }}
  .video-thumb img {{ width: 100%; height: 100%; object-fit: cover; display: block; }}
  .video-thumb .play-icon {{ position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; background: rgba(0,0,0,0.35); opacity: 0; transition: opacity 0.2s; }}
  .video-card:hover .play-icon {{ opacity: 1; }}
  .play-icon svg {{ width: 40px; height: 40px; fill: white; filter: drop-shadow(0 2px 4px rgba(0,0,0,0.6)); }}
  .video-card-body {{ padding: 10px 12px; flex: 1; }}
  .video-speaker {{ font-size: 0.75rem; font-weight: 700; color: var(--accent2); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 3px; }}
  .video-link {{ color: var(--text); text-decoration: none; font-size: 0.83rem; display: block; line-height: 1.4; }}
  .video-link:hover {{ color: var(--accent); }}
  .video-platform {{ font-size: 0.7rem; color: var(--muted); margin-top: 4px; }}
  .no-videos-msg {{ color: var(--muted); font-size: 0.9rem; padding: 24px; text-align: center; }}

  /* BUDDY FINDER */
  .buddy-search-wrap {{ max-width: 480px; margin-bottom: 28px; }}
  .buddy-search-wrap .search-panel {{ padding: 18px 20px; }}
  .buddy-search-wrap .search-panel h2 {{ margin-bottom: 8px; }}
  .buddy-search-wrap .search-panel p {{ margin-bottom: 14px; }}
  .buddy-sections {{ display: flex; flex-direction: column; gap: 28px; }}
  .buddy-section-title {{ font-size: 0.85rem; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 14px; display: flex; align-items: center; gap: 10px; }}
  .buddy-section-title::after {{ content: ''; flex: 1; height: 1px; background: var(--border); }}
  .buddy-pairs-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 14px; }}
  @media (max-width: 700px) {{ .buddy-pairs-grid {{ grid-template-columns: 1fr; }} }}
  .buddy-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 18px 20px; display: flex; flex-direction: column; gap: 14px; transition: border-color 0.2s, transform 0.15s; position: relative; overflow: hidden; }}
  .buddy-card::before {{ content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px; background: linear-gradient(90deg, var(--accent), var(--accent2)); opacity: 0; transition: opacity 0.2s; }}
  .buddy-card:hover {{ border-color: var(--accent); transform: translateY(-2px); }}
  .buddy-card:hover::before {{ opacity: 1; }}
  .buddy-card-header {{ display: flex; align-items: center; gap: 10px; justify-content: space-between; }}
  .buddy-name {{ font-size: 1.05rem; font-weight: 700; color: var(--text); flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .buddy-rank {{ font-size: 0.7rem; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; flex-shrink: 0; }}
  .buddy-score-row {{ display: flex; align-items: center; gap: 10px; }}
  .buddy-score-label {{ font-size: 0.75rem; color: var(--muted); white-space: nowrap; }}
  .buddy-score-bar {{ flex: 1; height: 6px; background: var(--surface2); border-radius: 3px; overflow: hidden; }}
  .buddy-score-bar-fill {{ height: 100%; border-radius: 3px; background: linear-gradient(90deg, var(--accent), var(--accent2)); transition: width 0.4s ease; }}
  .buddy-exchange {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }}
  .buddy-direction {{ background: var(--surface2); border-radius: 8px; padding: 10px 12px; }}
  .buddy-dir-label {{ font-size: 0.68rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .buddy-dir-label.can-teach {{ color: var(--yes); }}
  .buddy-dir-label.learns-from {{ color: var(--accent); }}
  .buddy-dir-count {{ font-size: 1.2rem; font-weight: 800; color: var(--text); line-height: 1; margin-bottom: 8px; }}
  .buddy-dir-count span {{ font-size: 0.72rem; font-weight: 400; color: var(--muted); margin-left: 2px; }}
  .buddy-topic-pills {{ display: flex; flex-direction: column; gap: 3px; }}
  .buddy-pill {{ font-size: 0.7rem; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; padding: 2px 0 2px 6px; border-left: 2px solid var(--border); }}
  .buddy-pill.teach {{ border-left-color: var(--yes); color: var(--text); }}
  .buddy-pill.learn {{ border-left-color: var(--accent); color: var(--text); }}
  .buddy-footer {{ display: flex; align-items: center; gap: 6px; padding-top: 6px; border-top: 1px solid var(--border); flex-wrap: wrap; }}
  .buddy-gap-badge {{ font-size: 0.72rem; background: rgba(224,83,83,0.12); color: var(--no); border: 1px solid rgba(224,83,83,0.25); border-radius: 12px; padding: 2px 8px; font-weight: 600; }}
  .buddy-common-badge {{ font-size: 0.72rem; background: rgba(61,186,110,0.1); color: var(--yes); border: 1px solid rgba(61,186,110,0.2); border-radius: 12px; padding: 2px 8px; font-weight: 600; }}
  .buddy-trios-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(380px, 1fr)); gap: 14px; }}
  @media (max-width: 800px) {{ .buddy-trios-grid {{ grid-template-columns: 1fr; }} }}
  .trio-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 18px 20px; display: flex; flex-direction: column; gap: 14px; transition: border-color 0.2s, transform 0.15s; position: relative; overflow: hidden; }}
  .trio-card::before {{ content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px; background: linear-gradient(90deg, var(--yes), var(--accent), var(--accent2)); opacity: 0; transition: opacity 0.2s; }}
  .trio-card:hover {{ border-color: var(--accent2); transform: translateY(-2px); }}
  .trio-card:hover::before {{ opacity: 1; }}
  .trio-names {{ display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }}
  .trio-name-chip {{ background: var(--surface2); border: 1px solid var(--border); border-radius: 16px; padding: 4px 10px; font-size: 0.85rem; font-weight: 600; }}
  .trio-name-chip.is-you {{ border-color: var(--accent); color: var(--accent); }}
  .trio-joiner {{ color: var(--muted); font-size: 0.8rem; font-weight: 700; }}
  .trio-stats {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }}
  .trio-stat {{ background: var(--surface2); border-radius: 8px; padding: 10px 8px; text-align: center; }}
  .trio-stat-val {{ font-size: 1.3rem; font-weight: 800; line-height: 1; margin-bottom: 4px; }}
  .trio-stat-lbl {{ font-size: 0.65rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; line-height: 1.3; }}
  .buddy-empty {{ color: var(--muted); font-size: 0.9rem; text-align: center; padding: 40px 20px; border: 1px dashed var(--border); border-radius: var(--radius); }}
  .buddy-detail-cols {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
  @media (max-width: 520px) {{ .buddy-detail-cols {{ grid-template-columns: 1fr; }} }}
  .buddy-detail-col-head {{ font-size: 0.78rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 10px; padding-bottom: 6px; border-bottom: 1px solid var(--border); }}
  .buddy-detail-col-head.can-teach {{ color: var(--yes); }}
  .buddy-detail-col-head.learns-from {{ color: var(--accent); }}
  .buddy-detail-list {{ display: flex; flex-direction: column; gap: 2px; max-height: 50vh; overflow-y: auto; }}
  .buddy-detail-row {{ font-size: 0.82rem; padding: 5px 8px 5px 10px; border-radius: 4px; border-left: 2px solid var(--border); }}
  .buddy-detail-row.teach {{ border-left-color: var(--yes); background: rgba(61,186,110,0.06); }}
  .buddy-detail-row.learn {{ border-left-color: var(--accent); background: rgba(79,142,247,0.06); }}

  /* SCROLLBAR */
  ::-webkit-scrollbar {{ width: 7px; height: 7px; }}
  ::-webkit-scrollbar-track {{ background: var(--surface); }}
  ::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 4px; }}
  ::-webkit-scrollbar-thumb:hover {{ background: var(--muted); }}
</style>
</head>
<body>

<nav>
  <button class="tab-btn active" onclick="showTab('home',this)">Home</button>
  <button class="tab-btn" onclick="showTab('overview',this)">Overview</button>
  <button class="tab-btn" onclick="showTab('sharpen',this)">Sharpen Iron</button>
  <button class="tab-btn" onclick="showTab('videos',this)">Associated Videos</button>
  <button class="tab-btn" onclick="showTab('buddy',this)">Buddy Finder</button>
  <div class="nav-right">
    <button class="theme-toggle" onclick="toggleTheme()" id="theme-btn">Light Mode</button>
    <span class="updated">Updated: {updated}</span>
  </div>
</nav>

<!-- HOME -->
<div id="tab-home" class="tab active">
  <div class="hero">
    <h1>Strait Is The Gate Iron Sharpener</h1>
    <p class="verse">Then they that feared the Lord spake often one to another: and the Lord hearkened, and heard it, and a book of remembrance was written before him for them that feared the Lord, and that thought upon his name.</p>
  </div>

  <div class="stats-row">
    <div class="stat-card"><div class="val" style="color:var(--accent)">{n_people}</div><div class="lbl">Respondents</div></div>
    <div class="stat-card"><div class="val" style="color:var(--accent)">{n_topics}</div><div class="lbl">Topics Assessed</div></div>
    <div class="stat-card"><div class="val" style="color:{avg_color}">{avg_score}%</div><div class="lbl">Avg Understanding Score</div></div>
  </div>

  <div class="section">
    <h2>Helpful Resources</h2>
    <div class="link-grid">
      <a class="link-card" href="https://straitisthegate.net" target="_blank">
        <div><div class="link-name">Main Website</div><div class="link-url">straitisthegate.net</div></div>
      </a>
      <a class="link-card" href="https://straitisthegatesearch.netlify.app" target="_blank">
        <div><div class="link-name">Video Search Tool</div><div class="link-url">straitisthegatesearch.netlify.app</div></div>
      </a>
      <a class="link-card" href="https://straitisthegatex.net/" target="_blank">
        <div><div class="link-name">Notes Search Tool</div><div class="link-url">straitisthegatex.net</div></div>
      </a>
      <a class="link-card" href="https://docs.google.com/forms/d/e/1FAIpQLSeQt3OUu6ULGHqqfB2NArVS6B67K2GX0R89TLwBUinURDjflg/viewform" target="_blank">
        <div><div class="link-name">Original Form (Submit or Edit Your Response)</div><div class="link-url">docs.google.com</div></div>
      </a>
    </div>
  </div>

  <div class="section">
    <h2>How to Use This Site</h2>
    <div class="how-to">
      <p><strong>Overview Tab</strong>: See every topic ranked by how well its understood overall. Sort columns, search topics, and explore analytics including the top and bottom performing topics, most polarising questions, and hidden correlations of knowledge gaps.</p>
      <br>
      <p><strong>Sharpen Iron Tab</strong>: Drill down two ways:</p>
      <ul style="margin: 8px 0 0 20px; line-height: 2;">
        <li><strong>Search by Topic</strong>: Pick any topic and see who knows it, who partly knows it, and who doesn&apos;t so you can reach out and help people.</li>
        <li><strong>Search by Person</strong>: Pick any person and see what they know, what they&apos;re confused with, and what they still need to learn.</li>
      </ul>
      <br>
      <p><strong>Associated Videos Tab</strong>: Browse curated YouTube videos for each topic. Search by keyword or filter by topic to find teaching resources that will help you learn.</p>
      <br>
      <p><strong>Buddy Finder Tab</strong>: Enter your name to find the people who complement your knowledge most — those who know what you don&apos;t, and don&apos;t know what you do. Tap any match card to see the full topic breakdown.</p>
    </div>
  </div>
</div>

<!-- OVERVIEW -->
<div id="tab-overview" class="tab">

  <div class="charts-grid">
    <div class="chart-card">
      <h3>Top 5 Best Understood Topics</h3>
      <div class="chart-wrap"><canvas id="chart-top-topics"></canvas></div>
    </div>
    <div class="chart-card">
      <h3>Bottom 5 Least Understood Topics</h3>
      <div class="chart-wrap"><canvas id="chart-bot-topics"></canvas></div>
    </div>
    <div class="chart-card">
      <h3>Most Polarising Topics</h3>
      <div class="chart-wrap"><canvas id="chart-polar"></canvas></div>
    </div>
    <div class="chart-card">
      <h3>Top 5 People by Understanding</h3>
      <div class="chart-wrap"><canvas id="chart-top-people"></canvas></div>
    </div>
    <div class="chart-card">
      <h3>Bottom 5 People by Understanding</h3>
      <div class="chart-wrap"><canvas id="chart-bot-people"></canvas></div>
    </div>
    <div class="chart-card">
      <h3>Overall Response Breakdown</h3>
      <div class="chart-wrap"><canvas id="chart-doughnut"></canvas></div>
    </div>
  </div>

  <div class="section" id="corr-section" style="display:none">
    <h2>Knowledge Gap Correlations</h2>
    <p style="color:var(--muted);font-size:0.83rem;margin-bottom:14px;">Among people who said "No" to a topic, what percentage also said "No" to another?</p>
    <div class="correlation-grid" id="corr-grid"></div>
  </div>

  <div class="section">
    <h2>All Topics</h2>
    <div class="toolbar">
      <input class="search-box" id="overview-search" placeholder="Search topics..." oninput="filterOverview()">
      <span id="overview-count" style="color:var(--muted);font-size:0.85rem;white-space:nowrap;"></span>
    </div>
    <div class="table-wrap">
      <table id="overview-table">
        <thead>
          <tr>
            <th onclick="sortOverview(0)" data-col="0">Topic <span class="sort-arrow">&#8597;</span></th>
            <th onclick="sortOverview(1)" data-col="1">Understanding Score <span class="sort-arrow">&#8597;</span></th>
            <th onclick="sortOverview(2)" data-col="2">Yes % <span class="sort-arrow">&#8597;</span></th>
            <th onclick="sortOverview(3)" data-col="3">Sorta % <span class="sort-arrow">&#8597;</span></th>
            <th onclick="sortOverview(4)" data-col="4">No % <span class="sort-arrow">&#8597;</span></th>
          </tr>
        </thead>
        <tbody id="overview-tbody"></tbody>
      </table>
    </div>
  </div>
</div>

<!-- ASSOCIATED VIDEOS -->
<div id="tab-videos" class="tab">
  <div class="videos-search-bar">
    <input class="search-box" id="videos-search" placeholder="Search videos or topics..." oninput="filterVideos()">
    <select class="topic-select" id="videos-topic-filter" onchange="filterVideos()">
      <option value="">All Topics</option>
    </select>
    <span class="video-count" id="video-count"></span>
  </div>
  <div class="video-topics-list" id="video-topics-list"></div>
</div>

<!-- SHARPEN IRON -->
<div id="tab-sharpen" class="tab">
  <div class="sharpen-row">

    <div class="search-panel">
      <h2>Search by Topic</h2>
      <p>Select a topic to see who knows it, and who needs help.</p>
      <div class="select-wrap" id="topic-wrap">
        <div class="input-row">
          <input class="searchable-input" id="topic-input" placeholder="Type to search topics..." autocomplete="off"
            oninput="filterDD('topic')" onfocus="openDD('topic')" onkeydown="ddKey(event,'topic')">
          <button class="clear-btn" id="topic-clear" onclick="clearDD('topic')">Clear</button>
        </div>
        <div class="dropdown" id="topic-dd"></div>
      </div>
      <div class="result-table-wrap" id="topic-result">
        <div class="three-col" id="topic-result-inner"></div>
      </div>
    </div>

    <div class="search-panel">
      <h2>Search by Person</h2>
      <p>Select a person to see what they know, and what they don&apos;t.</p>
      <div class="select-wrap" id="person-wrap">
        <div class="input-row">
          <input class="searchable-input" id="person-input" placeholder="Type to search people..." autocomplete="off"
            oninput="filterDD('person')" onfocus="openDD('person')" onkeydown="ddKey(event,'person')">
          <button class="clear-btn" id="person-clear" onclick="clearDD('person')">Clear</button>
        </div>
        <div class="dropdown" id="person-dd"></div>
      </div>
      <div class="result-table-wrap" id="person-result">
        <div class="three-col" id="person-result-inner"></div>
      </div>
    </div>

  </div>
</div>

<!-- BUDDY FINDER -->
<div id="tab-buddy" class="tab">

  <div class="buddy-search-wrap">
    <div class="search-panel">
      <h2>Buddy Finder</h2>
      <p>Enter your name to let the buddy finder engine suggest the perfect people to buddy up with.</p>
      <div class="select-wrap" id="buddy-wrap">
        <div class="input-row">
          <input class="searchable-input" id="buddy-input"
            placeholder="Type your name to find matches..."
            autocomplete="off"
            oninput="filterDD('buddy')"
            onfocus="openDD('buddy')"
            onkeydown="ddKey(event,'buddy')">
          <button class="clear-btn visible" id="buddy-clear" onclick="clearBuddy()" style="display:none">Clear</button>
        </div>
        <div class="dropdown" id="buddy-dd"></div>
      </div>
    </div>
  </div>

  <div id="buddy-results" style="display:none" class="buddy-sections">
    <div>
      <div class="buddy-section-title">Top 4 Pair Buddies</div>
      <div class="buddy-pairs-grid" id="buddy-pairs-grid"></div>
    </div>
    <div>
      <div class="buddy-section-title">Top 3 Trio Study Groups</div>
      <div class="buddy-trios-grid" id="buddy-trios-grid"></div>
    </div>
  </div>

  <div id="buddy-empty-state" class="buddy-empty" style="display:none">
    Not enough other respondents to generate buddy matches.
  </div>

</div>

<!-- BUDDY DETAIL MODAL -->
<div id="buddy-modal-overlay" onclick="closeBuddyDetail()" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.55);z-index:900"></div>
<div id="buddy-modal" style="display:none;position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);z-index:901;width:min(700px,95vw);max-height:80vh;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);flex-direction:column;overflow:hidden;box-shadow:0 20px 60px rgba(0,0,0,0.5)">
  <div style="display:flex;align-items:center;justify-content:space-between;padding:16px 20px;border-bottom:1px solid var(--border);flex-shrink:0">
    <div id="buddy-modal-title" style="font-weight:700;font-size:1rem;color:var(--text)"></div>
    <button onclick="closeBuddyDetail()" style="background:none;border:none;color:var(--muted);cursor:pointer;font-size:1.3rem;line-height:1;padding:2px 6px" title="Close">&times;</button>
  </div>
  <div id="buddy-modal-body" style="overflow-y:auto;padding:18px 20px;flex:1"></div>
</div>

<script>
const TOPIC_STATS = {topic_stats_js};
const PERSON_SCORES = {person_scores_js};
const TOPICS = {topics_js};
const PEOPLE = {people_js};
const CORRELATIONS = {correlations_js};
const AVG_YES = {avg_yes_pct};
const AVG_SORTA = {avg_sorta_pct};
const AVG_NO = {avg_no_pct};

// Theme
function toggleTheme() {{
  const isLight = document.body.classList.toggle('light');
  document.getElementById('theme-btn').textContent = isLight ? 'Dark Mode' : 'Light Mode';
  localStorage.setItem('theme', isLight ? 'light' : 'dark');
  if (window._chartsBuilt) {{ rebuildCharts(); }}
}}
(function() {{
  if (localStorage.getItem('theme') === 'light') {{
    document.body.classList.add('light');
    document.getElementById('theme-btn').textContent = 'Dark Mode';
  }}
}})();

// Tab switching
function showTab(id, btn) {{
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + id).classList.add('active');
  btn.classList.add('active');
  if (id === 'overview' && !window._chartsBuilt) buildCharts();
}}

// Score color (matches Python)
function scoreColor(s) {{
  s = Math.max(0, Math.min(100, s));
  let r, g;
  if (s <= 50) {{ r = 220; g = Math.round(s / 50 * 200); }}
  else {{ r = Math.round((100 - s) / 50 * 200); g = 200; }}
  return `rgb(${{r}},${{g}},60)`;
}}

function getCSSVar(name) {{
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}}

// Overview table
let ovData = TOPIC_STATS.map(t => ({{...t}}));
let ovSort = {{col: 1, asc: false}};

function renderOverview() {{
  const tbody = document.getElementById('overview-tbody');
  tbody.innerHTML = '';
  ovData.forEach(t => {{
    const color = scoreColor(t.score);
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${{escH(t.topic)}}</td>
      <td><span class="score-cell" style="background:${{color}}">${{t.score}}</span></td>
      <td>
        <div style="display:flex;align-items:center;gap:8px">
          <div class="pct-bar">
            <div class="seg-yes" style="width:${{t.yes_pct}}%"></div>
            <div class="seg-sorta" style="width:${{t.sorta_pct}}%"></div>
            <div class="seg-no" style="width:${{t.no_pct}}%"></div>
          </div>
          <span style="color:var(--yes);font-size:0.82rem">${{t.yes_pct}}%</span>
        </div>
      </td>
      <td style="color:var(--sorta)">${{t.sorta_pct}}%</td>
      <td style="color:var(--no)">${{t.no_pct}}%</td>`;
    tbody.appendChild(tr);
  }});
  document.getElementById('overview-count').textContent = ovData.length + ' topics';
  document.querySelectorAll('#overview-table th').forEach((th, i) => {{
    th.classList.toggle('sorted', i === ovSort.col);
    th.querySelector('.sort-arrow').textContent = i === ovSort.col ? (ovSort.asc ? '\u2191' : '\u2193') : '\u2195';
  }});
}}

function filterOverview() {{
  const q = document.getElementById('overview-search').value.toLowerCase();
  ovData = TOPIC_STATS.filter(t => t.topic.toLowerCase().includes(q));
  sortAndRender();
}}

function sortOverview(col) {{
  if (ovSort.col === col) ovSort.asc = !ovSort.asc;
  else {{ ovSort.col = col; ovSort.asc = col === 0; }}
  sortAndRender();
}}

function sortAndRender() {{
  const keys = ['topic', 'score', 'yes_pct', 'sorta_pct', 'no_pct'];
  const k = keys[ovSort.col];
  ovData.sort((a, b) => {{
    if (typeof a[k] === 'string') return ovSort.asc ? a[k].localeCompare(b[k]) : b[k].localeCompare(a[k]);
    return ovSort.asc ? a[k] - b[k] : b[k] - a[k];
  }});
  renderOverview();
}}

function escH(s) {{
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}}

sortAndRender();

// Correlations
if (CORRELATIONS.length > 0) {{
  document.getElementById('corr-section').style.display = '';
  const grid = document.getElementById('corr-grid');
  CORRELATIONS.forEach(c => {{
    const div = document.createElement('div');
    div.className = 'corr-card';
    div.innerHTML = `<div class="corr-pct">${{c.pct}}%</div>
      <div class="corr-text">of people who didn&apos;t know <strong>${{escH(c.a)}}</strong> also didn&apos;t know <strong>${{escH(c.b)}}</strong><br><span style="font-size:0.75rem">(${{c.count}} people)</span></div>`;
    grid.appendChild(div);
  }});
}}

// Charts
window._chartsBuilt = false;
let chartInstances = {{}};

function getChartDefaults() {{
  const mutedColor = getCSSVar('--muted') || '#8b92a8';
  const borderColor = getCSSVar('--border') || '#2e3247';
  return {{
    responsive: true, maintainAspectRatio: false,
    plugins: {{ legend: {{ display: false }}, tooltip: {{ callbacks: {{ label: ctx => ' ' + ctx.parsed.x + '%' }} }} }},
    scales: {{
      x: {{ ticks: {{ color: mutedColor }}, grid: {{ color: borderColor }} }},
      y: {{ ticks: {{ color: mutedColor, font: {{ size: 11 }} }}, grid: {{ display: false }} }}
    }}
  }};
}}

function buildCharts() {{
  window._chartsBuilt = true;
  const defs = getChartDefaults();
  const mutedColor = getCSSVar('--muted') || '#8b92a8';

  function hbar(id, labels, data, colors) {{
    if (chartInstances[id]) chartInstances[id].destroy();
    chartInstances[id] = new Chart(document.getElementById(id), {{
      type: 'bar',
      data: {{ labels, datasets: [{{ data, backgroundColor: colors || data.map(v => scoreColor(v)), borderRadius: 5 }}] }},
      options: {{
        ...defs,
        indexAxis: 'y',
        scales: {{
          x: {{ ...defs.scales.x, max: 100 }},
          y: {{ ...defs.scales.y }}
        }}
      }}
    }});
  }}

  hbar('chart-top-topics', {top5_t_labels}, {top5_t_scores});
  hbar('chart-bot-topics', {bot5_t_labels}, {bot5_t_scores});

  if (chartInstances['chart-polar']) chartInstances['chart-polar'].destroy();
  chartInstances['chart-polar'] = new Chart(document.getElementById('chart-polar'), {{
    type: 'bar',
    data: {{ labels: {polar_labels}, datasets: [{{ data: {polar_scores}, backgroundColor: '#7c5cbf', borderRadius: 5 }}] }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      indexAxis: 'y',
      plugins: {{ legend: {{ display: false }}, tooltip: {{ callbacks: {{ label: ctx => ' variance: ' + ctx.parsed.x }} }} }},
      scales: {{
        x: {{ ticks: {{ color: mutedColor }}, grid: {{ color: getCSSVar('--border') || '#2e3247' }} }},
        y: {{ ticks: {{ color: mutedColor, font: {{ size: 11 }} }}, grid: {{ display: false }} }}
      }}
    }}
  }});

  hbar('chart-top-people', {top5_p_labels}, {top5_p_scores});
  hbar('chart-bot-people', {bot5_p_labels}, {bot5_p_scores});

  if (chartInstances['chart-doughnut']) chartInstances['chart-doughnut'].destroy();
  chartInstances['chart-doughnut'] = new Chart(document.getElementById('chart-doughnut'), {{
    type: 'doughnut',
    data: {{
      labels: ['Yes', 'Sorta', 'No'],
      datasets: [{{
        data: [AVG_YES, AVG_SORTA, AVG_NO],
        backgroundColor: ['#3dba6e', '#e6b84a', '#e05353'],
        borderWidth: 0,
        borderRadius: 4,
      }}]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      plugins: {{
        legend: {{ display: true, position: 'bottom', labels: {{ color: mutedColor, font: {{ size: 12 }}, padding: 16 }} }},
        tooltip: {{ callbacks: {{ label: ctx => ' ' + ctx.label + ': ' + ctx.parsed + '%' }} }}
      }}
    }}
  }});
}}

function rebuildCharts() {{
  buildCharts();
}}

// Dropdowns
const ddState = {{
  topic: {{ items: TOPICS, selected: null, focused: -1, filtered: null }},
  person: {{ items: PEOPLE.map(p => p.name), selected: null, focused: -1, filtered: null }}
}};

function filterDD(type) {{
  const q = document.getElementById(type + '-input').value.toLowerCase();
  const s = ddState[type];
  s.filtered = s.items.filter(item => item.toLowerCase().includes(q));
  s.focused = -1;
  renderDD(type);
  openDD(type);
}}

function openDD(type) {{
  const s = ddState[type];
  if (!s.filtered) s.filtered = [...s.items];
  renderDD(type);
  document.getElementById(type + '-dd').classList.add('open');
}}

function closeDD(type) {{
  document.getElementById(type + '-dd').classList.remove('open');
}}

function renderDD(type) {{
  const s = ddState[type];
  const dd = document.getElementById(type + '-dd');
  dd.innerHTML = '';
  (s.filtered || s.items).forEach((item, i) => {{
    const div = document.createElement('div');
    div.className = 'dd-item' + (i === s.focused ? ' focused' : '');
    div.textContent = item;
    div.onmousedown = () => selectDD(type, item);
    dd.appendChild(div);
  }});
}}

function selectDD(type, value) {{
  ddState[type].selected = value;
  document.getElementById(type + '-input').value = value;
  document.getElementById(type + '-clear').classList.add('visible');
  closeDD(type);
  if (type === 'topic') showTopicResult(value);
  else showPersonResult(value);
}}

function clearDD(type) {{
  ddState[type].selected = null;
  ddState[type].filtered = null;
  document.getElementById(type + '-input').value = '';
  document.getElementById(type + '-clear').classList.remove('visible');
  document.getElementById(type + '-result').classList.remove('visible');
}}

function ddKey(e, type) {{
  const s = ddState[type];
  const items = s.filtered || s.items;
  if (e.key === 'ArrowDown') {{ s.focused = Math.min(s.focused + 1, items.length - 1); renderDD(type); e.preventDefault(); }}
  else if (e.key === 'ArrowUp') {{ s.focused = Math.max(s.focused - 1, 0); renderDD(type); e.preventDefault(); }}
  else if (e.key === 'Enter' && s.focused >= 0) {{ selectDD(type, items[s.focused]); }}
  else if (e.key === 'Escape') {{ closeDD(type); }}
}}

document.addEventListener('click', e => {{
  ['topic', 'person'].forEach(type => {{
    if (!document.getElementById(type + '-wrap').contains(e.target)) closeDD(type);
  }});
}});

function showTopicResult(topic) {{
  const topicIdx = TOPICS.indexOf(topic);
  if (topicIdx === -1) return;
  const yes = [], sorta = [], no = [];
  PEOPLE.forEach(p => {{
    const r = p.responses[topicIdx] || 'No';
    if (r === 'Yes') yes.push(p.name);
    else if (r === 'Sorta') sorta.push(p.name);
    else no.push(p.name);
  }});
  const maxRows = Math.max(yes.length, sorta.length, no.length);
  let rows = `
    <div class="col-head yes">Know it (${{yes.length}})</div>
    <div class="col-head sorta">Sorta know it (${{sorta.length}})</div>
    <div class="col-head no">Don&apos;t know it (${{no.length}})</div>`;
  for (let i = 0; i < maxRows; i++) {{
    rows += `<div class="col-body">${{yes[i] ? escH(yes[i]) : ''}}</div>`;
    rows += `<div class="col-body">${{sorta[i] ? escH(sorta[i]) : ''}}</div>`;
    rows += `<div class="col-body">${{no[i] ? escH(no[i]) : ''}}</div>`;
  }}
  document.getElementById('topic-result-inner').innerHTML = rows;
  document.getElementById('topic-result').classList.add('visible');
}}

// ── Associated Videos ─────────────────────────────────────────────────────
const VIDEO_DATA = [
  {{
    topic: "How to Read the Bible",
    subtopics: "",
    videos: [
      {{ speaker: "Andrew", url: "https://youtu.be/ZTdCA-hcY98", note: "Bible cheat codes. IMPORTANT" }},
      {{ speaker: "Big Mike", url: "https://youtu.be/AKni_2NIjPs", note: "the website he is using is linked in the description" }},
      {{ speaker: "Mark", url: "https://youtu.be/r1p6B5F1Qwc?si=xiZycx-8Iou6JnFR", note: "" }},
      {{ speaker: "Mark", url: "https://www.youtube.com/live/XfSoifA3NO4?si=i_nFjTkfaXwcgYVk", note: "" }}
    ]
  }},
  {{
    topic: "Rainbow Covenant",
    subtopics: "Noahic / Rainbow Covenant — Can Christians eat pork?",
    videos: [
      {{ speaker: "Josh", url: "https://youtu.be/ko5k0mb6SUk", note: "" }},
      {{ speaker: "Group", url: "https://youtu.be/XnMguUIJvMs", note: "" }}
    ]
  }},
  {{
    topic: "Peter's Vision",
    subtopics: "",
    videos: [
      {{ speaker: "Matthew UK", url: "https://youtu.be/Gq1xgh0rOuk", note: "" }},
      {{ speaker: "Mark", url: "https://youtu.be/MrcuTC9axCo", note: "" }},
      {{ speaker: "Daniel San", url: "https://youtu.be/s_kAKIyeFmU", note: "" }}
    ]
  }},
  {{
    topic: "He Made All Foods Clean",
    subtopics: "",
    videos: [
      {{ speaker: "Matthew UK", url: "https://youtu.be/bjv-9wFkCqE", note: "" }},
      {{ speaker: "Mark", url: "https://www.youtube.com/live/MrcuTC9axCo?si=TDKEdmGYRl6KCUjP", note: "" }}
    ]
  }},
  {{
    topic: "Love / Fear of God",
    subtopics: "Enter into life",
    videos: [
      {{ speaker: "Mark", url: "https://youtu.be/GG9azonD-Us", note: "" }},
      {{ speaker: "Mark", url: "https://youtu.be/N9jlpqBuPDg", note: "" }},
      {{ speaker: "Mark", url: "https://youtu.be/jHA8XxtVGDQ", note: "" }},
      {{ speaker: "Daniel San", url: "https://youtu.be/6lr-OX5HZIA", note: "" }},
      {{ speaker: "Andrew", url: "https://youtu.be/Lq56OPzkcP8", note: "" }},
      {{ speaker: "Matthew UK", url: "https://youtu.be/jM5EMybEsjs", note: "Enter into life" }}
    ]
  }},
  {{
    topic: "The Will of God / Heart's Desire",
    subtopics: "",
    videos: [
      {{ speaker: "Daniel San", url: "https://youtu.be/_I4CsjWkycE", note: "" }},
      {{ speaker: "Matthew UK", url: "https://www.youtube.com/live/CCR9RpFUnyI?si=Z9_M7tpnOVuHhWf8", note: "" }},
      {{ speaker: "Big Mike", url: "https://www.tiktok.com/t/ZThXYy6tD/", note: "" }}
    ]
  }},
  {{
    topic: "Born Again / Christmas",
    subtopics: "No one celebrating Christmas will enter the kingdom of heaven — Christmas is idolatry",
    videos: [
      {{ speaker: "Matthew UK", url: "https://youtu.be/RTD1Z70lO_8", note: "" }},
      {{ speaker: "Matthew UK", url: "https://youtu.be/EcD11E3RiLQ", note: "No one celebrating Christmas will enter the kingdom of heaven — Christmas is idolatry" }},
      {{ speaker: "Mark", url: "https://youtu.be/1kQgrfsr7HI", note: "" }},
      {{ speaker: "Mark", url: "https://youtu.be/BPaD8gIdg4M", note: "Christmas is idolatry" }},
      {{ speaker: "Ricky", url: "https://youtu.be/2N6F--CMfYc", note: "" }},
      {{ speaker: "Andrew", url: "https://youtu.be/d50Kwga19ew", note: "" }},
      {{ speaker: "James", url: "https://youtu.be/OcU7z00IqE8", note: "" }},
      {{ speaker: "Daniel San", url: "https://youtu.be/RLxvQMW4Ls8", note: "" }},
      {{ speaker: "Daniel San", url: "https://youtu.be/vRl1hDDgbb4", note: "" }},
      {{ speaker: "Daniel San", url: "https://youtu.be/ZGpypBCPf-s", note: "" }}
    ]
  }},
  {{
    topic: "Baptism",
    subtopics: "",
    videos: [
      {{ speaker: "Josh", url: "https://youtu.be/2suNCLzDMrc", note: "" }},
      {{ speaker: "Mark", url: "https://youtu.be/LmrmVtrJjSI?si=ZpBG7veM3SQTQsX5", note: "" }},
      {{ speaker: "Matthew G", url: "https://youtu.be/LmrmVtrJjSI?si=ZpBG7veM3SQTQsX5", note: "Timestamp: 1:38:30 – 1:45:00" }},
      {{ speaker: "Matthew UK", url: "https://youtu.be/lKejL52chHU", note: "" }},
      {{ speaker: "Big Mike", url: "https://youtu.be/Wq6heGFbkyg", note: "" }}
    ]
  }},
  {{
    topic: "Peculiar People / Holy Nation",
    subtopics: "",
    videos: [
      {{ speaker: "Daniel San", url: "https://youtu.be/OCnZ4_vtE-8", note: "" }},
      {{ speaker: "Mark", url: "https://youtu.be/sZeb9PquqW0", note: "" }},
      {{ speaker: "Mark", url: "https://youtu.be/fGlmmFMSVng", note: "" }},
      {{ speaker: "Matthew UK", url: "https://youtu.be/P86w_rYF6ww", note: "" }},
      {{ speaker: "Andrew", url: "https://youtu.be/vlwT49Jxey4", note: "" }}
    ]
  }},
  {{
    topic: "The 10 Commandments",
    subtopics: "The 1st Commandment with Promise",
    videos: [
      {{ speaker: "Mark", url: "https://youtu.be/S0cc3Z2SBaE", note: "" }},
      {{ speaker: "Andrew", url: "https://youtu.be/DhCJ35WIMus", note: "" }},
      {{ speaker: "Andrew", url: "https://youtu.be/CzFwz_MsmDg", note: "" }}
    ]
  }},
  {{
    topic: "Receive the Holy Spirit",
    subtopics: "Lose the Spirit — Spirit of Error / Spirit of Fornication / Antichrist Spirit",
    videos: [
      {{ speaker: "Matthew UK", url: "https://youtu.be/gWfI9aBRREU", note: "" }},
      {{ speaker: "Andrew", url: "https://youtu.be/jNJxbOgovgY", note: "" }},
      {{ speaker: "Andrew", url: "https://youtu.be/eKPMgIeyPg8", note: "" }}
    ]
  }},
  {{
    topic: "Works of the Law / Letter of the Law / Law of Sin and Death",
    subtopics: "First Things Gentiles Should Do / Covenants of Promise — Ministration of Death, Written & Engraven in Stone — Twisting Paul's Words",
    videos: [
      {{ speaker: "Matthew UK", url: "https://youtu.be/jM5EMybEsjs", note: "" }},
      {{ speaker: "Antonio", url: "https://youtu.be/ikozBtaZYIo", note: "" }},
      {{ speaker: "Antonio", url: "https://youtu.be/3JQhgj51WSA", note: "" }},
      {{ speaker: "Mark", url: "https://www.youtube.com/live/khof_V5ysk8?si=ZQKv5h8NbSJgbxe0", note: "" }},
      {{ speaker: "Mark", url: "https://youtu.be/m5vHsxSRXF8", note: "" }},
      {{ speaker: "Mark", url: "https://youtu.be/lo2Lws6KiJY", note: "" }},
      {{ speaker: "Mark", url: "https://youtu.be/kMLPsNIkUCk", note: "" }},
      {{ speaker: "James", url: "https://youtu.be/2n1MqNLQOrU", note: "" }},
      {{ speaker: "Daniel San", url: "https://youtu.be/_I4CsjWkycE", note: "" }},
      {{ speaker: "Big Mike", url: "https://youtu.be/mfr85MybICw", note: "" }}
    ]
  }},
  {{
    topic: "Wicked Rulers / Government",
    subtopics: "",
    videos: [
      {{ speaker: "Mark", url: "https://youtu.be/IG7Hs98tSJU", note: "" }},
      {{ speaker: "Matthew UK", url: "https://youtu.be/Uiml4lHudg8", note: "" }},
      {{ speaker: "Daniel San", url: "https://youtu.be/O79FhPjLHzo", note: "" }},
      {{ speaker: "Andrew", url: "https://youtu.be/dYPDme9UfBs", note: "" }}
    ]
  }},
  {{
    topic: "Sabbath / Day Dawning",
    subtopics: "Lunar Sabbath — Evening Sabbath",
    videos: [
      {{ speaker: "Matthew UK", url: "https://youtu.be/HedmsivwhMQ", note: "" }},
      {{ speaker: "Matthew UK", url: "https://youtu.be/ZBoakb9gYno", note: "" }},
      {{ speaker: "Mark", url: "https://youtu.be/-1UrtkgW4ok", note: "" }},
      {{ speaker: "Mark", url: "https://youtu.be/GtavCYOgF04", note: "" }},
      {{ speaker: "Daniel San", url: "https://youtu.be/wm0W_2IE4xA", note: "" }},
      {{ speaker: "Daniel San", url: "https://youtu.be/W0nble5B-Us", note: "" }},
      {{ speaker: "Big Mike", url: "https://youtu.be/Whqe-YVvdh0", note: "" }},
      {{ speaker: "Big Mike", url: "https://youtu.be/_CKSv_B2Lys", note: "" }},
      {{ speaker: "Antonio", url: "https://youtu.be/KIc-ae3p-oc", note: "" }},
      {{ speaker: "Andrew", url: "https://youtu.be/b1zX74gXMZU", note: "" }},
      {{ speaker: "Andrew", url: "https://youtu.be/Gexz9TnHaH4", note: "" }},
      {{ speaker: "Andrew", url: "https://youtu.be/LFJWi2h5aKU", note: "" }},
      {{ speaker: "Josh", url: "https://youtu.be/bu6q-XDBRGI", note: "" }},
      {{ speaker: "Matthew G", url: "https://youtu.be/BUuiFg6Osdk", note: "" }},
      {{ speaker: "Matthew G", url: "https://youtu.be/DSvxhZozEtg", note: "" }}
    ]
  }},
  {{
    topic: "Horeb vs. Sinai",
    subtopics: "",
    videos: [
      {{ speaker: "Andrew & Matthew", url: "https://youtu.be/eN-D5dFZE4c", note: "" }},
      {{ speaker: "Big Mike", url: "https://youtu.be/msf3OEHVHj0", note: "" }},
      {{ speaker: "Andrew", url: "https://youtu.be/Ri6r58C99MQ", note: "" }},
      {{ speaker: "Andrew", url: "https://youtu.be/jNJxbOgovgY", note: "" }},
      {{ speaker: "Matthew UK", url: "https://youtu.be/jM5EMybEsjs", note: "" }},
      {{ speaker: "Matthew UK", url: "https://youtu.be/P86w_rYF6ww", note: "" }},
      {{ speaker: "Matthew UK", url: "https://youtu.be/pNEWG3jboWQ", note: "" }},
      {{ speaker: "Matthew UK", url: "https://youtu.be/o0-9uO-En04", note: "" }},
      {{ speaker: "Mark", url: "https://youtu.be/fB17F5M--CU", note: "" }},
      {{ speaker: "Mark", url: "https://youtu.be/VAPb0OhJfEQ", note: "" }}
    ]
  }},
  {{
    topic: "New Covenant vs. Old Covenant",
    subtopics: "",
    videos: [
      {{ speaker: "Josh", url: "https://youtu.be/WQJTcx1CwTI", note: "" }},
      {{ speaker: "Matthew", url: "https://youtu.be/CIyS2NfnmgQ", note: "" }},
      {{ speaker: "Andrew", url: "https://youtu.be/47eLP0wq6HU", note: "" }},
      {{ speaker: "Antonio", url: "https://youtu.be/kYBnXOnegKA", note: "" }}
    ]
  }},
  {{
    topic: "Leaven of Pharisees / Sadducees / Herod",
    subtopics: "God's Righteousness vs. Self-Righteousness",
    videos: [
      {{ speaker: "Mark", url: "https://youtu.be/nNye4O7Rmkk", note: "" }},
      {{ speaker: "Mark", url: "https://youtu.be/0o2kNunltQ0", note: "" }},
      {{ speaker: "Matthew UK", url: "https://www.youtube.com/live/pUd4wdWOqFs?si=iqdlU8aRm6No68g6", note: "" }},
      {{ speaker: "Andrew", url: "https://youtu.be/Tk5zsppkq9U", note: "" }},
      {{ speaker: "Bryce", url: "https://www.youtube.com/live/2yWT1rCPI_4?si=XmuCJVwcNNNindt4", note: "" }}
    ]
  }},
  {{
    topic: "Name of Baal",
    subtopics: "Satan Cast Out Satan / Lying Signs & Wonders",
    videos: [
      {{ speaker: "Matthew UK", url: "https://youtu.be/xhj_7KRrNw4", note: "" }},
      {{ speaker: "Mark", url: "https://youtu.be/-Xcw-LpxDcA", note: "" }},
      {{ speaker: "Mark", url: "https://youtu.be/KVDFTBrrJSA", note: "" }},
      {{ speaker: "Mark", url: "https://youtu.be/HCMIW48EpW0", note: "" }},
      {{ speaker: "Josh", url: "https://youtu.be/23GknA_Aezg", note: "" }},
      {{ speaker: "Bryce", url: "https://www.youtube.com/live/7zJjQMspcsU?si=U2rmqYS5IxzmemB_", note: "" }}
    ]
  }},
  {{
    topic: "Royal Law / Love Your Neighbor / Law of Liberty / Faith of Yeshua",
    subtopics: "Hide a Multitude of Sins — Cain vs. Abel's Offering — Judging the Cause of the Fatherless & Widows",
    videos: [
      {{ speaker: "Mark", url: "https://youtu.be/jHA8XxtVGDQ", note: "" }},
      {{ speaker: "Mark", url: "https://youtu.be/OkIXGrxSLvQ", note: "" }},
      {{ speaker: "Matthew UK", url: "https://youtu.be/My-xFDsPSIQ?si=OnVfeRi4hKBXZ8Bs", note: "" }},
      {{ speaker: "Andrew", url: "https://www.youtube.com/live/Lq56OPzkcP8?si=geqe10vPihiVLwqs", note: "" }},
      {{ speaker: "Big Mike", url: "https://youtu.be/e_GpgHJ-bps", note: "" }}
    ]
  }},
  {{
    topic: "Enter into the Work of the Prophets",
    subtopics: "",
    videos: [
      {{ speaker: "Antonio", url: "https://youtu.be/GknrDUIgMQI", note: "" }},
      {{ speaker: "Bryce", url: "https://www.youtube.com/live/p36HFyWzyaY?si=mA5xAfo94yiwo1jr", note: "" }}
    ]
  }},
  {{
    topic: "False Pastors / Shepherds",
    subtopics: "",
    videos: [
      {{ speaker: "Mark", url: "https://youtu.be/3z6fbzWXv54", note: "" }},
      {{ speaker: "Mark", url: "https://youtu.be/loPv3YuMx3w", note: "" }},
      {{ speaker: "Mark", url: "https://youtu.be/M2y7-HOAB9c", note: "" }},
      {{ speaker: "Mark", url: "https://youtu.be/jS-titOauyE", note: "" }},
      {{ speaker: "Mark", url: "https://youtu.be/m6oLwqUc0eU", note: "" }},
      {{ speaker: "Matthew UK", url: "https://youtu.be/Jq2mm8HspEY", note: "" }}
    ]
  }},
  {{
    topic: "Grace / Salt",
    subtopics: "",
    videos: [
      {{ speaker: "Josh", url: "https://youtu.be/711frZ69RzU", note: "" }},
      {{ speaker: "Matthew UK", url: "https://youtu.be/gF7oLF3JNrc", note: "" }},
      {{ speaker: "Bryce", url: "https://www.youtube.com/live/uzJq-3vNZn0?si=6qT_4x84m0HLoScf", note: "" }},
      {{ speaker: "Mark", url: "https://youtu.be/3un8hdDCyrU", note: "" }},
      {{ speaker: "Mark", url: "https://youtu.be/mg21LTVezVM", note: "" }}
    ]
  }},
  {{
    topic: "Blasphemy of the Holy Spirit",
    subtopics: "",
    videos: [
      {{ speaker: "Mark", url: "https://youtu.be/AATiH_otp6c", note: "" }},
      {{ speaker: "Mark", url: "https://youtu.be/s6pYSVstp5U", note: "" }},
      {{ speaker: "Matthew UK", url: "https://youtu.be/AhwoVfKphcw", note: "" }}
    ]
  }},
  {{
    topic: "6th Seal / Great Tribulation / The Seals / \u201cThe Rapture\u201d",
    subtopics: "Revelation 12 Sign",
    videos: [
      {{ speaker: "Matthew UK", url: "https://youtu.be/ULUuWcmOhFk", note: "" }},
      {{ speaker: "Mark", url: "https://youtu.be/Tsi5l-L-MIU", note: "" }},
      {{ speaker: "Mark", url: "https://youtu.be/W4tTVfaBgxM", note: "" }},
      {{ speaker: "Mark", url: "https://www.youtube.com/live/JSbezj6Y4rg?si=vDwcdpZaMac8IZ-r", note: "" }}
    ]
  }},
  {{
    topic: "Antichrist / Sons of Perdition",
    subtopics: "Abomination of Desolation",
    videos: [
      {{ speaker: "Mark", url: "https://www.youtube.com/live/yiAT6DBIeDM?si=7kfEtdzprtF1ou27", note: "" }},
      {{ speaker: "Mark", url: "https://youtu.be/m5vHsxSRXF8", note: "" }},
      {{ speaker: "Matthew UK", url: "https://www.youtube.com/live/NNZDuAMSzQQ?si=NDX7AUY5uuglUK95", note: "" }},
      {{ speaker: "Matthew UK", url: "https://www.youtube.com/live/botRR5Aynms?si=c82wr2LutFsXfn_T", note: "" }}
    ]
  }},
  {{
    topic: "Mercy not Sacrifice",
    subtopics: "",
    videos: [
      {{ speaker: "Mark", url: "https://youtu.be/GUlb3FP1ShM?si=9AiNfuKOwAnfz2dL", note: "" }},
      {{ speaker: "Mark", url: "https://youtu.be/ahOQmbKILjM?si=DZa31JBL_ldDbj1P", note: "" }},
      {{ speaker: "Andrew", url: "https://youtu.be/EELdTFhjvE0?si=z2SANU_WxKQ3Kfe8", note: "" }},
      {{ speaker: "Bryce", url: "https://www.youtube.com/live/Fd9IY6LghZA?si=mmmJM6K3QxSk5JSQ", note: "" }}
    ]
  }},
  {{
    topic: "Ephraim",
    subtopics: "They Are Rich / Rich Young Ruler / The Church at Laodicea — U.S.A.",
    videos: [
      {{ speaker: "Andrew", url: "https://www.youtube.com/live/-cyj23Vnz38?si=wMDyhiR0nDwyQ9BT", note: "" }},
      {{ speaker: "Big Mike", url: "https://youtu.be/oZ23Ce7yAjM", note: "" }},
      {{ speaker: "Matthew UK", url: "https://www.youtube.com/live/JikYxqy89Ww?si=RU6mKrd9RG8zJbBt", note: "" }},
      {{ speaker: "Matthew UK", url: "https://youtu.be/L8Lzc7_1Sw8", note: "" }},
      {{ speaker: "Matthew UK", url: "https://youtu.be/hWTtw_dlQfs?si=F9rMbPxQM00P7wpu", note: "" }},
      {{ speaker: "Mark", url: "https://youtu.be/2IBYi2PcH88", note: "" }}
    ]
  }},
  {{
    topic: "Drunkard / Glutton",
    subtopics: "Publicans & Harlots Enter Kingdom First",
    videos: [
      {{ speaker: "Matthew UK", url: "https://youtu.be/e9JLe4YicSU", note: "" }},
      {{ speaker: "Mark", url: "https://www.youtube.com/live/yo2CjHjM_f4?si=-sQtdqohEJ_XNtof", note: "" }}
    ]
  }},
  {{
    topic: "Babylon & Chaldeans",
    subtopics: "Babylon is Fallen — The Elect in Babylon",
    videos: [
      {{ speaker: "Mark", url: "https://www.youtube.com/live/ivF1A_aQMDY?si=hCslpnA9ZC_SGSTU", note: "" }},
      {{ speaker: "Mark", url: "https://youtu.be/1RmN4aAvnPs?si=gwE95wroHYCr3Qyb", note: "" }},
      {{ speaker: "Mark", url: "https://www.youtube.com/live/W5NRQ2BDNM4?si=wqjmWRC1Za_S1Jqn", note: "" }},
      {{ speaker: "Andrew", url: "https://www.youtube.com/live/cQIpCoXxiRo?si=l73Wvw7H3y3hGQMe", note: "" }},
      {{ speaker: "Bryce", url: "https://www.youtube.com/live/feGW4m--QGQ?si=Tqp5gRoe8bmgJrX5", note: "" }}
    ]
  }},
  {{
    topic: "Who is Israel / Lost 10 Tribes",
    subtopics: "Bill of Divorce / Remarriage — Ye Are Not My People, Ye Are My People — Woman at the Well — Why the Ezekiel Temple Wasn't Built — The Apostasy of the Church / 2 Timothy 3 & 4 — Septuagint & Why It Was Written — Judah Already Taken",
    videos: [
      {{ speaker: "Matthew US", url: "https://youtu.be/RSXNt75QFfA?si=EK04kWpRCL3hKEL1", note: "" }},
      {{ speaker: "Andrew", url: "https://youtu.be/qvYQ3yW5d5c", note: "" }},
      {{ speaker: "Andrew", url: "https://www.youtube.com/live/2FhNXPoJgZE?si=8vE-OGZfmML2zcYT", note: "" }},
      {{ speaker: "Mark", url: "https://www.youtube.com/live/lfi9TpmYf8M?si=5tEKV-IyrNCI-4Od", note: "" }},
      {{ speaker: "Mark", url: "https://youtu.be/EJf4LHgHJ4I?si=j42_2Hd6ktEvTfij", note: "" }},
      {{ speaker: "Mark", url: "https://youtu.be/nZ9jApQOpmA", note: "" }},
      {{ speaker: "Mark", url: "https://www.youtube.com/live/LBEY-l0zp3I?si=aqmhd5ugv7-N5P3G", note: "" }},
      {{ speaker: "Matthew UK", url: "https://www.youtube.com/live/-WGkykmNHio?si=E8PoXMGYof2RV1w3", note: "" }}
    ]
  }},
  {{
    topic: "Jacob / Manchild / Bride / 144k / Many Sons / Nation Formed at Once",
    subtopics: "Rod of Iron — The New Song of Moses — The Church at Philadelphia",
    videos: [
      {{ speaker: "Andrew", url: "https://www.youtube.com/live/H1bd-TMB_no?si=hW3Tz1XgP6lAPx4I", note: "" }},
      {{ speaker: "Andrew", url: "https://www.youtube.com/live/CeqgSkCHTaQ?si=G_GgRl4kZLCDIge2", note: "" }},
      {{ speaker: "Mark", url: "https://www.youtube.com/live/vkU7vk4yOLA?si=gCqrK9e820Ocylkz", note: "" }},
      {{ speaker: "Mark", url: "https://www.youtube.com/live/_sXsoV5M6XQ?si=9WXL2PPs_ThTfJlh", note: "" }},
      {{ speaker: "Mark", url: "https://www.youtube.com/live/j2pc_6d_xUw?si=HzmPAmSzELq6hGYn", note: "" }},
      {{ speaker: "Mark", url: "https://www.youtube.com/live/JSbezj6Y4rg?si=vDwcdpZaMac8IZ-r", note: "" }},
      {{ speaker: "Mark", url: "https://www.youtube.com/live/JjtEnFuKbEc?si=ajJJjBSZDvORVnZu", note: "" }},
      {{ speaker: "Matthew", url: "https://www.youtube.com/live/ebIy5WmJirQ?si=8MmHx8RXGDMOKrui", note: "" }},
      {{ speaker: "Bryce", url: "https://www.youtube.com/live/T8NNZj5du_4?si=lsC54SlfsAB6gLYe", note: "" }},
      {{ speaker: "Bryce", url: "https://www.youtube.com/live/CXS51EdSbhk?si=Pq1OgKEW4sMzBlL1", note: "" }}
    ]
  }},
  {{
    topic: "2nd Exodus",
    subtopics: "",
    videos: [
      {{ speaker: "Matthew UK", url: "https://youtu.be/0vpIEm1dXBo?si=b9OHflgusBJj9lCL", note: "" }},
      {{ speaker: "Mark", url: "https://www.youtube.com/live/-TaikvgkRwU?si=pEt_xypanLsIvqz3", note: "" }}
    ]
  }},
  {{
    topic: "2 Houses / Sticks",
    subtopics: "",
    videos: [
      {{ speaker: "Mark", url: "https://youtu.be/KxPF9BL2hKQ?si=MXtvMKDfJ63DMIfi", note: "" }},
      {{ speaker: "Bryce", url: "https://www.youtube.com/live/ELNGLZb2qko?si=SVhdj90tXTN5dr1K", note: "" }}
    ]
  }},
  {{
    topic: "Rules to Rebuke",
    subtopics: "",
    videos: [
      {{ speaker: "Andrew", url: "https://www.youtube.com/live/c6D5RmHlkfk?si=hAy1xg2EauO9gDcv", note: "" }},
      {{ speaker: "Mark", url: "https://www.youtube.com/live/6oswHsZ1gaU?si=gmaLeJCTWjz0XMdZ", note: "" }}
    ]
  }},
  {{
    topic: "Jezebel & Ahab",
    subtopics: "Rules for Women — Punishment to Women",
    videos: [
      {{ speaker: "Mark", url: "https://www.youtube.com/live/tpHqNqiybfg?si=HsxT7Zw6xK23ryKS", note: "" }},
      {{ speaker: "Mark", url: "https://www.youtube.com/live/Ue1Hh6hUgng?si=YjR6YfW3FKNqM_FI", note: "" }}
    ]
  }},
  {{
    topic: "Watchmen",
    subtopics: "Watchman of Ephraim",
    videos: [
      {{ speaker: "Josh", url: "https://youtu.be/A0UNgmwqZtI", note: "" }},
      {{ speaker: "James", url: "https://www.youtube.com/live/3zS_HzrTSgM?si=YRRRi8o8wANeHKu7", note: "" }}
    ]
  }},
  {{
    topic: "Key of David",
    subtopics: "",
    videos: [
      {{ speaker: "Matthew UK", url: "https://youtu.be/2I0CtHIiQX8?si=vyVIylzG9uqJAX3i", note: "" }},
      {{ speaker: "Mark", url: "https://youtu.be/0Yq4NBXtp9s?si=xX8iIKG0I0qfeQZm", note: "" }},
      {{ speaker: "Andrew", url: "https://www.youtube.com/live/GdCEwmRgULI?si=Uj6llretGlBltT8W", note: "" }}
    ]
  }},
  {{
    topic: "Ethiopian Eunuch / Hidden Manna",
    subtopics: "",
    videos: [
      {{ speaker: "Matthew UK", url: "https://youtu.be/ZfcnSUCHJoE?si=Rq01m7rKmEo-ACOd", note: "" }},
      {{ speaker: "Mark", url: "https://youtu.be/2IBYi2PcH88", note: "" }}
    ]
  }},
  {{
    topic: "The Olivet Discourse",
    subtopics: "",
    videos: [
      {{ speaker: "Mark", url: "https://youtu.be/E6_ZE3ISRCE?si=Yxx7YPZjz3b09Ov3", note: "" }},
      {{ speaker: "Mark", url: "https://www.youtube.com/live/H_4GaJ3smhU?si=W-x0SF1jIaOZXBIp", note: "" }},
      {{ speaker: "Mark", url: "https://www.youtube.com/live/WKhsANcnllw?si=Bk8xXlAiOcuq1f0s", note: "" }}
    ]
  }},
  {{
    topic: "Evil Servants / 7 Worse Spirits / Esau",
    subtopics: "Do This & You'll Never Fall — Wise in Their Own Conceits — Presumptuous Sin — They Make Their Robes White / Death Swallowed in Victory / Ephraim Goes Into the Pit",
    videos: [
      {{ speaker: "Andrew", url: "https://youtu.be/eKPMgIeyPg8?si=QpeV0njk7_GYiQct", note: "" }},
      {{ speaker: "Mark", url: "https://youtu.be/Baf7fU-xh5k", note: "" }},
      {{ speaker: "Mark", url: "https://youtu.be/axPCGtd86Lk", note: "" }},
      {{ speaker: "Big Mike", url: "https://youtu.be/mWqVtHuf2lA?si=-Yb0UNKF9YgWwR_g", note: "" }}
    ]
  }},
  {{
    topic: "Dumb Dog Watchmen",
    subtopics: "",
    videos: [
      {{ speaker: "Mark", url: "https://youtu.be/Jaw3AcUsQoU?si=gqhvriks9OFN5XwL", note: "" }},
      {{ speaker: "Bryce", url: "https://www.youtube.com/live/0f4Y5abZw2Q?si=BOu5uTzDpXQP3Rhy", note: "" }}
    ]
  }},
  {{
    topic: "Unjust Steward",
    subtopics: "",
    videos: [
      {{ speaker: "Mark", url: "https://youtu.be/qz2sK7vUzW0", note: "" }},
      {{ speaker: "Matthew UK", url: "https://youtu.be/95vfyuvMBjU?si=t9i5JjilrJcEZmNV", note: "" }},
      {{ speaker: "Andrew", url: "https://youtu.be/ehVvJpbiE10?si=XE4WDQI13-Iv2CRe", note: "" }}
    ]
  }},
  {{
    topic: "All the Parables",
    subtopics: "What It Means to be Converted",
    videos: [
      {{ speaker: "Bryce", url: "https://www.youtube.com/live/1kMrGFkK1V0?si=V7A5wXM0Se3nVxbF", note: "" }}
    ]
  }},
  {{
    topic: "Refreshing / Good Tidings / Gospel",
    subtopics: "Promise to Abraham — Death, Burial, Resurrection (DBR) Gospel — When Will Yeshua Return — The Melchizedek Scroll (11Q13)",
    videos: [
      {{ speaker: "Mark", url: "https://www.youtube.com/live/GnlNydyMZs8?si=CFUWDenapEf3ZIzo", note: "" }},
      {{ speaker: "Mark", url: "https://www.youtube.com/live/qdSKtxhCPmY?si=ZdA0ONFEfI8DY01S", note: "" }},
      {{ speaker: "Mark", url: "https://youtu.be/W7JF4bezh_g?si=qCayvlgnlEnd2lvu", note: "" }},
      {{ speaker: "Andrew", url: "https://www.youtube.com/live/wHUya4jvBKE?si=UnGFqHXgnhQ4ZI5k", note: "" }},
      {{ speaker: "Andrew", url: "https://youtu.be/eN-D5dFZE4c?si=fmPojf4bCfp57waf", note: "" }},
      {{ speaker: "Andrew", url: "https://youtu.be/08OB1sZA-w8?si=T3nU9bZ6nzFHh4xb", note: "" }},
      {{ speaker: "Andrew", url: "https://youtu.be/2vzC10UGpBA?si=YZWO-CfkKHy5811t", note: "" }},
      {{ speaker: "Bryce", url: "https://www.youtube.com/live/18r2GkwJI90?si=m9spiAsNVcRMFfVR", note: "" }}
    ]
  }},
  {{
    topic: "Sermon on the Mount / Beatitudes",
    subtopics: "The Blessed / The Beloved / Who Yeshua Prayed For",
    videos: [
      {{ speaker: "Mark", url: "https://www.youtube.com/live/ao9IKdglmg0?si=_FGXS-JJv6bUETiX", note: "" }},
      {{ speaker: "Mark", url: "https://youtu.be/C-D0n7vBCwI?si=U1P5zY3MD4LiBUGs", note: "" }},
      {{ speaker: "Matthew UK", url: "https://youtu.be/a-TdqS9Jr1M?si=wEM3q4Q6kZlDYgCP", note: "" }}
    ]
  }},
  {{
    topic: "Fruits of the Spirit",
    subtopics: "",
    videos: [
      {{ speaker: "Andrew", url: "https://youtu.be/smeRoNSmneI?si=HH4s0wm8pfC4anPu", note: "" }},
      {{ speaker: "Antonio", url: "https://youtu.be/AocjjC-s9qY", note: "" }}
    ]
  }},
  {{
    topic: "Foolish Things That Confound the Wise",
    subtopics: "",
    videos: [
      {{ speaker: "Mark", url: "https://youtu.be/VlyB-zXGN5A", note: "" }}
    ]
  }},
  {{
    topic: "Jerusalem's Destruction",
    subtopics: "New Heavens & New Earth — Earth Void & Without Form — What God Did In Shiloh / Red Heifer Sacrifice",
    videos: [
      {{ speaker: "Bryce", url: "https://www.youtube.com/live/cAwayrdiI0s?si=BNArDSpgzMU6TDpn", note: "" }},
      {{ speaker: "Antonio", url: "https://www.youtube.com/live/GY8HfZYaNRY?si=KEBFD4fTWvl1VYae", note: "" }},
      {{ speaker: "Matthew UK", url: "https://youtu.be/9p0kCui31gQ?si=bXWKrPsDIKTUXtlH", note: "" }},
      {{ speaker: "Mark", url: "https://www.youtube.com/live/8pjCjRREJBE?si=mFiepllsAKyq11gp", note: "" }},
      {{ speaker: "Mark", url: "https://www.youtube.com/live/7mBnCdYSluI?si=jlhICIyGNBvrW3LQ", note: "" }},
      {{ speaker: "Mark", url: "https://www.youtube.com/live/80qPXMXUzWY?si=CyoSSGD6rfP8_eSY", note: "" }}
    ]
  }},
  {{
    topic: "Easter",
    subtopics: "3 Days & 3 Nights — The False Sunday Resurrection Tradition",
    videos: [
      {{ speaker: "Matthew UK", url: "https://youtu.be/hN6cgBNR_ZE?si=zg6hhA3XvGFRoAw0", note: "" }},
      {{ speaker: "Mark", url: "https://youtu.be/A6CjL25OPn8?si=NmKk8j0R77OAIuDt", note: "" }}
    ]
  }},
  {{
    topic: "Gainsaying of Korah/Core",
    subtopics: "",
    videos: [
      {{ speaker: "Andrew", url: "https://www.youtube.com/live/iPsTpYKVjeM?si=t-yY9oXHzQ2GtL8j", note: "" }}
    ]
  }},
  {{
    topic: "Whitestone",
    subtopics: "",
    videos: [
      {{ speaker: "Mark", url: "https://youtu.be/JYDSdVHRdOc", note: "" }}
    ]
  }},
  {{
    topic: "The Lord's Prayer",
    subtopics: "",
    videos: [
      {{ speaker: "Mark", url: "https://www.youtube.com/live/I9BVLQM-7-k?si=EAdG6Th5Fp_fA27f", note: "" }}
    ]
  }},
  {{
    topic: "Lying Pen of the Scribes",
    subtopics: "Strong's Concordance / Gentle",
    videos: [
      {{ speaker: "Mark", url: "https://www.youtube.com/live/_C8xvhl34A8?si=-mMNSclcRx6JGE-E", note: "" }}
    ]
  }},
  {{
    topic: "Thief on the Cross",
    subtopics: "",
    videos: [
      {{ speaker: "Big Mike", url: "https://youtu.be/81nvzfmQPyM", note: "" }},
      {{ speaker: "James", url: "https://youtu.be/7uQS-zZmN_U", note: "Timestamp: 44:00 – 47:00" }}
    ]
  }},
  {{
    topic: "The Feasts",
    subtopics: "Ephraim Envies Judah",
    videos: [
      {{ speaker: "Bryce", url: "https://www.youtube.com/live/OJZxM6Oxlho?si=gIw0iX4qMNQApDee", note: "" }}
    ]
  }},
  {{
    topic: "Removing the Bound",
    subtopics: "",
    videos: [
      {{ speaker: "Mark", url: "https://youtu.be/Juivyqu-teE", note: "" }},
      {{ speaker: "Mark", url: "https://www.youtube.com/live/8GTqNP0Oqrk?si=fQcIj8_xv5bBELMD", note: "" }}
    ]
  }},
  {{
    topic: "Enemies of Your Own Household",
    subtopics: "",
    videos: [
      {{ speaker: "Andrew", url: "https://www.youtube.com/live/aP6-ZvkQPIg?si=7bWwC6ajIbPuM5qr", note: "" }},
      {{ speaker: "Mark", url: "https://youtu.be/-jbX0l8oIGY", note: "" }},
      {{ speaker: "Bryce", url: "https://www.youtube.com/live/lnt3jCTDU9M?si=jcAQzMJB4XUfRain", note: "" }}
    ]
  }},
  {{
    topic: "Bema Seat Judgment / 7 Churches",
    subtopics: "",
    videos: [
      {{ speaker: "Andrew", url: "https://www.youtube.com/live/KSwMh-jvyCI?si=jJ1KNkU6w70DMFc_", note: "" }},
      {{ speaker: "Mark", url: "https://youtu.be/dCWnZnR-d08?si=Gv65bKKvnPkvFtJv", note: "" }}
    ]
  }},
  {{
    topic: "Yeshua is not God",
    subtopics: "",
    videos: [
      {{ speaker: "Antonio", url: "https://www.youtube.com/live/xxDMmRDFr9I?si=y4gEgtR-IeEF6OVQ", note: "" }}
    ]
  }},
  {{
    topic: "Yeshua Writing in the Earth Twice",
    subtopics: "",
    videos: [
      {{ speaker: "Andrew", url: "https://youtu.be/IYiVxq9Tjqk", note: "" }}
    ]
  }},
  {{
    topic: "Corner Stone / Rock of Offence / Stumbling Stone",
    subtopics: "",
    videos: [
      {{ speaker: "Daniel Morgan", url: "https://youtu.be/oCQw4cAtFRI", note: "" }},
      {{ speaker: "Matthew UK", url: "https://youtu.be/1L-Ipk8nnEs?si=cJTfl5QKK6G3UU3z", note: "" }},
      {{ speaker: "Matthew UK", url: "https://youtu.be/hT2HMst9IiA?si=NKJPyfeDcseRzOd1", note: "" }},
      {{ speaker: "Andrew", url: "https://www.youtube.com/live/vlwT49Jxey4?si=CKdNF9jpU2B3HVeA", note: "" }}
    ]
  }},
  {{
    topic: "Be Perfect",
    subtopics: "",
    videos: [
      {{ speaker: "Matthew UK", url: "https://youtu.be/KgspnVZKMEU?si=hHPl1HdhzRkjXvJx", note: "" }}
    ]
  }},
  {{
    topic: "Paleo Hebrew / Word Police",
    subtopics: "",
    videos: [
      {{ speaker: "Mark", url: "https://youtu.be/Jaw3AcUsQoU?si=36UBNHantqaJSKVo", note: "" }}
    ]
  }},
  {{
    topic: "1 Thessalonians 4 vs. 1 Thessalonians 5",
    subtopics: "",
    videos: [
      {{ speaker: "Andrew", url: "https://www.youtube.com/live/_6Lza75HYoM?si=M-cequhtQfQvFtPb", note: "" }}
    ]
  }},
  {{
    topic: "White / Black Hebrew Israelites",
    subtopics: "",
    videos: [
      {{ speaker: "Mark", url: "https://youtu.be/K_LSMgQLHaw?si=qLM-TuQD_c-qL7_M", note: "" }}
    ]
  }},
  {{
    topic: "Speaking in Tongues vs. Prophesying",
    subtopics: "",
    videos: [
      {{ speaker: "Mark", url: "https://www.youtube.com/live/e79W8aZ1qBE?si=OAiG1KSkglkUshQ4", note: "" }},
      {{ speaker: "Antonio", url: "https://youtu.be/aOfjIcOFcXQ", note: "" }}
    ]
  }}
];

// Populate topic filter dropdown
(function() {{
  const sel = document.getElementById('videos-topic-filter');
  VIDEO_DATA.forEach(g => {{
    const opt = document.createElement('option');
    opt.value = g.topic;
    opt.textContent = g.topic;
    sel.appendChild(opt);
  }});
}})();

function getYouTubeId(url) {{
  try {{
    const u = new URL(url);
    if (u.hostname === 'youtu.be') return u.pathname.slice(1).split('?')[0];
    if (u.hostname.includes('youtube.com')) {{
      const v = u.searchParams.get('v');
      if (v) return v;
      // live URLs: /live/ID
      const liveParts = u.pathname.match(/[/]live[/]([^/?]+)/);
      if (liveParts) return liveParts[1];
    }}
  }} catch(e) {{}}
  return null;
}};

function getPlatformLabel(url) {{
  if (url.includes('tiktok.com')) return 'TikTok';
  if (url.includes('youtube.com') || url.includes('youtu.be')) return 'YouTube';
  return 'External Link';
}};

function renderVideoCard(v) {{
  const ytId = getYouTubeId(v.url);
  const platform = getPlatformLabel(v.url);
  const thumbHtml = ytId
    ? `<div class="video-thumb">
        <img src="https://img.youtube.com/vi/${{ytId}}/mqdefault.jpg" alt="" loading="lazy">
        <div class="play-icon"><svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg></div>
       </div>`
    : `<div class="video-thumb" style="background:var(--surface2);display:flex;align-items:center;justify-content:center;">
        <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="color:var(--muted)"><path d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"/><path d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
       </div>`;
  const noteHtml = v.note ? `<div style="color:var(--muted);font-size:0.72rem;margin-top:3px;font-style:italic">${{escH(v.note)}}</div>` : '';
  return `<a class="video-card" href="${{escH(v.url)}}" target="_blank" rel="noopener">
    ${{thumbHtml}}
    <div class="video-card-body">
      <div class="video-speaker">${{escH(v.speaker)}}</div>
      <div class="video-link">${{escH(v.url.replace(/^https?:[/][/]/, ''))}}</div>
      ${{noteHtml}}
      <div class="video-platform">${{platform}}</div>
    </div>
  </a>`;
}};

function filterVideos() {{
  const q = document.getElementById('videos-search').value.toLowerCase();
  const topicFilter = document.getElementById('videos-topic-filter').value;
  const container = document.getElementById('video-topics-list');
  container.innerHTML = '';
  let totalVideos = 0;

  const filtered = VIDEO_DATA.filter(g => {{
    if (topicFilter && g.topic !== topicFilter) return false;
    if (!q) return true;
    return g.topic.toLowerCase().includes(q)
      || g.subtopics.toLowerCase().includes(q)
      || g.videos.some(v => v.speaker.toLowerCase().includes(q) || v.note.toLowerCase().includes(q));
  }});

  filtered.forEach(g => {{
    const vids = q
      ? g.videos.filter(v => v.speaker.toLowerCase().includes(q) || v.note.toLowerCase().includes(q) || g.topic.toLowerCase().includes(q) || g.subtopics.toLowerCase().includes(q))
      : g.videos;

    if (vids.length === 0 && !g.topic.toLowerCase().includes(q) && !g.subtopics.toLowerCase().includes(q)) return;

    totalVideos += vids.length;
    const group = document.createElement('div');
    group.className = 'video-topic-group';
    const subtopicsHtml = g.subtopics ? `<div class="subtopics">${{escH(g.subtopics)}}</div>` : '';
    group.innerHTML = `
      <div class="video-topic-header">
        <h3>${{escH(g.topic)}}</h3>
        ${{subtopicsHtml}}
      </div>
      <div class="video-cards">${{vids.length > 0 ? vids.map(renderVideoCard).join('') : '<div class="no-videos-msg" style="padding:12px 16px">No videos yet for this topic.</div>'}}</div>`;
    container.appendChild(group);
  }});

  if (filtered.length === 0) {{
    container.innerHTML = '<div class="no-videos-msg">No topics match your search.</div>';
  }}
  document.getElementById('video-count').textContent = totalVideos + ' video' + (totalVideos !== 1 ? 's' : '');
}};

// Init videos tab
filterVideos();

function showPersonResult(name) {{
  const person = PEOPLE.find(p => p.name === name);
  if (!person) return;
  const yes = [], sorta = [], no = [];
  person.responses.forEach((r, i) => {{
    if (r === 'Yes') yes.push(TOPICS[i]);
    else if (r === 'Sorta') sorta.push(TOPICS[i]);
    else no.push(TOPICS[i]);
  }});
  const maxRows = Math.max(yes.length, sorta.length, no.length);
  let rows = `
    <div class="col-head yes">Knows (${{yes.length}})</div>
    <div class="col-head sorta">Sorta knows (${{sorta.length}})</div>
    <div class="col-head no">Doesn&apos;t know (${{no.length}})</div>`;
  for (let i = 0; i < maxRows; i++) {{
    rows += `<div class="col-body">${{yes[i] ? escH(yes[i]) : ''}}</div>`;
    rows += `<div class="col-body">${{sorta[i] ? escH(sorta[i]) : ''}}</div>`;
    rows += `<div class="col-body">${{no[i] ? escH(no[i]) : ''}}</div>`;
  }}
  document.getElementById('person-result-inner').innerHTML = rows;
  document.getElementById('person-result').classList.add('visible');
}}

// ── Buddy Finder ──────────────────────────────────────────────────────────

// Extend ddState for buddy picker
ddState['buddy'] = {{ items: PEOPLE.map(p => p.name), selected: null, focused: -1, filtered: null }};

// Patch selectDD to handle the buddy type (original only handles topic/person)
const _selectDDOrig = selectDD;
function selectDD(type, value) {{
  ddState[type].selected = value;
  document.getElementById(type + '-input').value = value;
  const clearBtn = document.getElementById(type + '-clear');
  if (clearBtn) {{ clearBtn.classList.add('visible'); clearBtn.style.display = ''; }}
  closeDD(type);
  if (type === 'topic') showTopicResult(value);
  else if (type === 'person') showPersonResult(value);
  else if (type === 'buddy') showBuddyResults(value);
}}

function clearBuddy() {{
  ddState['buddy'].selected = null;
  ddState['buddy'].filtered = null;
  document.getElementById('buddy-input').value = '';
  document.getElementById('buddy-clear').style.display = 'none';
  document.getElementById('buddy-results').style.display = 'none';
  document.getElementById('buddy-empty-state').style.display = 'none';
}}

document.addEventListener('click', e => {{
  const bw = document.getElementById('buddy-wrap');
  if (bw && !bw.contains(e.target)) closeDD('buddy');
}});

// ── Scoring ───────────────────────────────────────────────────────────────
// "Teachable" = A knows (Yes/Sorta), B doesn't (No/Sorta with A=Yes).
// Specifically:
//   A=Yes,   B=No    → A can fully teach B   (counted in aToBTopics)
//   A=Yes,   B=Sorta → A can clarify for B   (counted in aToBTopics)
//   A=Sorta, B=No    → A can partially teach B (counted in aToBTopics)
//   (mirror for B→A direction)
// Ranking key: min(aToBCount, bToACount) — both directions must be strong.

function computePairScore(personA, personB) {{
  const n = Math.min(personA.responses.length, personB.responses.length, TOPICS.length);
  const aToBTopics = [], bToATopics = [];
  let sharedGaps = 0, sharedStrength = 0;

  for (let i = 0; i < n; i++) {{
    const a = personA.responses[i] || 'No';
    const b = personB.responses[i] || 'No';
    const t = TOPICS[i];

    // A can teach B: A knows more than B
    const aVal = a === 'Yes' ? 2 : a === 'Sorta' ? 1 : 0;
    const bVal = b === 'Yes' ? 2 : b === 'Sorta' ? 1 : 0;

    if (aVal > bVal) aToBTopics.push(t);
    if (bVal > aVal) bToATopics.push(t);
    if (aVal === 0 && bVal === 0) sharedGaps++;       // both No
    if (aVal === 1 && bVal === 1) sharedGaps++;       // both Sorta
    if (aVal === 2 && bVal === 2) sharedStrength++;   // both Yes
  }}

  // Rank by the minimum of both directions — rewards true mutual exchange
  const mutual = Math.min(aToBTopics.length, bToATopics.length);
  const total = aToBTopics.length + bToATopics.length;
  // Score: weighted so mutual exchange matters most, total exchange second.
  // Realistic best case: topics split 50/50 → mutual=n/2, total=n → rawScore = n/2*2 + n = 2n
  // Normalize against 2n so a perfect 50/50 split = 100.
  const rawScore = mutual * 2 + total;
  const maxPossible = n * 2; // realistic best case
  const score = Math.max(0, Math.min(100, Math.round(rawScore / maxPossible * 100)));

  return {{
    score,
    mutual,
    aToBCount: aToBTopics.length,
    bToACount: bToATopics.length,
    sharedGaps,
    sharedStrength,
    aToBTopics,
    bToATopics,
  }};
}}

function computeTrioScore(personA, personB, personC) {{
  const n = Math.min(personA.responses.length, personB.responses.length, personC.responses.length, TOPICS.length);
  let coverage = 0, teachable = 0, deadZones = 0;
  for (let i = 0; i < n; i++) {{
    const vals = [
      personA.responses[i] || 'No',
      personB.responses[i] || 'No',
      personC.responses[i] || 'No'
    ].map(r => r === 'Yes' ? 2 : r === 'Sorta' ? 1 : 0);
    const maxVal = Math.max(...vals);
    const minVal = Math.min(...vals);
    if (maxVal >= 1) coverage++;
    if (maxVal > minVal) teachable++;
    if (maxVal === 0) deadZones++;
  }}
  const score = Math.max(0, Math.min(100, Math.round(
    (coverage / n) * 60 + (teachable / n) * 40 - (deadZones / n) * 20
  )));
  return {{ score, coverage, teachable, deadZones, total: n }};
}}

// ── Ranking ───────────────────────────────────────────────────────────────

function rankBuddies(selectedName) {{
  const personA = PEOPLE.find(p => p.name === selectedName);
  if (!personA) return null;
  const others = PEOPLE.filter(p => p.name !== selectedName);
  if (others.length < 1) return null;

  const pairResults = others.map(personB => ({{ buddy: personB, ...computePairScore(personA, personB) }}));
  // Sort by mutual first (both directions), then total, then score
  pairResults.sort((a, b) => b.mutual - a.mutual || (b.aToBCount + b.bToACount) - (a.aToBCount + a.bToACount) || b.score - a.score);
  const top4Pairs = pairResults.slice(0, 4);

  // For each top-4 buddy, find the best 3rd person
  const trioResults = [];
  top4Pairs.forEach(pair => {{
    let bestTrio = null, bestScore = -1;
    PEOPLE.forEach(personC => {{
      if (personC.name === selectedName || personC.name === pair.buddy.name) return;
      const ts = computeTrioScore(personA, pair.buddy, personC);
      if (ts.score > bestScore) {{ bestScore = ts.score; bestTrio = {{ third: personC, ...ts }}; }}
    }});
    if (bestTrio) trioResults.push({{ buddyA: pair.buddy, buddyB: bestTrio.third, ...bestTrio }});
  }});
  trioResults.sort((a, b) => b.score - a.score);

  return {{ selectedName, top4Pairs, top3Trios: trioResults.slice(0, 3) }};
}}

// ── Detail modal ──────────────────────────────────────────────────────────

let _buddyDetailData = null;

function openBuddyDetail(idx) {{
  if (!_buddyDetailData) return;
  const p = _buddyDetailData.pairs[idx];
  const sel = _buddyDetailData.selectedName;
  const modal = document.getElementById('buddy-modal');
  const overlay = document.getElementById('buddy-modal-overlay');

  const rowsAtoB = p.aToBTopics.map(t => `<div class="buddy-detail-row teach">${{escH(t)}}</div>`).join('') || '<div class="buddy-detail-row" style="color:var(--muted);font-style:italic">None</div>';
  const rowsBtoA = p.bToATopics.map(t => `<div class="buddy-detail-row learn">${{escH(t)}}</div>`).join('') || '<div class="buddy-detail-row" style="color:var(--muted);font-style:italic">None</div>';

  // Phone numbers
  const selPerson = PEOPLE.find(p2 => p2.name === sel);
  const selPhone = selPerson && selPerson.phone ? selPerson.phone : '';
  const buddyPhone = p.buddy.phone || '';
  const phoneHtml = (selPhone || buddyPhone) ? `
    <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px;padding-bottom:14px;border-bottom:1px solid var(--border)">
      ${{selPhone ? `<div style="background:var(--surface2);border:1px solid var(--border);border-radius:8px;padding:8px 14px;font-size:0.85rem">
        <span style="color:var(--muted);font-size:0.72rem;display:block;margin-bottom:2px;text-transform:uppercase;letter-spacing:0.05em">${{escH(sel)}}</span>
        <a href="tel:${{escH(selPhone)}}" style="color:var(--accent);text-decoration:none;font-weight:600">${{escH(selPhone)}}</a>
      </div>` : ''}}
      ${{buddyPhone ? `<div style="background:var(--surface2);border:1px solid var(--border);border-radius:8px;padding:8px 14px;font-size:0.85rem">
        <span style="color:var(--muted);font-size:0.72rem;display:block;margin-bottom:2px;text-transform:uppercase;letter-spacing:0.05em">${{escH(p.buddy.name)}}</span>
        <a href="tel:${{escH(buddyPhone)}}" style="color:var(--accent);text-decoration:none;font-weight:600">${{escH(buddyPhone)}}</a>
      </div>` : ''}}
    </div>` : '';

  document.getElementById('buddy-modal-title').textContent = escH(sel) + ' \u2194 ' + escH(p.buddy.name);
  document.getElementById('buddy-modal-body').innerHTML = `
    ${{phoneHtml}}
    <div class="buddy-detail-cols">
      <div class="buddy-detail-col">
        <div class="buddy-detail-col-head can-teach">${{escH(sel)}} can teach ${{escH(p.buddy.name)}} (${{p.aToBCount}})</div>
        <div class="buddy-detail-list">${{rowsAtoB}}</div>
      </div>
      <div class="buddy-detail-col">
        <div class="buddy-detail-col-head learns-from">${{escH(p.buddy.name)}} can teach ${{escH(sel)}} (${{p.bToACount}})</div>
        <div class="buddy-detail-list">${{rowsBtoA}}</div>
      </div>
    </div>`;

  modal.style.display = 'flex';
  overlay.style.display = 'block';
}}

function closeBuddyDetail() {{
  document.getElementById('buddy-modal').style.display = 'none';
  document.getElementById('buddy-modal-overlay').style.display = 'none';
}}

// ── Rendering ─────────────────────────────────────────────────────────────

function showBuddyResults(name) {{
  const results = rankBuddies(name);
  if (!results || results.top4Pairs.length === 0) {{
    document.getElementById('buddy-results').style.display = 'none';
    document.getElementById('buddy-empty-state').style.display = '';
    return;
  }}
  _buddyDetailData = {{ selectedName: name, pairs: results.top4Pairs }};
  document.getElementById('buddy-empty-state').style.display = 'none';
  document.getElementById('buddy-results').style.display = '';
  renderBuddyPairs(results.selectedName, results.top4Pairs);
  renderBuddyTrios(results.selectedName, results.top3Trios);
}}

function renderBuddyPairs(selectedName, pairs) {{
  const grid = document.getElementById('buddy-pairs-grid');
  grid.innerHTML = '';
  const rankLabels = ['#1 Best Match', '#2', '#3', '#4'];
  pairs.forEach((p, idx) => {{
    const color = scoreColor(p.score);
    const card = document.createElement('div');
    card.className = 'buddy-card';
    card.style.cursor = 'pointer';
    card.title = 'Click to see full topic breakdown';
    card.onclick = () => openBuddyDetail(idx);
    card.innerHTML = `
      <div class="buddy-card-header">
        <div class="buddy-name">${{escH(p.buddy.name)}}</div>
        <div class="buddy-rank">${{rankLabels[idx] || '#' + (idx + 1)}}</div>
      </div>
      <div class="buddy-score-row">
        <span class="buddy-score-label">Compatibility</span>
        <div class="buddy-score-bar"><div class="buddy-score-bar-fill" style="width:${{p.score}}%"></div></div>
        <span class="score-cell" style="background:${{color}};font-size:0.78rem;padding:3px 7px;min-width:40px">${{p.score}}</span>
      </div>
      <div class="buddy-exchange">
        <div class="buddy-direction">
          <div class="buddy-dir-label can-teach">You can teach</div>
          <div class="buddy-dir-count">${{p.aToBCount}}<span>topics</span></div>
        </div>
        <div class="buddy-direction">
          <div class="buddy-dir-label learns-from">You can learn</div>
          <div class="buddy-dir-count">${{p.bToACount}}<span>topics</span></div>
        </div>
      </div>
      <div class="buddy-footer">
        <span class="buddy-gap-badge">${{p.sharedGaps}} shared gaps</span>
        <span class="buddy-common-badge">${{p.sharedStrength}} both know</span>
        <span style="margin-left:auto;font-size:0.7rem;color:var(--muted)">tap for details &rsaquo;</span>
      </div>`;
    grid.appendChild(card);
  }});
}}

function renderBuddyTrios(selectedName, trios) {{
  const grid = document.getElementById('buddy-trios-grid');
  grid.innerHTML = '';
  if (trios.length === 0) {{
    grid.innerHTML = '<div class="buddy-empty">Not enough respondents to form trios.</div>';
    return;
  }}
  trios.forEach(t => {{
    const color = scoreColor(t.score);
    const coveragePct = Math.round(t.coverage / t.total * 100);
    const deadPct = Math.round(t.deadZones / t.total * 100);
    const card = document.createElement('div');
    card.className = 'trio-card';
    card.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap">
        <div class="trio-names">
          <span class="trio-name-chip is-you">${{escH(selectedName)}}</span>
          <span class="trio-joiner">+</span>
          <span class="trio-name-chip">${{escH(t.buddyA.name)}}</span>
          <span class="trio-joiner">+</span>
          <span class="trio-name-chip">${{escH(t.buddyB.name)}}</span>
        </div>
        <span class="score-cell" style="background:${{color}};flex-shrink:0;font-size:0.78rem;padding:3px 7px">${{t.score}}</span>
      </div>
      <div class="trio-stats">
        <div class="trio-stat">
          <div class="trio-stat-val" style="color:var(--yes)">${{coveragePct}}%</div>
          <div class="trio-stat-lbl">Topics at least one knows</div>
        </div>
        <div class="trio-stat">
          <div class="trio-stat-val" style="color:var(--accent)">${{t.teachable}}</div>
          <div class="trio-stat-lbl">Teaching opportunities</div>
        </div>
        <div class="trio-stat">
          <div class="trio-stat-val" style="color:var(--no)">${{deadPct}}%</div>
          <div class="trio-stat-lbl">Shared gaps (all 3)</div>
        </div>
      </div>`;
    grid.appendChild(card);
  }});
}}
</script>
</body>
</html>"""
    return html

def main():
    print("Fetching data from Google Sheets...")
    topics, people = fetch_data()
    print(f"  {len(people)} respondents, {len(topics)} topics")

    print("Computing statistics...")
    topic_stats = compute_topic_stats(topics, people)
    person_scores = compute_person_scores(topics, people)

    print("Generating HTML...")
    html = generate_html(topics, people, topic_stats, person_scores)

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("Done! Saved to index.html")

if __name__ == "__main__":
    main()
