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

    topics = [cols[i]["label"] for i in range(2, len(cols))]

    people = []
    for row in rows:
        cells = row.get("c", [])
        name_cell = cells[1] if len(cells) > 1 else None
        name = (name_cell.get("v") or name_cell.get("f") or "Unknown") if name_cell else "Unknown"
        ts_cell = cells[0] if cells else None
        timestamp = (ts_cell.get("f") or "") if ts_cell else ""
        responses = []
        for i in range(2, len(cells)):
            raw = cells[i].get("v") if cells[i] else None
            responses.append(simplify_response(raw))
        people.append({"name": name, "timestamp": timestamp, "responses": responses})

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
        {"name": p["name"], "responses": p["responses"]} for p in people
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
