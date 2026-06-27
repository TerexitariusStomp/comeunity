#!/usr/bin/env python3
"""Re-scrape job source_urls to get real job-specific titles and descriptions."""
import sqlite3
import re
import ssl
import urllib.request
import urllib.error
import socket
from html.parser import HTMLParser
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

DB_PATH = '/home/user/volunteer-map/backend/organizations.db'
TIMEOUT = 12
NUM_WORKERS = 25
MAX_READ = 200 * 1024  # Read up to 200KB of HTML

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'

DOMAIN_BLACKLIST = {
    'linktr.ee', 'facebook.com', 'fb.com', 'instagram.com',
    'twitter.com', 'x.com', 'linkedin.com', 'tiktok.com',
    'youtube.com', 'youtu.be', 'vimeo.com', 'pinterest.com',
    't.me', 'telegram.me', 'wa.me', 'whatsapp.com',
    'gofundme.com', 'kickstarter.com', 'indiegogo.com',
}


class TextExtractor(HTMLParser):
    SKIP_TAGS = {'script', 'style', 'nav', 'footer', 'header', 'aside', 'menu', 'noscript', 'svg', 'form'}
    SKIP_CLASSES = {'sidebar', 'menu', 'navigation', 'navbar', 'nav-menu', 'main-nav',
                    'breadcrumb', 'breadcrumbs', 'top-bar', 'topbar', 'site-header',
                    'site-footer', 'page-header', 'page-footer', 'mobile-nav',
                    'hamburger', 'social', 'social-links', 'social-icons',
                    'cookie', 'cookie-banner', 'popup', 'modal', 'search-form',
                    'wp-sidebar', 'widget-area', 'secondary', 'masthead',
                    'primary-menu', 'main-menu', 'sub-menu', 'footer-widgets',
                    'copyright', 'legal', 'site-info', 'skip-link', 'screen-reader'}
    SKIP_IDS = {'sidebar', 'navbar', 'header', 'footer', 'menu', 'navigation',
                'primary-menu', 'main-menu', 'site-header', 'site-footer'}

    def __init__(self):
        super().__init__()
        self.chunks = []
        self.skip_depth = 0
        self._skip_stack = []

    def handle_starttag(self, tag, attrs):
        should_skip = False
        if tag in self.SKIP_TAGS:
            should_skip = True
        else:
            attrs_dict = dict(attrs)
            cls = (attrs_dict.get('class') or '').lower()
            id_val = (attrs_dict.get('id') or '').lower()
            role = (attrs_dict.get('role') or '').lower()
            if role in ('navigation', 'banner', 'complementary', 'search'):
                should_skip = True
            elif any(sc in cls for sc in self.SKIP_CLASSES):
                should_skip = True
            elif any(sid in id_val for sid in self.SKIP_IDS):
                should_skip = True
        if should_skip:
            self.skip_depth += 1
            self._skip_stack.append(tag)

    def handle_endtag(self, tag):
        if self.skip_depth > 0 and self._skip_stack and self._skip_stack[-1] == tag:
            self.skip_depth -= 1
            self._skip_stack.pop()
        elif self.skip_depth > 0 and tag in self.SKIP_TAGS:
            self.skip_depth = max(0, self.skip_depth - 1)

    def handle_data(self, data):
        if self.skip_depth <= 0:
            s = data.strip()
            if s:
                self.chunks.append(s)

    def get_text(self):
        return re.sub(r'\s+', ' ', ' '.join(self.chunks)).strip()


class TitleExtractor(HTMLParser):
    """Extract the <title> tag and first <h1> tag."""
    def __init__(self):
        super().__init__()
        self.title = None
        self.h1 = None
        self._in_title = False
        self._in_h1 = False
        self._title_buf = ''
        self._h1_buf = ''

    def handle_starttag(self, tag, attrs):
        if tag == 'title':
            self._in_title = True
        elif tag == 'h1':
            self._in_h1 = True

    def handle_data(self, data):
        if self._in_title:
            self._title_buf += data
        if self._in_h1:
            self._h1_buf += data

    def handle_endtag(self, tag):
        if tag == 'title' and self._in_title:
            self._in_title = False
            self.title = re.sub(r'\s+', ' ', self._title_buf).strip()
        elif tag == 'h1' and self._in_h1:
            self._in_h1 = False
            self.h1 = re.sub(r'\s+', ' ', self._h1_buf).strip()

    def get_title(self):
        return self.title

    def get_h1(self):
        return self.h1


