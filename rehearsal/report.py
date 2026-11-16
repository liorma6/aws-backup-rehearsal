"""Portable evidence: JSON, Markdown, JUnit XML and self-contained HTML."""
import html
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def write_reports(report, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    lines = ["# AWS Backup Rehearsal — execution evidence", "",
        f"**{report['passed']}/{report['total']} scenarios passed** · Backend: **{report['backend']}**", "",
        f"Run: `{report['run_id']}` · UTC: {report['created_at']} · {report['duration_ms']} ms", "",
        f"Emulator build: {report.get('emulator_version') or 'not applicable / not recorded'}", "",
        "| Scenario | Result | Workflow outcome | Duration | Retries |", "|---|---|---|---:|---:|"]
    for result in report["scenarios"]:
        lines.append(f"| {result['title']} | {'PASS' if result['passed'] else 'FAIL'} | {result.get('workflow_status', 'error')} | {result['elapsed_ms']} ms | {result['retries']} |")
    lines += ["", "## Boundaries", ""] + [f"- {value}" for value in report["limitations"]]
    for result in report["scenarios"]:
        lines += ["", f"## {result['title']}", "", result["expected"], ""]
        lines += [f"- [{'x' if c['passed'] else ' '}] {c['label']}" for c in result["checks"]]
        if result.get("error"):
            lines += ["", f"Error: `{result['error']}`"]
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    suite = ET.Element("testsuite", name="backup-rehearsal", tests=str(report["total"]),
                       failures=str(report["total"] - report["passed"]), time=str(report["duration_ms"] / 1000))
    for result in report["scenarios"]:
        case = ET.SubElement(suite, "testcase", name=result["id"], classname=report["backend"], time=str(result["elapsed_ms"] / 1000))
        if not result["passed"]:
            ET.SubElement(case, "failure").text = json.dumps(result["checks"]) + result.get("error", "")
    ET.ElementTree(suite).write(output / "junit.xml", encoding="utf-8", xml_declaration=True)
    esc = html.escape
    cards = []
    for result in report["scenarios"]:
        checks = "".join(f"<li class='{ 'ok' if c['passed'] else 'bad'}'>{'✓' if c['passed'] else '×'} {esc(c['label'])}</li>" for c in result["checks"])
        trace = esc(json.dumps(result["events"], indent=2))
        cards.append(f"<article><div class='row'><h2>{esc(result['title'])}</h2><b class='{'ok' if result['passed'] else 'bad'}'>{'PASS' if result['passed'] else 'FAIL'}</b></div><p>{esc(result['expected'])}</p><ul>{checks}</ul><div class='meta'>{result['elapsed_ms']} ms · {result['retries']} retries · workflow: {esc(result.get('workflow_status','error'))}</div><details><summary>Inspect request evidence</summary><pre>{trace}</pre></details></article>")
    limitations = "".join(f"<li>{esc(value)}</li>" for value in report["limitations"])
    page = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AWS Backup Rehearsal | Execution evidence</title><style>
    :root{font-family:Inter,ui-sans-serif,system-ui,sans-serif;color:#deebf8;background:#0b1220}*{box-sizing:border-box}body{margin:0}main{max-width:1120px;margin:0 auto;padding:56px 24px}header{border-bottom:1px solid #2a3b51;padding-bottom:30px}.eyebrow{font-size:12px;letter-spacing:.18em;color:#8ca5c4;text-transform:uppercase}h1{font-size:clamp(32px,5vw,56px);letter-spacing:-.04em;line-height:1.08;margin:16px 0}p{color:#a6b8d0;line-height:1.6}.pill{display:inline-block;background:#182d40;border:1px solid #31516b;padding:6px 12px;border-radius:30px;font-size:13px}.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin:28px 0}.stat,article{background:#111e2f;border:1px solid #25354b;border-radius:16px;padding:24px}.stat strong{display:block;font-size:29px;letter-spacing:-.03em}.stat span{font-size:13px;color:#91a7c2}.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}.row{display:flex;gap:16px;align-items:start;justify-content:space-between}h2{font-size:18px;margin:0}ul{padding-left:0;list-style:none;font-size:14px;line-height:1.7}.ok{color:#74d9bb}.bad{color:#ff9c9c}.meta{font-size:12px;color:#99acc5;margin-top:20px}details{margin-top:20px;font-size:13px}summary{cursor:pointer;color:#b1cdf2}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:360px;overflow:auto;background:#0b1420;padding:16px;border-radius:8px}.boundary{margin-top:28px;padding:24px;border-left:3px solid #d8ad60;background:#1c2030}.boundary h2{color:#f1ca84}.boundary li{color:#b7c5d9;margin:8px 0}footer{margin-top:30px;font-size:12px;color:#7790af;overflow-wrap:anywhere}@media(max-width:720px){.grid{grid-template-columns:1fr}.stats{grid-template-columns:1fr}main{padding:30px 16px}}
    </style></head><body><main>"""
    page += f"<header><div class='eyebrow'>Independent engineering pilot · synthetic data</div><h1>Rehearse failure.<br>Inspect the evidence.</h1><p>Repeatable S3 discovery, backup and restore scenarios. Every result below comes from this recorded execution.</p><span class='pill'>{esc(report['backend'])}</span></header>"
    page += f"<section class='stats'><div class='stat'><strong>{report['passed']} / {report['total']}</strong><span>Scenario expectations met</span></div><div class='stat'><strong>{report['duration_ms']} ms</strong><span>Single run · not a cloud benchmark</span></div><div class='stat'><strong>S3 only</strong><span>5 synthetic source objects per scenario</span></div></section>"
    page += "<section class='grid'>" + "".join(cards) + "</section>"
    page += f"<section class='boundary'><h2>What this evidence does—and does not—show</h2><ul>{limitations}</ul></section>"
    page += f"<footer>Run {esc(report['run_id'])} · {esc(report['created_at'])}<br>Build: {esc(report.get('emulator_version') or 'No emulator build recorded')}<br>Independent prototype by Lior Mashiach. No affiliation with AWS or Eon.</footer></main></body></html>"
    (output / "report.html").write_text(page, encoding="utf-8")
