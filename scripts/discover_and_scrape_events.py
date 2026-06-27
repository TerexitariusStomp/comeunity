#!/usr/bin/env python3
"""
Discover and scrape event pages from organization websites.
Extracts event listings for an amalgamated event calendar.
"""
import sqlite3, re, urllib.request, urllib.parse, ssl, socket, time, json, sys, os
from datetime import datetime
from html.parser import HTMLParser

DB_PATH = '/home/user/volunteer-map/backend/organizations.db'
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
TIMEOUT = 5

SKIP_DOMAINS = {
    'facebook.com', 'instagram.com', 'twitter.com', 'x.com',
    'youtube.com', 'tiktok.com', 'pinterest.com', 'linkedin.com',
    'gofundme.com', 'paypal.com', 'ecovillage.org'
}
SKIP_PATHS = ('/donate', '/donation', '/fundraising', '/about-us',
              '/contact', '/team', '/staff', '/board')

EVENT_PATHS = [
    '/events', '/calendar', '/upcoming-events', '/event',
    '/workshops', '/programs', '/retreats', '/gatherings',
    '/festivals', '/courses', '/training', '/schedule',
    '/whatson', '/whats-on', '/activities', '/classes',
    '/retreats-workshops', '/workshops-events', '/event-calendar',
    '/community-events', '/annual-events', '/seasonal-events',
    '/conferences', '/open-days', '/visiting', '/visitors',
    '/tours', '/programmes'
]

EVENT_KEYWORDS = re.compile(
    r'event|calendar|workshop|retreat|gathering|festival|'
    r'course|training|seminar|conference|symposium|'
    r'date|schedule|upcoming|tickets|register|rsvp|'
    r'program|session|meeting|webinar|online event|'
    r'in-person|location|venue|time|am|pm|\d{1,2}:\d{2}',
    re.IGNORECASE
)

# Patterns to skip junk/noise entries
JUNK_TITLE_PATTERNS = [
    re.compile(r'^\s*(©|copyright|\u00a9)', re.IGNORECASE),
    re.compile(r'copyright\s+\d{4}', re.IGNORECASE),
    re.compile(r'connect with us', re.IGNORECASE),
    re.compile(r'follow us', re.IGNORECASE),
    re.compile(r'sign\s*(up|in|out)', re.IGNORECASE),
    re.compile(r'login|log\s*in', re.IGNORECASE),
    re.compile(r'the form contains errors?', re.IGNORECASE),
    re.compile(r'error\s*\d+', re.IGNORECASE),
    re.compile(r'page not found|404', re.IGNORECASE),
    re.compile(r'terms of use|privacy policy|cookie policy', re.IGNORECASE),
    re.compile(r'sitemap', re.IGNORECASE),
    re.compile(r'^\s*menu\s*$', re.IGNORECASE),
    re.compile(r'^\s*search\s*$', re.IGNORECASE),
    re.compile(r'^\s*home\s*$', re.IGNORECASE),
    re.compile(r'^\s*contact\s*$', re.IGNORECASE),
    re.compile(r'^\s*about\s*$', re.IGNORECASE),
    re.compile(r'^\s*close\s*$', re.IGNORECASE),
    re.compile(r'community website by|built with|powered by', re.IGNORECASE),
    re.compile(r'homeowners association|hoa sites|condo website', re.IGNORECASE),
    re.compile(r'^\s*subscribe\s*$', re.IGNORECASE),
    re.compile(r'^\s*read more\s*$', re.IGNORECASE),
    re.compile(r'^\s*learn more\s*$', re.IGNORECASE),
    re.compile(r'^\s*click here\s*$', re.IGNORECASE),
    re.compile(r'^\s*view\s+all\s*$', re.IGNORECASE),
    re.compile(r'^\s*previous\s*$', re.IGNORECASE),
    re.compile(r'^\s*next\s*$', re.IGNORECASE),
    re.compile(r'^\s*submit\s*$', re.IGNORECASE),
]

JUNK_DESC_PATTERNS = [
    re.compile(r'copyright\s+\d{4}.*all rights reserved', re.IGNORECASE),
    re.compile(r'the form contains errors?', re.IGNORECASE),
    re.compile(r'page not found|404 not found', re.IGNORECASE),
]

def is_junk_event(ev):
    title = (ev.get('title') or '').strip()
    desc = (ev.get('description') or '').strip()
    if not title and not desc:
        return True
    for pat in JUNK_TITLE_PATTERNS:
        if pat.search(title):
            return True
    for pat in JUNK_DESC_PATTERNS:
        if pat.search(desc):
            return True
    # Skip if title is just a single generic word and no description
    if len(title.split()) <= 2 and len(desc) < 50 and not ev.get('start_date'):
        return True
    return False

