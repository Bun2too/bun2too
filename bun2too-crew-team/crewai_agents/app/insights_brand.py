"""Shared navigation and brand treatment for legacy article URLs."""
import html
from .insights import site_url

CSS = '''
:root{--ink:#f1f0e6;--muted:#a6b4aa;--paper:#111e1c;--accent:#d0ed9a;--line:#34453b;--night:#182925}
body{background:var(--paper);color:var(--ink)}a:focus-visible,button:focus-visible{outline:3px solid #fa9518;outline-offset:5px}
.masthead{height:auto;min-height:88px;gap:28px;flex-wrap:wrap;padding-top:18px;padding-bottom:18px}.brand img{width:170px;height:auto;display:block}.masthead nav{display:flex;align-items:center;gap:24px;font-size:14px;flex-wrap:wrap}.masthead nav a{text-decoration:none;color:var(--muted)}.masthead nav a[aria-current],.masthead nav a:hover{color:var(--accent)}.main-contact{border:1px solid var(--line);padding:12px 18px;border-radius:30px}
.hero h1,.article-head h1{font-family:Arial,Helvetica,sans-serif;letter-spacing:-.065em}.hero p:last-child{color:var(--muted)}.summary{color:var(--muted)}.card{border-color:var(--line)}.card h2{font-size:clamp(28px,3.6vw,46px)}.media,.hero{border-radius:12px}.media img{transition:transform .25s}.media:hover img{transform:scale(1.025)}.byline{letter-spacing:0}.meta strong,.rail strong{color:var(--ink)}.insights-follow{border:1px solid var(--line);border-radius:20px;background:var(--night);max-width:1040px;margin:0 auto 72px;padding:38px;display:flex;gap:30px;justify-content:space-between;align-items:center}.insights-follow h2{font-size:32px;margin:0 0 12px}.insights-follow p{color:var(--muted);line-height:1.7;max-width:560px}.insights-follow a{display:inline-block;padding:12px 18px;border:1px solid var(--line);border-radius:30px;text-decoration:none;margin:5px}.insights-follow a:first-child{background:var(--accent);color:var(--paper)}.footer{background:var(--night);gap:24px}.footer a{color:var(--ink)}
@media(max-width:720px){.masthead nav{gap:14px;font-size:13px}.brand img{width:145px}.insights-follow{margin:0 20px 45px;padding:24px;display:block}.hero{border-radius:0}}@media(prefers-reduced-motion:reduce){.media img{transition:none}}
'''


def decorate(page, run_id=None):
    base=html.escape(site_url(),quote=True)
    brand='<a class="brand" href="'+base+'" aria-label="Bun2Too home"><img src="/insights-assets/logoHighRes.png" alt="Bun2Too" width="1003" height="290"></a>'
    nav='<header class="masthead">'+brand+'<nav aria-label="Main navigation">'+''.join(
        '<a href="'+base+path+'"'+(' aria-current="page"' if path=='/insights' else '')+'>'+label+'</a>'
        for label,path in [('Services','/services'),('Our process','/process'),('Use cases','/usecases'),('Insights','/insights'),('My account','/account')])+ '<a class="main-contact" href="'+base+'/contact">Let’s connect ↗</a></nav></header>'
    import re
    canonical = base + '/insights' + ('/' + html.escape(run_id, quote=True) if run_id else '')
    if 'rel="canonical"' in page:
        page=re.sub(r'<link rel="canonical" href="[^"]*">', lambda _: '<link rel="canonical" href="'+canonical+'">', page)
        page=re.sub(r'<meta property="og:url" content="[^"]*">', lambda _: '<meta property="og:url" content="'+canonical+'">', page)
    else:
        page=page.replace('</head>', '<link rel="canonical" href="'+canonical+'"></head>')
    page=re.sub(r'<header class="masthead">.*?</header>',lambda _:nav,page,count=1)
    follow='<section class="insights-follow" aria-label="Follow Bun2Too Insights"><div><p class="eyebrow">Stay curious</p><h2>Good ideas. Worth keeping.</h2><p>Choose email updates on Bun2Too, see what’s new on the site, or follow along in your favorite feed reader.</p></div><div><a href="'+base+'/insights#subscribe">Subscribe to insights ↗</a><a href="/insights/feed.xml">RSS feed</a><a href="/insights/feed.atom">Atom feed</a></div></section>'
    embed='<section aria-label="Email subscription"><iframe title="Subscribe to Bun2Too email insights" src="'+base+'/insights/signup" loading="lazy" style="width:100%;height:950px;border:0"></iframe></section>'
    page=page.replace('</main>',follow+embed+'</main>')
    page=page.replace('<a class="brand" href="/insights">BUN2TOO<i>.</i></a>',brand)
    page=page.replace('<style>', '<link rel="alternate" type="application/rss+xml" title="Bun2Too Insights" href="/insights/feed.xml"><link rel="alternate" type="application/atom+xml" title="Bun2Too Insights" href="/insights/feed.atom"><style>',1)
    page=page.replace('</style>','</style><style>'+CSS+'</style>',1)
    return page
