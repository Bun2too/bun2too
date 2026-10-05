"""Build a self-contained downloadable architecture document and companion ZIP.

Uses markdown-it-py, already supplied by the project's development environment.
No network resources or browser scripts are needed by the generated document.
"""
import html
from pathlib import Path
import zipfile

from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / 'docs'


def diagram():
    boxes = [
        (20, 20, 160, 58, 'User / Scheduler'), (220, 20, 190, 58, 'Authenticated Gateway'),
        (450, 20, 220, 58, 'Application / Durable Worker'),
        (710, 20, 270, 58, 'Agents • Retrieval • Models • Delivery'),
        (450, 130, 220, 58, 'OpenTelemetry Instrumentation'),
        (450, 235, 220, 65, 'Collector + Persistent Queues'),
        (710, 235, 270, 65, 'Kafka / Event Hub (optional)'),
        (450, 345, 220, 58, 'Traces • Metrics • Logs'),
        (450, 445, 220, 58, 'Dashboards / Alerts / Investigation'),
        (20, 235, 350, 65, 'Restricted Evidence / Versioned Evaluators'),
    ]
    arrows = ['M180 49 H220', 'M410 49 H450', 'M670 49 H710', 'M560 78 V130',
              'M560 188 V235', 'M560 300 V345', 'M560 403 V445', 'M670 267 H710',
              'M845 300 V374 H670', 'M370 267 H450']
    shape = ''.join(f'<path d="{path}" class="arrow" marker-end="url(#arrow)"/>' for path in arrows)
    shape += ''.join(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10"/>'
                     f'<text x="{x+w/2}" y="{y+h/2+5}" text-anchor="middle">{html.escape(label)}</text>'
                     for x,y,w,h,label in boxes)
    return ('<figure><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 535" role="img" '
            'aria-label="OTLP HTTP reference architecture with optional message buffering">'
            '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">'
            '<path d="M0,0 L0,6 L8,3 z" fill="#48617b"/></marker></defs>' + shape +
            '<text x="575" y="218">OTLP over HTTP</text></svg>'
            '<figcaption>Direct Collector export is the default. Kafka/Event Hub is optional.</figcaption></figure>')


def main():
    markdown = MarkdownIt('commonmark').enable('table')
    architecture = (DOCS / 'enterprise-ai-observability-architecture.md').read_text()
    start = architecture.index('```mermaid')
    end = architecture.index('```', start + 3) + 3
    body = markdown.render(architecture[:start]) + diagram() + markdown.render(architecture[end:])
    body += '<hr><div class="appendix">Implementation appendix</div>' + markdown.render((DOCS / 'telemetry-implementation.md').read_text())
    page = '''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Enterprise AI Observability Architecture — OTLP over HTTP</title>
<style>
:root{font-family:system-ui,-apple-system,sans-serif;color:#172a3d;background:#edf2f7;line-height:1.65}
body{max-width:1060px;margin:40px auto;background:white;padding:50px 64px;border-top:8px solid #167b94}
h1{font-size:2.2rem;line-height:1.2;letter-spacing:-.035em}h2{margin-top:2.6rem;color:#126b82;line-height:1.3}
h3{margin-top:2rem}a{color:#126b82}table{border-collapse:collapse;width:100%;font-size:.9rem;margin:1.5rem 0}
th,td{padding:12px;border:1px solid #d6e0e9;text-align:left;vertical-align:top}th{background:#edf4f7}
pre{background:#edf2f7;padding:20px;overflow:auto;border-radius:8px;font-size:.84rem;line-height:1.5}
code{font-size:.9em;overflow-wrap:anywhere}li{margin:.55rem 0}figure{margin:2rem 0}svg{width:100%}
svg rect{fill:#edf6fa;stroke:#167b94;stroke-width:1.5}svg text{font-size:13px;fill:#172a3d}
.arrow{fill:none;stroke:#48617b;stroke-width:2}figcaption{color:#54667a;font-size:.88rem}
hr{margin:4rem 0;border:0;border-top:2px solid #d6e0e9}.appendix{color:#167b94;text-transform:uppercase;font-weight:700;letter-spacing:.1em}
@media(max-width:700px){body{margin:0;padding:22px}h1{font-size:1.8rem}table{display:block;overflow:auto}}
@media print{body{margin:0;padding:0;border:0;max-width:none}h2{break-after:avoid}tr,pre,figure{break-inside:avoid}a{color:inherit}.appendix{break-before:page}}
</style></head><body>''' + body + '</body></html>\n'
    output = DOCS / 'enterprise-ai-observability-architecture.html'
    output.write_text(page)
    with zipfile.ZipFile(DOCS / 'enterprise-ai-observability-architecture.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in ('enterprise-ai-observability-architecture.md', 'enterprise-ai-observability-architecture.html', 'telemetry-implementation.md'):
            archive.write(DOCS / name, arcname=name)
    print(output)


if __name__ == '__main__':
    main()