def fetch(url):
    if not url or not url.startswith('http'):
        return None, None
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower().lstrip('www.')
        if any(domain.endswith(bd) or domain == bd for bd in DOMAIN_BLACKLIST):
            return None, None
    except:
        return None, None
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': UA,
            'Accept': 'text/html,application/xhtml+xml',
            'Accept-Language': 'en-US,en;q=0.9',
        })
        old_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(TIMEOUT)
        resp = urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx)
        data = resp.read(MAX_READ).decode('utf-8', errors='replace')
        socket.setdefaulttimeout(old_timeout)
        return resp.geturl(), data
    except:
        return None, None


def extract_meta_description(html):
    """Extract <meta name="description" content="..."> from HTML."""
    m = re.search(r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']{20,})["\']', html, re.I)
    if m:
        desc = re.sub(r'\s+', ' ', m.group(1)).strip()
        if len(desc) > 30:
            return desc
    # Also try og:description
    m = re.search(r'<meta\s+property=["\']og:description["\']\s+content=["\']([^"\']{20,})["\']', html, re.I)
    if m:
        desc = re.sub(r'\s+', ' ', m.group(1)).strip()
        if len(desc) > 30:
            return desc
    return None


def clean_title(raw_title, h1, org_name, url):
    """Generate a good job title from page title and h1."""
    candidates = []
    
    # Try h1 first (usually more specific)
    if h1:
        h1_clean = re.sub(r'\s+', ' ', h1).strip()
        h1_clean = re.sub(r'\s*[|–—-]\s*.*$', '', h1_clean).strip()  # Remove suffixes
        if 5 < len(h1_clean) < 80:
            candidates.append(h1_clean)
    
    # Try page title
    if raw_title:
        t = re.sub(r'\s+', ' ', raw_title).strip()
        # Remove common suffixes like " | Org Name" or " - Org Name"
        t = re.sub(r'\s*[|–—-]\s*.*$', '', t).strip()
        # Remove "Home" prefix
        t = re.sub(r'^Home\s*[-|]\s*', '', t, flags=re.I)
        if 5 < len(t) < 80:
            candidates.append(t)
    
    # Check candidates for junk
    junk_words = ['cookie', 'javascript', 'warenkorb', 'anmelden', 'pdf', 'jpg', 'png',
                  'expired', 'suspended', 'buy ', 'domain', 'navigateur', 'haccp',
                  'skip to', 'open menu', 'close menu', 'toggle', 'sidebar']
    
    for c in candidates:
        low = c.lower()
        if any(j in low for j in junk_words):
            continue
        # Skip if it's just the org name
        if c.lower() == org_name.lower():
            continue
        # Skip if it looks like nav (many capitalized words)
        words = c.split()
        if len(words) > 8:
            cap = sum(1 for w in words if w and w[0].isupper())
            if cap > len(words) * 0.7:
                continue
        # Good candidate
        return c
    
    # Fallback: "Volunteer at Org Name"
    return f"Volunteer at {org_name}"


