#!/usr/bin/env python3
"""Scrape ecovillage directories for new organizations."""
import sqlite3, re, json, ssl, urllib.request, urllib.parse, time
from html.parser import HTMLParser
from concurrent.futures import ThreadPoolExecutor, as_completed

DB_PATH = '/home/user/volunteer-map/backend/organizations.db'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def fetch(url, timeout=15):
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': UA,
            'Accept': 'text/html,application/xhtml+xml,application/json,*/*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'identity',
        })
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return r.read(500000).decode('utf-8', errors='replace')
    except:
        return None

class Ext(HTMLParser):
    def __init__(self):
        super().__init__(); self.text=[]; self.links=[]; self._skip=False; self._d=0; self._in_a=False; self._a=[]; self._ahref=''
    def handle_starttag(self, tag, attrs):
        d=dict(attrs)
        if tag in ('script','style','noscript'): self._skip=True; self._d+=1
        if tag=='a': self._in_a=True; self._a=[]; self._ahref=d.get('href','')
    def handle_endtag(self, tag):
        if tag in ('script','style','noscript'):
            self._d-=1
            if self._d<=0: self._skip=False
        if tag=='a' and self._in_a:
            self._in_a=False; t=''.join(self._a).strip()
            if t: self.links.append((t, self._ahref))
    def handle_data(self, data):
        if self._in_a: self._a.append(data)
        if not self._skip and data.strip(): self.text.append(data.strip())
    def get_text(self): return ' '.join(self.text)

def get_lat_lon(html):
    for pat in [r'"latitude"\s*:\s*"?(-?\d+\.?\d*)"\s*,\s*"longitude"\s*:\s*"?(-?\d+\.?\d*)"',
                r'data-lat="(-?\d+\.?\d*)"[^>]*data-lng="(-?\d+\.?\d*)"',
                r'data-latitude="(-?\d+\.?\d*)"[^>]*data-longitude="(-?\d+\.?\d*)"',
                r'll=(-?\d+\.?\d*),(-?\d+\.?\d*)',
                r'q=(-?\d+\.?\d*),(-?\d+\.?\d*)']:
        m=re.search(pat, html or '')
        if m:
            try: return float(m.group(1)), float(m.group(2))
            except: pass
    return None, None

def get_desc(html):
    for pat in [r'og:description"[^>]*content="([^"]+)"', r'name="description"[^>]*content="([^"]+)"']:
        m=re.search(pat, html or '')
        if m and len(m.group(1).strip())>30: return m.group(1).strip()[:1000]
    for m in re.finditer(r'<p[^>]*>(.*?)</p>', html or '', re.DOTALL):
        t=re.sub(r'<[^>]+>','',m.group(1)).strip()
        if len(t)>50: return t[:1000]
    return ''

def get_website(html, base_url):
    m=re.search(r'og:url"[^>]*content="([^"]+)"', html or '')
    if m: return m.group(1)
    ext=Ext()
    try: ext.feed(html)
    except: pass
    base_domain=urllib.parse.urlparse(base_url).netloc
    for txt,href in ext.links:
        if href.startswith('http') and base_domain not in href:
            if not any(x in href for x in ['facebook','twitter','instagram','youtube','linkedin','pinterest','tiktok']):
                return href
    return ''

def get_email(text):
    m=re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text or '')
    if m:
        email=m.group(0)
        if not any(x in email for x in ['sentry','example','wixpress','cloudflare','noreply']):
            return email
    return ''

def scrape_listing(base_url, link_pattern, source, org_type='Eco Village', max_pages=30):
    """Scrape paginated listing pages, follow links, extract org data."""
    orgs=[]
    for page in range(1, max_pages+1):
        url = base_url if page==1 else f'{base_url}page/{page}/'
        html=fetch(url)
        if not html:
            url=f'{base_url}?paged={page}'
            html=fetch(url)
            if not html: break

        ext=Ext()
        try: ext.feed(html)
        except: pass

        page_links=[]
        seen=set()
        for t,h in ext.links:
            if link_pattern in h:
                full=urllib.parse.urljoin(url,h)
                if full not in seen and t.strip():
                    seen.add(full)
                    page_links.append((t.strip(),full))

        if not page_links:
            print(f"  {source} p{page}: 0 links, stopping")
            break

        print(f"  {source} p{page}: {len(page_links)} links")

        with ThreadPoolExecutor(max_workers=10) as ex:
            futs={ex.submit(fetch,l):(t,l) for t,l in page_links}
            for f in as_completed(futs):
                t,l=futs[f]
                ph=f.result()
                if not ph: continue
                pe=Ext()
                try: pe.feed(ph)
                except: pass
                text=pe.get_text()
                lat,lon=get_lat_lon(ph)
                desc=get_desc(ph)
                ws=get_website(ph,l)
                email=get_email(text)
                country=''
                rm=re.search(r'project-region[^>]*>.*?<b[^>]*>Region</b>:\s*([^<]+)', ph)
                if rm: country=rm.group(1).strip()
                if t and (lat or ws or len(desc)>30):
                    orgs.append({'name':t[:200],'description':desc,'website':ws,'email':email,
                        'country':country,'latitude':lat,'longitude':lon,
                        'source':source,'organization_type':org_type})
        time.sleep(0.5)
    return orgs

