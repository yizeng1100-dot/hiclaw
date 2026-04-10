#!/usr/bin/env python3
"""Generate HTML performance analysis reports."""

import argparse
import datetime
import json
import os
import sys

from tp_query import default_output_dir


PRIORITY_ORDER = {
    "critical": 0,
    "poor": 1,
    "high": 1,
    "warning": 2,
    "fair": 3,
    "normal": 4,
    "good": 5,
    "excellent": 6,
}

SEVERITY_COLORS = {
    "critical": ("#f85149", "#f8514933"),
    "poor": ("#f85149", "#f8514933"),
    "high": ("#f85149", "#f8514933"),
    "warning": ("#d29922", "#d2992233"),
    "fair": ("#d29922", "#d2992233"),
    "normal": ("#58a6ff", "#58a6ff33"),
    "good": ("#3fb950", "#3fb95033"),
    "excellent": ("#3fb950", "#3fb95033"),
}


def load_results(output_dir: str) -> dict:
    results = {}
    for fname in sorted(os.listdir(output_dir)):
        if fname.endswith('.json') and fname != 'tp_state.json':
            with open(os.path.join(output_dir, fname)) as f:
                results[fname.replace('.json', '')] = json.load(f)
    return results


def make_severity_badge(sev: str) -> str:
    color, bg = SEVERITY_COLORS.get(sev, ("#8b949e", "#8b949e33"))
    return f'<span style="display:inline-block;padding:2px 10px;border-radius:12px;font-size:12px;font-weight:bold;background:{bg};color:{color}">{sev.upper()}</span>'


def render_section(name: str, data: dict) -> str:
    sev = data.get("severity", "normal")
    title = name.replace("_", " ").replace("-", " ").title()
    badge = make_severity_badge(sev)

    sev_class = "severity-high" if sev in ("critical", "poor", "high") else "severity-medium" if sev in ("warning", "fair") else "severity-low" if sev in ("good", "excellent") else "severity-normal"

    html = f'<div class="card {sev_class}"><h3>{title} {badge}</h3>'

    # Render key metrics
    skip_keys = {"has_issue", "severity"}
    for key, val in data.items():
        if key in skip_keys:
            continue
        if isinstance(val, (list, dict)):
            if isinstance(val, list) and len(val) > 0:
                html += f'<h4>{key.replace("_", " ").title()} ({len(val)} items)</h4>'
                html += '<table><tr>'
                if isinstance(val[0], dict):
                    for col in val[0]:
                        html += f'<th>{col}</th>'
                    html += '</tr>'
                    for row in val[:15]:
                        html += '<tr>'
                        for col in val[0]:
                            v = row.get(col, "")
                            if isinstance(v, float):
                                v = f"{v:.2f}"
                            html += f'<td>{v}</td>'
                        html += '</tr>'
                html += '</table>'
        else:
            if isinstance(val, float):
                val = f"{val:.2f}"
            html += f'<p><strong>{key.replace("_", " ").title()}:</strong> {val}</p>'

    html += '</div>'
    return html


def generate_html(results: dict, report_type: str = "full") -> str:
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    is_full = report_type == "full"
    title = "Performance Analysis - Full Report" if is_full else "Performance Analysis - Issues Report"

    # Sort by severity
    sorted_results = sorted(
        results.items(),
        key=lambda x: PRIORITY_ORDER.get(x[1].get("severity", "normal"), 99)
    )

    # For issue report, filter only items with issues
    if not is_full:
        sorted_results = [(k, v) for k, v in sorted_results if v.get("has_issue", False)]

    # Count severities
    sev_counts = {}
    for _, v in sorted_results:
        s = v.get("severity", "normal")
        sev_counts[s] = sev_counts.get(s, 0) + 1

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 0; padding: 20px; background: #0d1117; color: #c9d1d9; }}
.container {{ max-width: 1200px; margin: 0 auto; }}
h1 {{ color: #58a6ff; border-bottom: 1px solid #30363d; padding-bottom: 12px; font-size: 24px; }}
h2 {{ color: #79c0ff; margin-top: 32px; font-size: 18px; }}
h3 {{ color: #d2a8ff; margin: 0 0 12px 0; font-size: 16px; }}
h4 {{ color: #8b949e; font-size: 13px; margin: 12px 0 4px 0; }}
p {{ margin: 4px 0; font-size: 14px; }}
.card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; margin: 12px 0; }}
.severity-high {{ border-left: 4px solid #f85149; }}
.severity-medium {{ border-left: 4px solid #d29922; }}
.severity-low {{ border-left: 4px solid #3fb950; }}
.severity-normal {{ border-left: 4px solid #58a6ff; }}
table {{ width: 100%; border-collapse: collapse; margin: 8px 0; font-size: 13px; }}
th, td {{ padding: 6px 10px; border: 1px solid #30363d; text-align: left; }}
th {{ background: #21262d; color: #79c0ff; }}
tr:hover {{ background: #1c2128; }}
.summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin: 16px 0; }}
.summary-item {{ background: #21262d; border-radius: 8px; padding: 16px; text-align: center; }}
.summary-value {{ font-size: 28px; font-weight: bold; }}
.summary-label {{ font-size: 12px; color: #8b949e; margin-top: 4px; }}
.footer {{ text-align: center; color: #8b949e; margin-top: 40px; padding: 20px; border-top: 1px solid #30363d; font-size: 12px; }}
</style>
</head>
<body>
<div class="container">
<h1>{"&#128270;" if is_full else "&#9888;&#65039;"} {title}</h1>
<p style="color:#8b949e">Generated: {timestamp} | Total sections: {len(sorted_results)}</p>

<div class="summary">
"""
    for sev, count in sorted(sev_counts.items(), key=lambda x: PRIORITY_ORDER.get(x[0], 99)):
        color, _ = SEVERITY_COLORS.get(sev, ("#8b949e", "#8b949e33"))
        html += f'<div class="summary-item"><div class="summary-value" style="color:{color}">{count}</div><div class="summary-label">{sev.upper()}</div></div>'

    html += '</div>'

    for name, data in sorted_results:
        html += render_section(name, data)

    html += f"""
<div class="footer">
  <p>Generated by HiClaw Performance Analysis Workflow</p>
  <p>{timestamp}</p>
</div>
</div>
</body>
</html>"""
    return html


def main():
    parser = argparse.ArgumentParser(description="Generate HTML reports")
    parser.add_argument("--output-dir", default=default_output_dir())
    args = parser.parse_args()

    results = load_results(args.output_dir)
    if not results:
        print("ERROR: No analysis results found", file=sys.stderr)
        sys.exit(1)

    # Full report
    full_html = generate_html(results, "full")
    full_path = os.path.join(args.output_dir, "full_report.html")
    with open(full_path, "w") as f:
        f.write(full_html)

    # Issue report
    issue_html = generate_html(results, "issue")
    issue_path = os.path.join(args.output_dir, "issue_report.html")
    with open(issue_path, "w") as f:
        f.write(issue_html)

    output = {
        "full_report": full_path,
        "issue_report": issue_path,
        "sections": len(results),
        "issues": sum(1 for v in results.values() if v.get("has_issue", False)),
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