def extract_job_description(text, page_title, org_name, meta_desc=None):
    """Extract a 2-4 sentence job-specific description from page text."""
    # If we have a good meta description, use it as a base
    if meta_desc and len(meta_desc) > 50:
        # Check it's not junk
        low_md = meta_desc.lower()
        junk = ['cookie', 'javascript', 'warenkorb', 'anmelden', 'pdf, jpg',
                'expired domain', 'suspension page', 'navigateur']
        if not any(j in low_md for j in junk):
            # If meta desc is good enough on its own, use it
            if len(meta_desc) > 80:
                result = meta_desc[:500]
                if len(result) > 450:
                    last_period = result.rfind('. ')
                    if last_period > 100:
                        result = result[:last_period + 1]
                return result
    
    if not text:
        return meta_desc if meta_desc and len(meta_desc) > 50 else None
    
    text = re.sub(r'\s+', ' ', text).strip()
    
    # Remove page title from start if present
    if page_title:
        t_clean = re.sub(r'\s+', ' ', page_title).strip()
        if text.startswith(t_clean):
            text = text[len(t_clean):].strip()
    
    # Remove org name from start
    if text.startswith(org_name):
        text = text[len(org_name):].strip(' \u2014|-\u2013\u00b7')
    
    # Remove leading separators
    text = re.sub(r'^[\u2014\u2013\-|\u00b7\s]+', '', text).strip()
    
    # Split into sentences
    sentences = re.split(r'(?<=[.!?])\s+', text)
    
    # Keywords that indicate job-specific content - weighted
    high_kw = ['volunteer', 'opportunity', 'position', 'role', 'intern', 'apprentice',
               'steward', 'we are seeking', 'we are looking', 'seeking', 'join our',
               'join us', 'help us', 'we need', 'we welcome', 'we offer',
               'work exchange', 'wwoof', 'get involved', 'apply',
               'food forest', 'co-living', 'off-grid', 'natural building',
               'permaculture', 'regenerat', 'sustainable living']
    medium_kw = ['community', 'farm', 'garden', 'eco', 'teach', 'build', 'grow',
                 'nurture', 'restore', 'exchange', 'participate', 'contribute',
                 'skills', 'experience', 'learn', 'organic', 'biodynamic',
                 'homestead', 'retreat', 'stay', 'accommodation', 'work',
                 'help', 'mission', 'dedicated', 'focused', 'committed',
                 'we believe', 'our vision', 'our mission', 'collective',
                 'cooperative', 'collaborative', 'education', 'healing',
                 'spiritual', 'sanctuary', 'conservation', 'restoration',
                 'agriculture', 'horticulture', 'shared', 'welcome']
    low_kw = ['located in', 'based in', 'founded', 'established', 'project',
              'program', 'land', 'nature', 'environment', 'people', 'live']
    
    # Nav/junk indicators
    skip_words = ['menu', 'sidebar', 'footer', 'header', 'navigation', 'skip to',
                  'scroll', 'cookie', 'subscribe', 'follow us', 'all rights reserved',
                  'copyright', 'privacy policy', 'link to', 'share this', 'back to top',
                  'home about contact', 'search for', 'log in', 'sign up', 'register',
                  'cart', 'checkout', 'primary navigation', 'main content', 'toggle',
                  'open menu', 'close menu', 'anmelden', 'warenkorb', 'impressum',
                  'datenschutz', 'kontakt', 'navigateur', 'ouvre une nouvelle',
                  'select the extension', 'domain name', 'haberdashery',
                  'place an order', 'pop in', 'tag cloud', 'auslandsarbeit',
                  'bookmaker', 'paypal', 'form fields', 'first name last name']
    
    good_sentences = []
    for s in sentences:
        s = s.strip()
        if len(s) < 25:
            continue
        low = s.lower()
        
        # Skip nav/junk
        if any(sw in low for sw in skip_words):
            continue
        
        # Skip sentences that are just concatenated nav links
        words = s.split()
        cap_words = sum(1 for w in words if w and w[0].isupper())
        if cap_words > len(words) * 0.7 and len(words) > 5:
            continue
        
        # Skip pipe-separated breadcrumbs
        if s.count('|') > 2:
            continue
        
        # Skip domain names
        if re.match(r'^[\w\s\-]+\.(com|org|net|de|io|uk|co)\b', s, re.I):
            continue
        
        # Skip "Home About Contact" style nav
        if re.match(r'^(Home|About|Contact|Blog|Events|Gallery|Shop)\s+', s):
            continue
        
        # Skip category lists (e.g., "Transition Group Community Growing Other food projects")
        if re.match(r'^(Transition Group|Community Growing|Other food|Nature Community)', s):
            continue
        
        # Score sentence by keyword relevance
        score = sum(3 for kw in high_kw if kw in low)
        score += sum(2 for kw in medium_kw if kw in low)
        score += sum(1 for kw in low_kw if kw in low)
        
        # Bonus for sentences near the start (more likely to be intro/description)
        position_bonus = max(0, 5 - len(good_sentences))
        score += position_bonus
        
        if score > 0:
            good_sentences.append((score, s))
        if len(good_sentences) >= 15:
            break
    
    # Sort by score (descending) and take top 4
    good_sentences.sort(key=lambda x: -x[0])
    best = [s for score, s in good_sentences[:4]]
    
    if best:
        result = ' '.join(best)
        if len(result) > 50:
            if len(result) > 500:
                truncated = result[:500]
                last_period = truncated.rfind('. ')
                if last_period > 100:
                    result = truncated[:last_period + 1]
                else:
                    result = truncated + '...'
            return result
    
    # Fallback: find any sentence with job keywords
    for s in sentences:
        s = s.strip()
        low = s.lower()
        if len(s) > 40 and any(kw in low for kw in high_kw + medium_kw):
            return s[:500]
    
    # Last resort: use meta description if available
    if meta_desc and len(meta_desc) > 50:
        return meta_desc[:500]
    
    return None