def scrape_wp_api(base, post_type, source, org_type='Eco Village', max_pages=15):
    """Scrape WordPress REST API."""
    orgs=[]
    for page in range(1, max_pages+1):
        url=f'{base}/wp-json/wp/v2/{post_type}?per_page=100&page={page}&_embed'
        data=fetch(url)
        if not data: continue
        try: items=json.loads(data)
        except: break
        if not isinstance(items,list) or not items: break
        print(f"  {source} API p{page}: {len(items)}")
        for item in items:
            title=item.get('title',{})
            title=title.get('rendered','') if isinstance(title,dict) else str(title)
            title=re.sub(r'<[^>]+>','',title).strip()
            content=item.get('content',{})
            desc=re.sub(r'<[^>]+>','',content.get('rendered','') if isinstance(content,dict) else '').strip()[:1000]
            link=item.get('link','')
            lat=lon=None
            meta=item.get('meta',{})
            if isinstance(meta,dict):
                try: lat=float(meta.get('latitude',0) or 0) or None
                except: pass
                try: lon=float(meta.get('longitude',0) or 0) or None
                except: pass
            acf=item.get('acf',{})
            if isinstance(acf,dict):
                if not lat:
                    try: lat=float(acf.get('latitude',0) or 0) or None
                    except: pass
                if not lon:
                    try: lon=float(acf.get('longitude',0) or 0) or None
                    except: pass
            if title:
                orgs.append({'name':title[:200],'description':desc,'website':link,'latitude':lat,'longitude':lon,'source':source,'organization_type':org_type})
    return orgs

def main():
    conn=sqlite3.connect(DB_PATH)
    cur=conn.cursor()
    cur.execute("SELECT name, website FROM organizations")
    existing_names=set()
    existing_urls=set()
    for r in cur.fetchall():
        existing_names.add(r[0].lower().strip())
        if r[1]: existing_urls.add(r[1].lower().strip().rstrip('/'))
    cur.execute("SELECT MAX(id) FROM organizations")
    next_id=(cur.fetchone()[0] or 0)+1

    all_orgs=[]

    # 1. ecovillage.org GEN
    print("=== ecovillage.org ===")
    all_orgs += scrape_listing('https://ecovillage.org/projects/', '/ecovillage/', 'ecovillage', 'Eco Village', 30)

    # 2. diggersanddreamers.org.uk
    print("\n=== diggersanddreamers.org.uk ===")
    all_orgs += scrape_listing('https://www.diggersanddreamers.org.uk/communities-directory', '/communities/', 'DiggersAndDreamers', 'Intentional Community', 15)

    # 3. ecoversities.org - try WP API then directory
    print("\n=== ecoversities.org ===")
    eco_orgs = scrape_wp_api('https://ecoversities.org', 'ecoversity', 'Ecoversities', 'Ecoversity', 10)
    if not eco_orgs:
        eco_orgs = scrape_listing('https://ecoversities.org/', '/ecoversity/', 'Ecoversities', 'Ecoversity', 10)
    all_orgs += eco_orgs

    # 4. ecobasa.org
    print("\n=== ecobasa.org ===")
    all_orgs += scrape_listing('https://ecobasa.org/directory/', '/community/', 'ecobasa', 'Eco Village', 10)
    all_orgs += scrape_listing('https://ecobasa.org/communities/', '/profile/', 'ecobasa', 'Eco Village', 10)

    # 5. GEN Europe
    print("\n=== gen-europe.org ===")
    all_orgs += scrape_listing('https://gen-europe.org/projects/', '/project/', 'ecovillage', 'Eco Village', 10)

    # 6. GTA
    print("\n=== globaltapestryofalternatives.org ===")
    all_orgs += scrape_listing('https://map.globaltapestryofalternatives.org/', '/Case', 'GTA', 'Alternative Community', 10)

    # 7. Crianza Mutua
    print("\n=== crianzamutua.mx ===")
    all_orgs += scrape_listing('https://crianzamutua.mx/', '/Grupo', 'CrianzaMutua', 'Alternative Community', 10)

    # Deduplicate against existing DB
    new_orgs=[]
    seen=set()
    for org in all_orgs:
        nl=org['name'].lower().strip()
        wl=(org.get('website','') or '').lower().strip().rstrip('/')
        if nl in existing_names or nl in seen: continue
        if wl and wl in existing_urls: continue
        seen.add(nl)
        new_orgs.append(org)

    print(f"\n=== SUMMARY ===")
    print(f"Total scraped: {len(all_orgs)}")
    print(f"New (not in DB): {len(new_orgs)}")

    inserted=0
    for org in new_orgs:
        cur.execute("""INSERT INTO organizations
            (id, name, description, organization_type, website, country, latitude, longitude, source,
             accepts_volunteers, accepts_visitors, accepts_shortterm, accepts_longterm, has_jobs, has_stays, has_events)
            VALUES (?,?,?,?,?,?,?,?,?,0,0,0,0,0,0,0)""",
            (next_id, org['name'], org['description'], org.get('organization_type',''),
             org.get('website',''), org.get('country',''), org.get('latitude'), org.get('longitude'),
             org.get('source','')))
        next_id+=1
        inserted+=1
    conn.commit()

    cur.execute("SELECT COUNT(*) FROM organizations")
    total=cur.fetchone()[0]
    cur.execute("SELECT source, COUNT(*) FROM organizations GROUP BY source ORDER BY COUNT(*) DESC")
    sources=cur.fetchall()
    print(f"\nInserted {inserted} new organizations")
    print(f"Total in DB: {total}")
    for s,c in sources: print(f"  {s}: {c}")
    conn.close()

if __name__=='__main__':
    main()