def dedupe_events(events):
    """Remove events with duplicate titles within the same org/page batch."""
    seen = set()
    out = []
    for ev in events:
        key = (ev.get('title') or '').strip().lower()[:120]
        if key and key in seen:
            continue
        seen.add(key)
        out.append(ev)
    return out

class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.chunks = []
        self.skip_depth = 0
        self.skip_tags = {'script', 'style', 'nav'}

    def handle_starttag(self, tag, attrs):
        if tag in self.skip_tags:
            self.skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self.skip_tags:
            self.skip_depth -= 1

    def handle_data(self, data):
        if self.skip_depth <= 0:
            s = data.strip()
            if s:
                self.chunks.append(s)

    def get_text(self):
        return re.sub(r'\s+', ' ', ' '.join(self.chunks)).strip()

class LinkExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            d = dict(attrs)
            href = d.get('href', '')
            if href and not href.startswith(('#', 'javascript:', 'mailto:', 'tel:', 'data:')):
                self.links.append((href, d.get('title', ''),))

def should_skip_url(url):
    low = url.lower()
    for d in SKIP_DOMAINS:
        if d in low:
            return True
    for p in SKIP_PATHS:
        if p in low:
            return True
    return False

def url_join(base, rel):
    if rel.startswith('http'):
        return rel
    if rel.startswith('//'):
        return 'https:' + rel
    if rel.startswith('/'):
        parsed = urllib.parse.urlparse(base)
        return f"{parsed.scheme}://{parsed.netloc}{rel}"
    if not base.endswith('/'):
        base = base.rsplit('/', 1)[0] + '/'
    return base + rel

def fetch(opener, url):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
        resp = opener.open(req, timeout=TIMEOUT)
        ctype = resp.headers.get('Content-Type', '')
        if 'text/html' not in ctype and 'application/xhtml' not in ctype:
            return None
        data = resp.read(500_000)
        enc = 'utf-8'
        if 'charset=' in ctype:
            m = re.search(r'charset=([\w-]+)', ctype)
            if m:
                enc = m.group(1)
        try:
            return data.decode(enc, errors='ignore')
        except:
            return data.decode('utf-8', errors='ignore')
    except Exception:
        return None

def parse_date(text):
    """Extract date strings from text."""
    # Common patterns: "Jan 15, 2026", "15 January 2026", "2026-01-15", "01/15/2026", "15.01.2026"
    patterns = [
        r'(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}[,.]?\s+(?:\d{4})?',
        r'\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(?:\d{4})?',
        r'\d{4}-\d{2}-\d{2}',
        r'\d{1,2}[./]\d{1,2}[./]\d{2,4}',
    ]
    dates = []
    for pat in patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            d = m.group(0).strip()
            if d and len(d) > 5:
                dates.append(d)
    return list(dict.fromkeys(dates))[:2]  # unique, max 2

def detect_calendar_system(html, page_url):
    """Detect if page has embedded calendar widgets or .ics feeds."""
    info = {'calendar_type': None, 'feed_url': None}
    low = html.lower()
    if 'calendar.google.com' in low or 'google.com/calendar' in low:
        info['calendar_type'] = 'google_embed'
    elif 'eventbrite' in low:
        info['calendar_type'] = 'eventbrite'
    elif 'meetup.com' in low:
        info['calendar_type'] = 'meetup'
    elif 'outlook.office365.com' in low or 'outlook.live.com' in low:
        info['calendar_type'] = 'outlook'
    # .ics / iCal feed
    ics_match = re.search(r'href=["\']([^"\']+\.ics)["\']', html, re.IGNORECASE)
    if ics_match:
        info['feed_url'] = url_join(page_url, ics_match.group(1))
        info['calendar_type'] = 'ics_feed'
    return info

