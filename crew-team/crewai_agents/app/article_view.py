"""Safe, dependency-free editorial rendering for approved public articles."""
import html
import math
import re
from datetime import datetime
from urllib.parse import urlsplit


def _paragraphs(body):
    return [part.strip() for part in re.split(r'\n\s*\n', body) if part.strip()]


def _heading(value):
    plain = value.lstrip('#').strip()
    words = plain.split()
    return (value.startswith('## ') or
            (2 <= len(words) <= 10 and len(plain) <= 90 and not re.search(r'[.!?]$', plain)))


def _body_html(parts):
    blocks = []
    for index, part in enumerate(parts):
        if index and _heading(part):
            blocks.append('<h2>' + html.escape(part.lstrip('#').strip()) + '</h2>')
            continue
        lines = [line.strip() for line in part.splitlines() if line.strip()]
        numbered = len(lines) > 1 and all(re.match(r'^\d+[.)]\s+', line) for line in lines)
        if numbered:
            blocks.append('<ol>' + ''.join('<li>' + html.escape(re.sub(r'^\d+[.)]\s+', '', line)) + '</li>'
                                               for line in lines) + '</ol>')
        else:
            blocks.append('<p' + (' class="lede"' if index == 0 else '') + '>' +
                          html.escape(part).replace('\n', '<br>') + '</p>')
    return ''.join(blocks)


def _date(value):
    try:
        parsed = datetime.fromisoformat(value)
        return f'{parsed:%B} {parsed.day}, {parsed.year}'
    except (TypeError, ValueError):
        return 'Bun2too Insights'


