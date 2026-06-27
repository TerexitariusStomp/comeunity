#!/usr/bin/env python3
"""Scrape accommodation/stay booking pages from organization websites.

Checks common paths like /stay, /visit, /accommodation, /book, /rooms, /guests
and extracts stay booking information.
"""
import sqlite3
import re
import time
import urllib.request
import urllib.error
from html.parser import HTMLParser
from datetime import datetime

DB_PATH = '/home/user/volunteer-map/backend/organizations.db'

STAY_PATHS = [
    'stay', 'stays', 'accommodation', 'accommodations', 'rooms', 'room',
    'book', 'booking', 'book-a-stay', 'book-now', 'reserve', 'reservation',
    'visit', 'visiting', 'guest', 'guests', 'guesthouse', 'guest-house',
    'hostel', 'bnb', 'bed-and-breakfast', 'camping', 'camp', 'glamping',
    'tent', 'airbnb', 'holiday', 'vacation', 'rental', 'rentals',
    'retreat', 'retreats', 'getaway', 'hospitality', 'overnight',
    'lodging', 'sleep', 'place-to-stay', 'where-to-stay', 'en/stay',
    'en/accommodation', 'en/visit', 'tarif', 'tarifs', 'prices', 'rates',
    'hebergement', 'logement', 'gite', 'chambre', 'chambres-dhotes',
]


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
        self.skip_tags = {'script', 'style', 'nav'}
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.skip_tags:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self.skip_tags:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth <= 0:
            stripped = data.strip()
            if stripped:
                self.text.append(stripped)

    def get_text(self):
        raw = ' '.join(self.text)
        return re.sub(r'\s+', ' ', raw).strip()


def fetch_url(url, timeout=15):
    if not url.startswith('http'):
        url = 'https://' + url
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        resp = urllib.request.urlopen(req, timeout=timeout)
        html = resp.read().decode('utf-8', errors='replace')
        return resp.status, html, resp.geturl()
    except urllib.error.HTTPError as e:
        return e.code, None, url
    except Exception as e:
        return -1, None, url


def check_stay_page(base_url):
    if not base_url:
        return False, None, None
    if not base_url.startswith('http'):
        base_url = 'https://' + base_url
    base_url = base_url.rstrip('/')

    for path in STAY_PATHS:
        url = f"{base_url}/{path}"
        status, html, final_url = fetch_url(url)
        if status == 200 and html:
            stay_terms = [
                'stay with us', 'book your stay', 'book a room', 'book now',
                'accommodation', 'where to stay', 'overnight', 'guest room',
                'camping', 'glamping', 'rent a room', 'chambre', 'hebergement',
                'gite', 'bed and breakfast', 'bnb', 'hostel', 'book a bed',
                'reserve your spot', 'reservation', 'booking form', 'nightly rate',
                'per night', 'per person', 'tarif', 'price per night', 'room rate',
                'check in', 'check-in', 'check out', 'check-out', 'available dates',
            ]
            try:
                extractor = TextExtractor()
                extractor.feed(html)
                text = extractor.get_text()
                text_lower = text.lower()
                score = sum(1 for t in stay_terms if t in text_lower)
                if score >= 2 and len(text) > 150:
                    return True, final_url, text
            except Exception:
                pass
        time.sleep(0.3)
    return False, None, None


def extract_stay_listings(text, page_url):
    listings = []
    sentences = text.split('. ')
    title = sentences[0][:200] if sentences else 'Stay/Accommodation'
    listings.append({
        'title': title,
        'description': text[:2000],
        'stay_type': 'accommodation',
    })
    return listings


def process_batch(limit=50, offset=0):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute('''
        SELECT id, name, website 
        FROM organizations 
        WHERE website IS NOT NULL AND website != ''
        AND (has_stays IS NULL OR has_stays = 0)
        ORDER BY id
        LIMIT ? OFFSET ?
    ''', (limit, offset))
    orgs = cur.fetchall()

    if not orgs:
        print("No more organizations to process.")
        conn.close()
        return 0

    found_count = 0
    for org_id, name, website in orgs:
        print(f"Checking: {name} -> {website}")
        has_stays, stay_url, text = check_stay_page(website)

        if has_stays and text:
            found_count += 1
            print(f"  FOUND stay page: {stay_url}")
            cur.execute('UPDATE organizations SET has_stays = 1 WHERE id = ?', (org_id,))
            listings = extract_stay_listings(text, stay_url)
            for listing in listings:
                cur.execute('''
                    INSERT INTO stays (organization_id, title, description, stay_type, created_at)
                    VALUES (?, ?, ?, ?, ?)
                ''', (org_id, listing['title'], listing['description'],
                      listing['stay_type'], datetime.now().isoformat()))
        else:
            cur.execute('UPDATE organizations SET has_stays = 0 WHERE id = ?', (org_id,))

        conn.commit()
        time.sleep(0.5)

    conn.close()
    return found_count


if __name__ == '__main__':
    import sys
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    offset = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    print(f"Processing batch: limit={limit}, offset={offset}")
    found = process_batch(limit, offset)
    print(f"Found {found} organizations with stay booking pages in this batch.")