def process_job(args):
    job_id, source_url, org_name, current_desc = args
    
    url, html = fetch(source_url)
    if not html or len(html) < 200:
        return None
    
    # Extract meta description
    meta_desc = extract_meta_description(html)
    
    # Extract title and h1
    te = TitleExtractor()
    try:
        te.feed(html)
    except:
        pass
    page_title = te.get_title()
    h1 = te.get_h1()
    
    # Extract text content
    tx = TextExtractor()
    try:
        tx.feed(html)
    except:
        pass
    text = tx.get_text()
    
    if len(text) < 50 and not meta_desc:
        return None
    
    # Generate new title
    new_title = clean_title(page_title, h1, org_name, source_url)
    
    # Generate new description
    new_desc = extract_job_description(text, page_title, org_name, meta_desc)
    
    # Always update if we got something good
    updates = {}
    if new_title and len(new_title) > 5:
        updates['title'] = new_title
    if new_desc and len(new_desc) > 50:
        updates['description'] = new_desc
    
    if updates:
        return (job_id, updates)
    return None


def main():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    cur = conn.cursor()
    
    # Get ALL jobs with source_urls (including ic.org directory pages)
    cur.execute('''
        SELECT v.id, v.source_url, o.name, v.description, v.title
        FROM volunteer_opportunities v
        JOIN organizations o ON v.organization_id = o.id
        WHERE v.source_url IS NOT NULL AND v.source_url != ''
        AND v.source_url NOT LIKE '%expireddomains%'
        ORDER BY v.id
    ''')
    rows = cur.fetchall()
    print(f'Jobs to re-scrape: {len(rows)}')
    
    # Deduplicate by source_url - only process unique URLs
    url_to_jobs = {}
    for row in rows:
        job_id, source_url, org_name, desc, title = row
        if source_url not in url_to_jobs:
            url_to_jobs[source_url] = []
        url_to_jobs[source_url].append((job_id, org_name, desc, title))
    
    print(f'Unique URLs to fetch: {len(url_to_jobs)}')
    
    # Build task list - one per unique URL
    tasks = []
    for url, jobs in url_to_jobs.items():
        # Use the first job for this URL
        first_job = jobs[0]
        tasks.append((first_job[0], url, first_job[1], first_job[2]))
    
    results = {}
    processed = 0
    updated = 0
    
    with ThreadPoolExecutor(max_workers=NUM_WORKERS) as pool:
        futures = {pool.submit(process_job, task): task for task in tasks}
        for future in as_completed(futures, timeout=300):
            processed += 1
            try:
                result = future.result()
                if result:
                    job_id, updates = result
                    # Apply to all jobs with this URL
                    task_url = futures[future][1]
                    for jid, org_name, desc, title in url_to_jobs.get(task_url, []):
                        results[jid] = updates
                    updated += 1
            except Exception as e:
                pass
            if processed % 50 == 0:
                print(f'  Processed {processed}/{len(tasks)} URLs, {updated} updated...')
    
    print(f'\nProcessed {processed} URLs, got updates for {len(results)} jobs')
    
    # Apply updates to database
    title_count = 0
    desc_count = 0
    for job_id, updates in results.items():
        if 'title' in updates:
            cur.execute('UPDATE volunteer_opportunities SET title = ? WHERE id = ?',
                        (updates['title'], job_id))
            title_count += 1
        if 'description' in updates:
            cur.execute('UPDATE volunteer_opportunities SET description = ? WHERE id = ?',
                        (updates['description'], job_id))
            desc_count += 1
    
    conn.commit()
    print(f'Titles updated: {title_count}')
    print(f'Descriptions updated: {desc_count}')
    conn.close()


if __name__ == '__main__':
    main()