def render(run, run_id, public_base, artwork=False):
    article = run['artifact']['articles'][0]
    title = html.escape(article['title'])
    raw_parts = _paragraphs(article['body'])
    description_text = re.sub(r'\s+', ' ', raw_parts[0] if raw_parts else article['body']).strip()[:240]
    description = html.escape(description_text, quote=True)
    words = len(re.findall(r"\b[\w'-]+\b", article['body']))
    reading_time = max(1, math.ceil(words / 220))
    canonical = public_base.rstrip('/') + '/articles/' + run_id
    image_url = canonical + '/artwork.webp' if artwork else ''
    source_items = []
    for url in article.get('source_urls', []):
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            continue
        label = parsed.hostname.removeprefix('www.')
        source_items.append('<li><a rel="noopener noreferrer" target="_blank" href="' +
                            html.escape(url, quote=True) + '"><span>' + html.escape(label) +
                            '</span><b>Read source <span aria-hidden="true">↗</span></b></a></li>')
    sources = ('<aside class="sources" aria-labelledby="sources-title"><div><p class="eyebrow">Further reading</p>'
               '<h2 id="sources-title">Sources behind this story</h2></div><ul>' + ''.join(source_items) +
               '</ul></aside>') if source_items else ''
    hero = ('<figure class="hero"><img src="/articles/' + html.escape(run_id, quote=True) +
            '/artwork.webp" alt="' + html.escape((run.get('article_artwork') or {}).get('alt', ''), quote=True) +
            '" width="1536" height="1024"><figcaption>Original editorial artwork generated for this article</figcaption></figure>'
            if artwork else '<div class="hero fallback" role="img" aria-label="Abstract Bun2too editorial artwork">'
                            '<span></span><span></span><span></span><strong>Ideas<br>in motion.</strong></div>')
    og_image = ('<meta property="og:image" content="' + html.escape(image_url, quote=True) + '">'
                '<meta property="og:image:width" content="1536"><meta property="og:image:height" content="1024">'
                '<meta name="twitter:card" content="summary_large_image">') if image_url else '<meta name="twitter:card" content="summary">'
    css = r'''
:root{--ink:#121212;--muted:#686868;--paper:#f7f5ef;--accent:#ff4f2e;--line:#d8d5ce;--night:#151a22}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;color:var(--ink);background:var(--paper);font-family:Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;-webkit-font-smoothing:antialiased}
a{color:inherit}.masthead{height:72px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;padding:0 clamp(20px,5vw,72px)}
.brand{text-decoration:none;font-weight:900;letter-spacing:-.06em;font-size:26px}.brand i{color:var(--accent);font-style:normal}.section{font-size:12px;font-weight:750;letter-spacing:.16em;text-transform:uppercase;color:var(--muted)}
.progress{height:3px;background:linear-gradient(90deg,var(--accent) 0 38%,transparent 38%)}main{overflow:hidden}
.article-head{max-width:1180px;margin:0 auto;padding:clamp(64px,10vw,132px) clamp(22px,5vw,72px) clamp(42px,7vw,84px);display:grid;grid-template-columns:minmax(0,1fr) minmax(230px,300px);gap:clamp(34px,8vw,110px);align-items:end}
.eyebrow{font-size:12px;line-height:1.2;font-weight:800;letter-spacing:.18em;text-transform:uppercase;color:var(--accent);margin:0 0 20px}.article-head h1{font-family:Georgia,"Times New Roman",serif;font-size:clamp(48px,7vw,96px);line-height:.96;letter-spacing:-.055em;margin:0;max-width:900px}
.meta{border-top:1px solid var(--ink);padding-top:18px;font-size:13px;line-height:1.65;color:var(--muted)}.meta strong{display:block;color:var(--ink);font-size:14px}.meta span{display:block}
.hero{width:min(1400px,calc(100% - 32px));aspect-ratio:3/2;margin:0 auto clamp(58px,9vw,120px);position:relative;overflow:hidden;background:var(--night)}.hero img{width:100%;height:100%;object-fit:cover;display:block}.hero figcaption{position:absolute;right:12px;bottom:10px;background:#111c;color:#fff;padding:7px 10px;font-size:10px;letter-spacing:.04em}
.fallback{background:radial-gradient(circle at 18% 78%,#ff6d38 0 11%,transparent 11.2%),radial-gradient(circle at 72% 30%,#b8ff65 0 16%,transparent 16.2%),linear-gradient(135deg,#19212d,#0c1016);isolation:isolate}.fallback:before{content:"";position:absolute;inset:-20%;background:repeating-linear-gradient(115deg,transparent 0 42px,#ffffff12 43px 44px);transform:rotate(-7deg)}.fallback span{position:absolute;border:1px solid #ffffff70;border-radius:50%;width:38%;aspect-ratio:1}.fallback span:nth-child(1){left:8%;top:12%}.fallback span:nth-child(2){left:32%;top:38%}.fallback span:nth-child(3){right:-5%;top:-12%}.fallback strong{position:absolute;right:7%;bottom:7%;font-family:Georgia,serif;font-size:clamp(48px,8vw,124px);line-height:.76;letter-spacing:-.06em;color:#fff;text-align:right}
.story-grid{max-width:1120px;margin:0 auto;padding:0 clamp(22px,5vw,72px);display:grid;grid-template-columns:170px minmax(0,700px);gap:clamp(30px,8vw,90px);align-items:start}.rail{position:sticky;top:24px;border-top:1px solid var(--ink);padding-top:14px;font-size:12px;line-height:1.6;color:var(--muted)}.rail strong{display:block;color:var(--ink);text-transform:uppercase;letter-spacing:.12em;font-size:11px;margin-bottom:5px}
.prose{font-family:Georgia,"Times New Roman",serif;font-size:clamp(19px,2vw,22px);line-height:1.72}.prose p{margin:0 0 1.55em}.prose .lede{font-size:clamp(25px,3.1vw,36px);line-height:1.34;letter-spacing:-.025em;margin-bottom:1.8em}.prose .lede:first-letter{float:left;font-size:4.3em;line-height:.78;padding:12px 10px 0 0;color:var(--accent)}.prose h2{font-size:clamp(31px,4vw,48px);line-height:1.08;letter-spacing:-.035em;margin:1.65em 0 .62em}.prose ol{padding-left:1.25em}.prose li{padding-left:.35em;margin-bottom:.8em}
.sources{max-width:1120px;margin:clamp(70px,10vw,140px) auto 0;padding:42px clamp(22px,5vw,72px) 80px;border-top:1px solid var(--ink);display:grid;grid-template-columns:1fr 1.4fr;gap:50px}.sources h2{font-family:Georgia,serif;font-size:clamp(30px,4vw,48px);line-height:1.05;margin:0}.sources ul{list-style:none;padding:0;margin:0}.sources li{border-top:1px solid var(--line)}.sources li:last-child{border-bottom:1px solid var(--line)}.sources a{padding:17px 2px;text-decoration:none;display:flex;justify-content:space-between;gap:20px;font-size:13px}.sources b{white-space:nowrap}.sources a:hover b{color:var(--accent)}
.footer{background:var(--night);color:#fff;padding:55px clamp(22px,5vw,72px);display:flex;align-items:end;justify-content:space-between}.footer .brand{font-size:38px}.footer p{margin:0;color:#adb4bf;font-size:12px;max-width:330px;text-align:right;line-height:1.5}
@media(max-width:720px){.masthead{height:60px}.article-head{grid-template-columns:1fr}.article-head h1{font-size:clamp(43px,14vw,67px)}.meta{max-width:240px}.hero{width:100%;margin-bottom:58px}.hero figcaption{display:none}.story-grid{grid-template-columns:1fr}.rail{position:static;display:flex;gap:8px;border-top:0;padding:0}.rail span:after{content:" · "}.prose .lede:first-letter{font-size:3.5em}.sources{grid-template-columns:1fr}.footer{align-items:start;flex-direction:column;gap:30px}.footer p{text-align:left}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
'''
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            'content="width=device-width,initial-scale=1"><title>' + title + ' | Bun2too</title>'
            '<meta name="description" content="' + description + '"><link rel="canonical" href="' +
            html.escape(canonical, quote=True) + '"><meta property="og:type" content="article">'
            '<meta property="og:site_name" content="Bun2too"><meta property="og:title" content="' + title +
            '"><meta property="og:description" content="' + description + '"><meta property="og:url" content="' +
            html.escape(canonical, quote=True) + '">' + og_image + '<style>' + css + '</style></head><body>'
            '<header class="masthead"><a class="brand" href="/insights">BUN2TOO<i>.</i></a><span class="section">Insights / Technology</span></header><div class="progress"></div><main>'
            '<header class="article-head"><div><p class="eyebrow">Technology · Analysis</p><h1>' + title +
            '</h1></div><div class="meta"><strong>Bun2too Editorial Team</strong><span>' +
            html.escape(_date(run.get('updated_at') or run.get('created_at'))) + '</span><span>' + str(reading_time) +
            ' min read</span></div></header>' + hero + '<div class="story-grid"><aside class="rail"><strong>Filed under</strong><span>AI</span><span>Software</span><span>Innovation</span></aside>'
            '<article class="prose">' + _body_html(raw_parts) + '</article></div>' + sources + '</main>'
            '<footer class="footer"><a class="brand" href="/insights">BUN2TOO<i>.</i></a><p>Practical perspectives on software engineering, AI, and the systems shaping modern work.</p></footer></body></html>')


