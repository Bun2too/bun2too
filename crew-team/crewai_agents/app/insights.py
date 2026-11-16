"""Public, publication-only projections. Never expose run briefs, traces or credentials."""
import json
import os
import re
from datetime import datetime, timezone
from email.utils import format_datetime
from xml.etree import ElementTree as ET
from . import marketing


def site_url():
    return os.getenv('INSIGHTS_SITE_URL', 'https://bun2too.com').rstrip('/')


def entries(db, data_dir, limit=100, run_id=None):
    with db.connect() as conn:
        rows = conn.execute("SELECT data FROM runs WHERE id=?", (run_id,)).fetchall() if run_id else conn.execute("SELECT data FROM runs ORDER BY rowid DESC").fetchall()
        publications = {row[0]: json.loads(row[1]) for row in conn.execute('SELECT run_id,data FROM social_posts')}
    result = []
    for row in rows:
        run = json.loads(row[0])
        articles = (run.get('artifact') or {}).get('articles') or []
        if run.get('status') != 'published' or not run.get('approval') or not articles:
            continue
        article = articles[0]
        # Social publication timestamps do not change when metrics are refreshed.
        publication = publications.get(run['id']) or {}
        stamp = publication.get('updated_at') or publication.get('created_at') or run['approval'].get('approved_at') or run['created_at']
        body = article['body']
        result.append(dict(id=run['id'], title=article['title'], body=body,
            summary=re.sub(r'\s+', ' ', body.split('\n\n')[0]).strip()[:260],
            published_at=stamp, url=site_url() + '/insights/' + run['id'],
            image_url=(os.getenv('PUBLIC_API_BASE_URL', '').rstrip('/') + '/articles/' + run['id'] + '/artwork.webp')
                if marketing.artwork_path(data_dir, run.get('article_artwork')) else None,
            image_alt=(run.get('article_artwork') or {}).get('alt', ''),
            reading_minutes=max(1, (len(body.split()) + 219)//220),
            source_urls=[u for u in article.get('source_urls', []) if u.startswith('https://')]))
    return sorted(result, key=lambda item: (item['published_at'], item['id']), reverse=True)[:limit]


def feed(items, atom=False):
    if atom:
        ET.register_namespace('', 'http://www.w3.org/2005/Atom')
        def tag(name): return '{http://www.w3.org/2005/Atom}' + name
        root = ET.Element(tag('feed'))
        for key, value in [('title', 'Bun2Too Insights'), ('id', site_url()+'/insights'),
                           ('updated', items[0]['published_at'] if items else '1970-01-01T00:00:00Z')]:
            ET.SubElement(root, tag(key)).text = value
        ET.SubElement(root, tag('link'), href=site_url()+'/insights/feed.atom', rel='self')
        ET.SubElement(root, tag('link'), href=site_url()+'/insights')
        author = ET.SubElement(root, tag('author')); ET.SubElement(author, tag('name')).text='Bun2Too Editorial Team'
        for item in items:
            entry = ET.SubElement(root, tag('entry'))
            for key, value in [('id', item['url']), ('title', item['title']), ('updated', item['published_at']),
                               ('summary', item['summary'])]:
                ET.SubElement(entry, tag(key)).text = value
            ET.SubElement(entry, tag('link'), href=item['url'])
    else:
        root = ET.Element('rss', version='2.0'); channel = ET.SubElement(root, 'channel')
        for key,value in [('title','Bun2Too Insights'),('link',site_url()+'/insights'),
                          ('description','Practical perspectives on AI, software and customer technology.')]:
            ET.SubElement(channel,key).text=value
        for item in items:
            entry=ET.SubElement(channel,'item')
            for key,value in [('title',item['title']),('link',item['url']),('guid',item['url']),('description',item['summary']),
                              ('pubDate',format_datetime(datetime.fromisoformat(item['published_at'].replace('Z','+00:00')).astimezone(timezone.utc)))]:
                ET.SubElement(entry,key).text=value
    return ET.tostring(root,encoding='utf-8',xml_declaration=True)
