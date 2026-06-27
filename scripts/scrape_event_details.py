#!/usr/bin/env python3
"""
Scrape event pages to extract:
- Exact start/end dates and times
- Online/in-person status
- Video call links (zoom, meet, teams, etc.)
Updates the events table with proper datetime values.
"""

import sqlite3
import re
import ssl
import json
import urllib.request
from urllib.parse import urlparse, urljoin
from html.parser import HTMLParser
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date
import time

import os
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'backend', 'organizations.db')
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
TIMEOUT = 12
MAX_READ = 300_000  # 300KB
MAX_WORKERS = 25

# Domains to skip (known to be problematic or not useful)
BLACKLIST_DOMAINS = {'facebook.com', 'fb.com', 'instagram.com', 'twitter.com', 'x.com'}

# Video call platform patterns
VIDEO_PATTERNS = [
    r'zoom\.us/j/\d+',
    r'zoom\.us/w/\d+',
    r'meet\.google\.com/\w+',
    r'teams\.microsoft\.com/\S+',
    r'join\.skype\.com/\S+',
    r'discord\.gg/\w+',
    r'whereby\.com/\w+',
    r'jitsi\.org/\S+',
    r'meet\.jit\.si/\w+',
    r'bigbluebutton\.org/\S+',
    r'bbb\.\S+/b/\S+',
    r'clickmeeting\.com/\S+',
    r'webex\.com/\S+',
    r'gotomeeting\.com/\S+',
    r'livestream\.com/\S+',
    r'youtube\.com/watch\?\S+',
    r'youtu\.be/\w+',
    r'twitch\.tv/\w+',
]

# Online/remote keywords
ONLINE_KEYWORDS = [
    'online', 'virtual', 'remote', 'webinar', 'livestream', 'live stream',
    'video call', 'video conference', 'zoom', 'google meet', 'teams',
    'attend online', 'join online', 'streaming', 'broadcast',
]

IN_PERSON_KEYWORDS = [
    'in person', 'in-person', 'on-site', 'onsite', 'at the farm', 'at our',
    'in portugal', 'in spain', 'in france', 'in germany', 'in italy',
    'in costa rica', 'in mexico', 'in brazil', 'in thailand', 'in india',
    'in australia', 'in usa', 'in uk', 'in netherlands', 'in ecuador',
    'at the community', 'at the ecovillage', 'on the land', 'in person at',
    'physical location', 'gather at', 'meet at', 'come to',
]


class TextExtractor(HTMLParser):
    """Extract visible text and meta/structured data from HTML."""
    def __init__(self):
        super().__init__()
        self.text_parts = []
        self._skip = False
        self._skip_depth = 0
        self.meta_tags = []
        self.script_data = []
        self.link_tags = []
        self._in_script = False
        self._script_type = None

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag in ('script', 'style', 'noscript', 'svg', 'path'):
            self._skip = True
            self._skip_depth += 1
            if tag == 'script':
                self._in_script = True
                self._script_type = attrs_dict.get('type', '')
        if tag == 'meta':
            self.meta_tags.append(attrs_dict)
        if tag == 'link':
            self.link_tags.append(attrs_dict)
        if tag == 'script' and self._script_type in ('application/ld+json', 'application/json'):
            self._in_script = True

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript', 'svg', 'path'):
            self._skip_depth -= 1
            if self._skip_depth <= 0:
                self._skip = False
                self._in_script = False

    def handle_data(self, data):
        if self._in_script and self._script_type in ('application/ld+json', 'application/json'):
            self.script_data.append(data)
        elif not self._skip:
            cleaned = data.strip()
            if cleaned:
                self.text_parts.append(cleaned)

    def get_text(self):
        return ' '.join(self.text_parts)

    def get_ldjson(self):
        """Parse JSON-LD script blocks."""
        results = []
        for raw in self.script_data:
            try:
                data = json.loads(raw)
                if isinstance(data, list):
                    results.extend(data)
                else:
                    results.append(data)
            except (json.JSONDecodeError, TypeError):
                pass
        return results