def render_index(items):
    cards = []
    for run_id, run, artwork in items:
        article = run['artifact']['articles'][0]
        parts = _paragraphs(article['body'])
        summary = re.sub(r'\s+', ' ', parts[0] if parts else article['body']).strip()[:220]
        media = ('<img src="/articles/' + html.escape(run_id, quote=True) + '/artwork.webp" alt="' +
                 html.escape((run.get('article_artwork') or {}).get('alt', ''), quote=True) + '">') if artwork else '<span class="abstract"></span>'
        cards.append('<article class="card"><a class="media" href="/articles/' + html.escape(run_id, quote=True) + '">' +
                     media + '</a><div><p class="eyebrow">Technology · Analysis</p><h2><a href="/articles/' +
                     html.escape(run_id, quote=True) + '">' + html.escape(article['title']) + '</a></h2><p class="summary">' +
                     html.escape(summary) + '</p><p class="byline">Bun2too Editorial Team · ' +
                     html.escape(_date(run.get('updated_at') or run.get('created_at'))) + '</p></div></article>')
    empty = '<p class="empty">The next Bun2too field note is in production.</p>' if not cards else ''
    css = r'''
:root{--ink:#121212;--muted:#686868;--paper:#f7f5ef;--accent:#ff4f2e;--line:#d8d5ce;--night:#151a22}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font-family:Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.masthead{height:72px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;padding:0 clamp(20px,5vw,72px)}.brand{text-decoration:none;font-weight:900;letter-spacing:-.06em;font-size:26px}.brand i{color:var(--accent);font-style:normal}.section,.byline{font-size:12px;color:var(--muted);letter-spacing:.08em}.section,.eyebrow{text-transform:uppercase;font-weight:750}.hero{max-width:1240px;margin:0 auto;padding:clamp(70px,11vw,150px) clamp(22px,5vw,72px) clamp(50px,7vw,90px)}.eyebrow{color:var(--accent);letter-spacing:.18em;font-size:11px;margin:0 0 16px}.hero h1{font:clamp(58px,10vw,138px)/.82 Georgia,serif;letter-spacing:-.07em;margin:0;max-width:900px}.hero p:last-child{font:20px/1.5 Georgia,serif;max-width:650px;margin:38px 0 0}.stories{max-width:1120px;margin:0 auto;padding:0 clamp(22px,5vw,72px) 110px}.card{border-top:1px solid var(--ink);padding:34px 0;display:grid;grid-template-columns:minmax(280px,1fr) 1.25fr;gap:clamp(28px,6vw,72px)}.media{display:block;aspect-ratio:3/2;background:var(--night);overflow:hidden}.media img{width:100%;height:100%;display:block;object-fit:cover}.abstract{display:block;width:100%;height:100%;background:radial-gradient(circle at 72% 28%,#b8ff65 0 16%,transparent 16.4%),radial-gradient(circle at 21% 76%,#ff5c38 0 12%,transparent 12.4%),repeating-linear-gradient(125deg,#151a22 0 34px,#27303d 35px 36px)}.card h2{font:clamp(30px,4vw,49px)/1.02 Georgia,serif;letter-spacing:-.04em;margin:0}.card h2 a{text-decoration:none}.card h2 a:hover{color:var(--accent)}.summary{font:17px/1.55 Georgia,serif;color:#383838;margin:22px 0}.empty{border-top:1px solid var(--ink);padding:40px 0;font:28px Georgia,serif}.footer{background:var(--night);color:#fff;padding:55px clamp(22px,5vw,72px);display:flex;justify-content:space-between}.footer p{color:#adb4bf;font-size:12px}@media(max-width:720px){.masthead{height:60px}.hero h1{font-size:clamp(58px,18vw,90px)}.card{grid-template-columns:1fr}.footer{flex-direction:column;gap:24px}}
'''
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Bun2too Insights | AI, software, and innovation</title><meta name="description" content="Practical perspectives on software engineering, AI, and the systems shaping modern work.">'
            '<style>' + css + '</style></head><body><header class="masthead"><a class="brand" href="/insights">BUN2TOO<i>.</i></a><span class="section">Independent technology perspectives</span></header>'
            '<main><section class="hero"><p class="eyebrow">Bun2too Insights</p><h1>Ideas for what comes next.</h1><p>Clear, sourced reporting and practical analysis for people building with software and AI.</p></section>'
            '<section class="stories" aria-label="Latest articles">' + ''.join(cards) + empty + '</section></main>'
            '<footer class="footer"><a class="brand" href="/insights">BUN2TOO<i>.</i></a><p>Software engineering · AI · Data · Innovation</p></footer></body></html>')