def extract_jsonld_events(html):
    """Extract events from JSON-LD structured data."""
    events = []
    for m in re.finditer(r'<script type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.IGNORECASE | re.DOTALL):
        try:
            data = json.loads(m.group(1))
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                t = item.get('@type', '')
                if t not in ('Event', 'EducationEvent', 'Festival', 'Workshop', 'CourseInstance'):
                    continue
                events.append({
                    'title': item.get('name', ''),
                    'description': item.get('description', ''),
                    'start_date': item.get('startDate'),
                    'end_date': item.get('endDate'),
                    'is_online': item.get('eventAttendanceMode', '').endswith('OnlineEventAttendanceMode'),
                    'is_in_person': item.get('eventAttendanceMode', '').endswith('OfflineEventAttendanceMode'),
                    'registration_url': None,
                    'event_url': item.get('url', ''),
                })
        except Exception:
            pass
    return events

def extract_event_blocks(html, page_url):
    """Extract event-like blocks from HTML."""
    events = []

    # Strategy 0: JSON-LD structured data (often has full calendars)
    jsonld_events = extract_jsonld_events(html)
    if jsonld_events:
        events.extend(jsonld_events)

    # Strategy 1: Broad regex for structured event containers
    event_divs = re.findall(
        r'<(?:article|div|section|li|tr)[^>]*?(?:class|id)=["\']([^"\']*(?:event|workshop|retreat|gathering|festival|course|program|session|calendar-item|event-item|listing-item|activity|entry|item|post|row|card)[^"\']*)["\'][^>]*>(.*?)</(?:article|div|section|li|tr)>',
        html, re.IGNORECASE | re.DOTALL
    )

    # Strategy 2: If few blocks, look for containers with date patterns
    if len(event_divs) < 2:
        date_containers = re.findall(
            r'<(?:div|section|article|li)[^>]*>(.*?\b(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}[,.]?\s*\d{2,4}.*?)</(?:div|section|article|li)>',
            html, re.IGNORECASE | re.DOTALL
        )
        seen = set()
        for block in date_containers:
            key = block[:200]
            if key not in seen:
                seen.add(key)
                event_divs.append(('date-block', block))

    # Strategy 3: <time> tags (common in calendars)
    if len(event_divs) < 2:
        time_blocks = re.findall(r'<(?:article|div|section|li)[^>]*>.*?<time[^>]*>.*?</time>.*?</(?:article|div|section|li)>', html, re.IGNORECASE | re.DOTALL)
        for block in time_blocks:
            event_divs.append(('time-block', block))

    for cls, block in event_divs:
        text_ex = TextExtractor()
        try:
            text_ex.feed(block)
        except:
            pass
        text = text_ex.get_text()
        if len(text) < 20:
            continue

        title = ''
        title_match = re.search(r'<h[1-6][^>]*>(.*?)</h[1-6]>', block, re.IGNORECASE | re.DOTALL)
        if title_match:
            t_ex = TextExtractor()
            try:
                t_ex.feed(title_match.group(1))
                title = t_ex.get_text()
            except:
                pass
        if not title:
            s = re.split(r'[.!?]\s+', text, 1)
            title = s[0][:120] if s else text[:120]

        desc = text[:800]
        dates = parse_date(text)
        start_date = dates[0] if dates else None
        end_date = dates[1] if len(dates) > 1 else None

        is_online = bool(re.search(r'online|virtual|webinar|zoom|stream', text, re.IGNORECASE))
        is_in_person = bool(re.search(r'in-person|in person|venue|location|address|on-site', text, re.IGNORECASE))

        reg_url = None
        link_ex = LinkExtractor()
        try:
            link_ex.feed(block)
        except:
            pass
        for href, _ in link_ex.links:
            full = url_join(page_url, href)
            if re.search(r'register|signup|rsvp|ticket|book|eventbrite', full, re.IGNORECASE):
                reg_url = full
                break

        ev = {
            'title': title,
            'description': desc,
            'start_date': start_date,
            'end_date': end_date,
            'is_online': is_online,
            'is_in_person': is_in_person,
            'registration_url': reg_url,
            'event_url': page_url,
        }
        if not is_junk_event(ev):
            events.append(ev)

    # Strategy 4: If page is clearly a calendar but no structured blocks
    if not events:
        text_ex = TextExtractor()
        try:
            text_ex.feed(html)
        except:
            pass
        full_text = text_ex.get_text()

        # Count date occurrences to detect calendar pages
        date_count = len(re.findall(
            r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}[,.]?\s*\d{2,4}\b',
            full_text, re.IGNORECASE
        ))

        if date_count >= 3 or EVENT_KEYWORDS.search(full_text):
            cal_info = detect_calendar_system(html, page_url)
            if cal_info['calendar_type']:
                title = f"Calendar ({cal_info['calendar_type'].replace('_', ' ').title()})"
                desc = f"Embedded {cal_info['calendar_type']} calendar detected. {full_text[:600]}"
                if cal_info['feed_url']:
                    desc += f" Feed: {cal_info['feed_url']}"
            else:
                title = 'Events & Programs'
                desc = full_text[:1200]

            is_online = bool(re.search(r'online|virtual|webinar|zoom|stream', full_text, re.IGNORECASE))
            is_in_person = bool(re.search(r'in-person|in person|venue|location|address|on-site', full_text, re.IGNORECASE))
            ev = {
                'title': title,
                'description': desc,
                'start_date': None,
                'end_date': None,
                'is_online': is_online,
                'is_in_person': is_in_person,
                'registration_url': cal_info.get('feed_url'),
                'event_url': page_url,
            }
            if not is_junk_event(ev):
                events.append(ev)

    return dedupe_events(events)