def fetch(url):
    """Fetch URL content with custom headers."""
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml,application/json,*/*',
            'Accept-Language': 'en-US,en;q=0.9',
        })
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as resp:
            content_type = resp.headers.get('Content-Type', '')
            if 'text' not in content_type and 'json' not in content_type and 'html' not in content_type:
                return None
            data = resp.read(MAX_READ)
            charset = 'utf-8'
            if 'charset=' in content_type:
                charset = content_type.split('charset=')[-1].strip()
            return data.decode(charset, errors='replace')
    except Exception:
        return None


def extract_dates_from_ldjson(ldjson_items):
    """Extract date/time info from JSON-LD structured data."""
    results = []
    for item in ldjson_items:
        if not isinstance(item, dict):
            continue
        # Handle @graph arrays
        if '@graph' in item:
            results.extend(extract_dates_from_ldjson(item['@graph']))
            continue
        
        schema_type = item.get('@type', '')
        if isinstance(schema_type, list):
            schema_type = ' '.join(schema_type)
        schema_type = str(schema_type).lower()
        
        if 'event' in schema_type or 'event' in str(item.get('@type', '')).lower():
            start = item.get('startDate') or item.get('start_date')
            end = item.get('endDate') or item.get('end_date')
            location = item.get('location', {})
            url = item.get('url', '')
            
            # Check for virtual location
            is_online = False
            is_in_person = False
            if isinstance(location, dict):
                loc_str = str(location).lower()
                if 'virtual' in loc_str or 'online' in loc_str:
                    is_online = True
                else:
                    is_in_person = True
            elif isinstance(location, str):
                if 'virtual' in location.lower() or 'online' in location.lower():
                    is_online = True
                else:
                    is_in_person = True
            
            # Check for video url
            video_url = ''
            for key in ('url', 'potentialAction'):
                val = item.get(key, '')
                if isinstance(val, dict):
                    val = val.get('url', '')
                if isinstance(val, str):
                    for pat in VIDEO_PATTERNS:
                        m = re.search(pat, val, re.IGNORECASE)
                        if m:
                            video_url = val if val.startswith('http') else ''
                            break
            
            results.append({
                'start': start,
                'end': end,
                'is_online': is_online,
                'is_in_person': is_in_person,
                'video_url': video_url,
                'url': url if isinstance(url, str) else '',
            })
    
    return results


def parse_date_string(s):
    """Parse various date string formats into ISO format."""
    if not s or not isinstance(s, str):
        return None
    
    s = s.strip()
    
    # Already ISO format
    iso_match = re.match(r'^(\d{4})-(\d{2})-(\d{2})([T ](\d{2}):(\d{2})(?::(\d{2}))?)?', s)
    if iso_match:
        try:
            year, month, day = int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3))
            hour = int(iso_match.group(5)) if iso_match.group(5) else None
            minute = int(iso_match.group(6)) if iso_match.group(6) else None
            second = int(iso_match.group(7)) if iso_match.group(7) else None
            if hour is not None:
                return datetime(year, month, day, hour, minute or 0, second or 0)
            return datetime(year, month, day)
        except (ValueError, TypeError):
            pass
    
    # Try common formats
    formats = [
        '%B %d, %Y',           # "July 11, 2021"
        '%b %d, %Y',           # "Jul 11, 2021"
        '%B %d %Y',            # "July 11 2021"
        '%b %d %Y',            # "Jul 11 2021"
        '%d %B %Y',            # "11 July 2021"
        '%d %b %Y',            # "11 Jul 2021"
        '%Y-%m-%d',
        '%m/%d/%Y',            # "07/11/2021"
        '%d/%m/%Y',            # "11/07/2021"
        '%A, %B %d, %Y',       # "Sunday, July 11, 2021"
        '%A %B %d %Y',         # "Sunday July 11 2021"
        '%B %d, %Y %I:%M %p',  # "July 11, 2021 2:00 PM"
        '%B %d, %Y at %I:%M %p',  # "July 11, 2021 at 2:00 PM"
        '%b %d, %Y %I:%M %p',
        '%Y-%m-%dT%H:%M:%S',
        '%Y-%m-%dT%H:%M',
        '%Y-%m-%d %H:%M',
        '%Y-%m-%d %H:%M:%S',
        '%d.%m.%Y',
        '%d-%m-%Y',
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt)
        except (ValueError, TypeError):
            continue
    
    # Try dateutil as fallback
    try:
        from dateutil import parser as date_parser
        return date_parser.parse(s, fuzzy=True, default=datetime(2025, 1, 1))
    except (ImportError, Exception):
        pass
    
    return None


def extract_time_from_text(text):
    """Extract time patterns from text."""
    times = []
    # "2:00 PM", "14:00", "2pm", "10:30 AM"
    time_patterns = [
        r'\b(\d{1,2}):(\d{2})\s*(AM|PM|am|pm)\b',
        r'\b(\d{1,2})\s*(AM|PM|am|pm)\b',
        r'\b(\d{1,2}):(\d{2})\b',
        r'\bat\s+(\d{1,2}):(\d{2})\s*(AM|PM|am|pm)\b',
        r'\bfrom\s+(\d{1,2}):(\d{2})\s*(AM|PM|am|pm)\b',
    ]
    for pat in time_patterns:
        matches = re.findall(pat, text)
        for m in matches:
            times.append(' '.join(m))
    return times


def extract_video_link(text, html):
    """Find video call links in text or HTML."""
    # Search in href attributes first
    href_links = re.findall(r'href=["\']([^"\']+)["\']', html or '')
    for link in href_links:
        for pat in VIDEO_PATTERNS:
            if re.search(pat, link, re.IGNORECASE):
                if not link.startswith('http'):
                    link = 'https://' + link
                return link
    
    # Search in text
    for pat in VIDEO_PATTERNS:
        m = re.search(pat, text or '', re.IGNORECASE)
        if m:
            url = m.group(0)
            if not url.startswith('http'):
                url = 'https://' + url
            return url
    
    return ''


def detect_online_status(text, title, description):
    """Detect if event is online, in-person, or both."""
    combined = f"{title} {description} {text}".lower()
    
    is_online = any(kw in combined for kw in ONLINE_KEYWORDS)
    is_in_person = any(kw in combined for kw in IN_PERSON_KEYWORDS)
    
    # If neither detected, leave both as None (unknown)
    return is_online, is_in_person


def process_event(event_id, event_url, event_title, event_desc):
    """Scrape a single event URL and extract details."""
    if not event_url:
        return None
    
    parsed = urlparse(event_url)
    domain = parsed.netloc.lower()
    
    # Skip blacklisted domains
    for bl in BLACKLIST_DOMAINS:
        if bl in domain:
            return None
    
    html = fetch(event_url)
    if not html:
        return None
    
    extractor = TextExtractor()
    try:
        extractor.feed(html)
    except Exception:
        pass
    
    text = extractor.get_text()
    ldjson_items = extractor.get_ldjson()
    
    # Try JSON-LD first (most reliable)
    start_date = None
    end_date = None
    is_online = None
    is_in_person = None
    video_url = ''
    
    ldjson_results = extract_dates_from_ldjson(ldjson_items)
    if ldjson_results:
        best = ldjson_results[0]
        start_date = parse_date_string(best.get('start', ''))
        end_date = parse_date_string(best.get('end', ''))
        if best.get('is_online'):
            is_online = True
        if best.get('is_in_person'):
            is_in_person = True
        if best.get('video_url'):
            video_url = best['video_url']
    
    # Also check meta tags for dates
    if not start_date:
        for meta in extractor.meta_tags:
            prop = meta.get('property', '') or meta.get('name', '')
            content = meta.get('content', '')
            if prop in ('og:start_date', 'article:published_time', 'event:start_time') and content:
                parsed_date = parse_date_string(content)
                if parsed_date:
                    start_date = parsed_date
                    break
            if prop in ('og:end_date', 'event:end_time') and content:
                parsed_date = parse_date_string(content)
                if parsed_date:
                    end_date = parsed_date
    
    # Try extracting dates from text if still not found
    if not start_date:
        # Look for date patterns near event-related keywords
        # Try common date patterns in text
        date_patterns = [
            r'\b(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})',
            r'\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})\b',
            r'\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})\b',
            r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2}),?\s+(\d{4})\b',
        ]
        for pat in date_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                parsed_date = parse_date_string(m.group(0))
                if parsed_date and parsed_date.year >= 2024:
                    start_date = parsed_date
                    break
    
    # Extract video link
    if not video_url:
        video_url = extract_video_link(text, html)
    
    # Detect online/in-person status
    if is_online is None and is_in_person is None:
        is_online, is_in_person = detect_online_status(text, event_title, event_desc)
    
    # Extract times if we have a date but no time
    if start_date and start_date.hour == 0 and start_date.minute == 0:
        times = extract_time_from_text(text[:5000])  # Check first 5000 chars
        if times:
            # Try to parse the first time found
            for t in times:
                try:
                    # Parse time and combine with date
                    for fmt in ['%I %p', '%I:%M %p', '%H:%M']:
                        try:
                            t_obj = datetime.strptime(t.upper().replace('AM', 'AM').replace('PM', 'PM'), fmt)
                            start_date = start_date.replace(hour=t_obj.hour, minute=t_obj.minute)
                            break
                        except (ValueError, TypeError):
                            continue
                    break
                except (ValueError, TypeError):
                    continue
    
    return {
        'event_id': event_id,
        'start_date': start_date.isoformat() if start_date else None,
        'end_date': end_date.isoformat() if end_date else None,
        'is_online': is_online,
        'is_in_person': is_in_person,
        'video_url': video_url,
    }


def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # Get unique event URLs that need scraping
    cur.execute("""
        SELECT MIN(id) as event_id, event_url, 
               MIN(title) as title, MIN(description) as description
        FROM events 
        WHERE event_url IS NOT NULL AND event_url != ''
        GROUP BY event_url
    """)
    urls_to_scrape = cur.fetchall()
    
    print(f"Total unique event URLs to scrape: {len(urls_to_scrape)}")
    
    # Also get events that already have date strings but need proper parsing
    cur.execute("""
        SELECT id, start_date, end_date FROM events 
        WHERE start_date IS NOT NULL AND typeof(start_date) = 'text'
    """)
    existing_dates = cur.fetchall()
    print(f"Events with existing date strings to parse: {len(existing_dates)}")
    
    # First, parse existing date strings into proper datetime
    parsed_count = 0
    for event_id, start_str, end_str in existing_dates:
        start_dt = parse_date_string(start_str)
        end_dt = parse_date_string(end_str) if end_str else None
        if start_dt:
            cur.execute(
                "UPDATE events SET start_date = ?, end_date = ? WHERE id = ?",
                (start_dt.isoformat(), end_dt.isoformat() if end_dt else None, event_id)
            )
            parsed_count += 1
    conn.commit()
    print(f"Parsed {parsed_count} existing date strings into proper datetimes")
    
    # Now scrape unique URLs
    print(f"\nStarting to scrape {len(urls_to_scrape)} unique URLs with {MAX_WORKERS} workers...")
    
    results = []
    completed = 0
    errors = 0
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_url = {}
        for event_id, event_url, title, desc in urls_to_scrape:
            future = executor.submit(process_event, event_id, event_url, title, desc)
            future_to_url[future] = (event_id, event_url)
        
        for future in as_completed(future_to_url):
            event_id, event_url = future_to_url[future]
            try:
                result = future.result()
                if result:
                    results.append(result)
                    completed += 1
                    if completed % 100 == 0:
                        print(f"  Progress: {completed}/{len(urls_to_scrape)} scraped, {len(results)} with data")
                        # Batch update
                        update_db(conn, results[-100:])
                else:
                    errors += 1
            except Exception as e:
                errors += 1
            
            if (completed + errors) % 500 == 0:
                print(f"  Processed: {completed + errors}/{len(urls_to_scrape)} (success: {completed}, errors: {errors})")
    
    # Final batch update
    remaining = [r for r in results if r not in results[:-100]]
    if remaining:
        update_db(conn, remaining)
    
    print(f"\nDone! Scraped {completed} URLs successfully, {errors} errors/skips")
    print(f"Total results with data: {len(results)}")
    
    # Stats
    cur.execute("SELECT COUNT(*) FROM events WHERE start_date IS NOT NULL")
    print(f"Events with start_date after scraping: {cur.fetchone()[0]}")
    cur.execute("SELECT COUNT(*) FROM events WHERE is_online = 1")
    print(f"Events marked online: {cur.fetchone()[0]}")
    cur.execute("SELECT COUNT(*) FROM events WHERE is_in_person = 1")
    print(f"Events marked in-person: {cur.fetchone()[0]}")
    cur.execute("SELECT COUNT(*) FROM events WHERE registration_url IS NOT NULL AND registration_url != ''")
    print(f"Events with registration_url: {cur.fetchone()[0]}")
    
    conn.close()


def update_db(conn, results):
    """Batch update events table with scraped data."""
    cur = conn.cursor()
    for r in results:
        event_id = r['event_id']
        
        # Get all events with this URL
        cur.execute("SELECT id FROM events WHERE event_url = (SELECT event_url FROM events WHERE id = ?)", (event_id,))
        event_ids = [row[0] for row in cur.fetchall()]
        
        for eid in event_ids:
            if r['start_date']:
                cur.execute("UPDATE events SET start_date = ? WHERE id = ? AND (start_date IS NULL OR typeof(start_date) = 'text')", 
                           (r['start_date'], eid))
            if r['end_date']:
                cur.execute("UPDATE events SET end_date = ? WHERE id = ? AND (end_date IS NULL OR typeof(end_date) = 'text')", 
                           (r['end_date'], eid))
            if r['is_online'] is not None:
                cur.execute("UPDATE events SET is_online = ? WHERE id = ?", (r['is_online'], eid))
            if r['is_in_person'] is not None:
                cur.execute("UPDATE events SET is_in_person = ? WHERE id = ?", (r['is_in_person'], eid))
            if r['video_url']:
                cur.execute("UPDATE events SET registration_url = ? WHERE id = ? AND (registration_url IS NULL OR registration_url = '')", 
                           (r['video_url'], eid))
    
    conn.commit()


if __name__ == '__main__':
    main()