def process_org(org_id, name, website, conn, opener):
    if not website:
        cur = conn.cursor()
        cur.execute('''
            UPDATE organizations SET has_events = 0, being_processed_since = NULL, events_scraped_at = ?
            WHERE id = ?
        ''', (datetime.now().isoformat(), org_id))
        conn.commit()
        return False, []

    if not website.startswith('http'):
        website = 'https://' + website

    base = website.rstrip('/')
    found_urls = set()
    all_events = []

    for path in EVENT_PATHS:
        url = base + path
        if should_skip_url(url):
            continue
        html = fetch(opener, url)
        if not html:
            continue
        events = extract_event_blocks(html, url)
        if events:
            found_urls.add(url)
            all_events.extend(events)
        time.sleep(0.15)

    # Also check homepage for event links
    if not all_events:
        home = fetch(opener, base + '/')
        if home:
            link_ex = LinkExtractor()
            try:
                link_ex.feed(home)
            except:
                pass
            for href, title in link_ex.links:
                low = href.lower()
                if any(k in low for k in ('event', 'calendar', 'workshop', 'retreat', 'festival', 'program')):
                    if should_skip_url(href):
                        continue
                    full = url_join(base, href)
                    if full in found_urls:
                        continue
                    h = fetch(opener, full)
                    if h:
                        evs = extract_event_blocks(h, full)
                        if evs:
                            all_events.extend(evs)
                            found_urls.add(full)
                    time.sleep(0.1)

    has_events = len(all_events) > 0

    cur = conn.cursor()
    # Final dedupe across all pages for this org
    all_events = dedupe_events(all_events)
    for ev in all_events:
        cur.execute('''
            INSERT INTO events (organization_id, title, description, event_type,
                start_date, end_date, location, is_online, is_in_person,
                registration_url, event_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            org_id, ev['title'], ev['description'], 'event',
            ev['start_date'], ev['end_date'], None,
            ev['is_online'], ev['is_in_person'],
            ev['registration_url'], ev['event_url']
        ))

    cur.execute('''
        UPDATE organizations SET has_events = ?, being_processed_since = NULL, events_scraped_at = ?
        WHERE id = ?
    ''', (has_events, datetime.now().isoformat(), org_id))
    conn.commit()
    return has_events, all_events

def claim_batch(conn, batch_size):
    cur = conn.cursor()
    conn.execute('BEGIN IMMEDIATE')
    cur.execute('''
        SELECT id, name, website FROM organizations
        WHERE website IS NOT NULL AND website != ''
          AND events_scraped_at IS NULL
          AND being_processed_since IS NULL
        ORDER BY id
        LIMIT ?
    ''', (batch_size,))
    rows = cur.fetchall()
    now = datetime.now().isoformat()
    for org_id, _, _ in rows:
        cur.execute('UPDATE organizations SET being_processed_since = ? WHERE id = ?', (now, org_id))
    conn.commit()
    return rows

def run_worker(batch_size=50):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ctx)
    )

    while True:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.execute('PRAGMA journal_mode=WAL')
        rows = claim_batch(conn, batch_size)
        if not rows:
            conn.close()
            # Wait for other workers to finish and release locks
            time.sleep(5)
            conn = sqlite3.connect(DB_PATH, timeout=30)
            conn.execute('PRAGMA journal_mode=WAL')
            rows = claim_batch(conn, batch_size)
            if not rows:
                conn.close()
                print('No more organizations to process. Exiting.')
                break

        for org_id, name, website in rows:
            try:
                has_events, events = process_org(org_id, name, website, conn, opener)
                print(f'  {org_id}: {name[:40]}... events={len(events)}')
            except Exception as e:
                print(f'  {org_id}: ERROR {e}')
                cur = conn.cursor()
                cur.execute('UPDATE organizations SET being_processed_since = NULL WHERE id = ?', (org_id,))
                conn.commit()
                continue

        conn.close()
        time.sleep(1)

if __name__ == '__main__':
    batch = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    run_worker(batch)
