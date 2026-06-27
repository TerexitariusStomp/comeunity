#!/usr/bin/env python3
"""Analyze stay booking pages to classify booking systems and flows.

Classifies booking types:
- direct_form: HTML form for booking directly on the site
- external_widget: Embedded widget (Booking.com, Airbnb, iframe, etc.)
- email_phone: Contact by email/phone to book
- external_link: Link to external booking platform
- calendar_tool: Calendar/scheduling tool (Calendly, etc.)
- unknown: Could not determine

Stores analysis in stays table.
"""
import sqlite3
import re
import time
import urllib.request
import urllib.error
from html.parser import HTMLParser
from datetime import datetime

DB_PATH = '/home/user/volunteer-map/backend/organizations.db'

BOOKING_TYPES = {
    'direct_form': 'On-site HTML form (name, email, dates, submit)',
    'external_widget': 'Embedded iframe/widget (Booking.com, Airbnb, etc.)',
    'email_phone': 'Email or phone contact required',
    'external_link': 'Link out to external booking platform',
    'calendar_tool': 'Calendly/similar scheduling tool',
    'unknown': 'Could not determine booking method',
}

STAY_PATHS = [
    'stay', 'stays', 'accommodation', 'accommodations', 'rooms', 'room',
    'book', 'booking', 'book-a-stay', 'book-now', 'reserve', 'reservation',
    'visit', 'visiting', 'guest', 'guests', 'guesthouse', 'camping', 'camp',
    'glamping', 'tent', 'retreat', 'getaway', 'overnight', 'lodging',
    'tarif', 'tarifs', 'prices', 'rates', 'hebergement', 'logement',
    'gite', 'chambre', 'chambres-dhotes',
]


class BookingAnalyzer(HTMLParser):
    def __init__(self):
        super().__init__()
        self.has_form = False
        self.has_iframe = False
        self.has_email = False
        self.has_phone = False
        self.has_calendar = False
        self.external_links = []
        self.booking_keywords = 0
        self.text = []
        self.skip_depth = 0
        self.skip_tags = {'script', 'style'}

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == 'form':
            self.has_form = True
        if tag == 'iframe':
            self.has_iframe = True
        if tag == 'a' and 'href' in attrs_dict:
            href = attrs_dict['href'].lower()
            if any(x in href for x in ['booking.com', 'airbnb', 'expedia', 'hotels.com',
                                         'reservation', 'book-now', 'checkfront', 'rezdy',
                                         'fareharbor', 'peek', 'tock', 'opentable']):
                self.external_links.append(attrs_dict['href'])
        if tag in self.skip_tags:
            self.skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self.skip_tags:
            self.skip_depth -= 1

    def handle_data(self, data):
        if self.skip_depth <= 0:
            s = data.strip()
            if s:
                self.text.append(s)

    def analyze(self):
        text = ' '.join(self.text).lower()
        self.booking_keywords = sum(1 for kw in [
            'book now', 'reserve', 'check availability', 'check-in', 'check-out',
            'arrival', 'departure', 'number of guests', 'nightly rate', 'per night',
            'availability calendar', 'select dates', 'confirm booking',
            'payment', 'credit card', 'paypal', 'stripe',
        ] if kw in text)
        self.has_email = bool(re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text))
        self.has_phone = bool(re.search(r'[\+\(]?[0-9]{1,4}[\)]?[-.\s]?[0-9]{1,4}[-.\s]?[0-9\s]{4,}', text))
        self.has_calendar = any(x in text for x in ['calendly', 'schedule', 'pick a date', 'select a time'])

    def classify(self):
        if self.has_form and self.booking_keywords >= 2:
            return 'direct_form'
        if self.has_iframe or self.external_links:
            return 'external_widget'
        if self.has_calendar:
            return 'calendar_tool'
        if self.has_email or self.has_phone:
            if self.booking_keywords >= 1:
                return 'email_phone'
        if self.external_links:
            return 'external_link'
        if self.booking_keywords >= 2:
            return 'unknown'
        return 'unknown'


def fetch(url, timeout=12):
    if not url.startswith('http'):
        url = 'https://' + url
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.status, resp.read().decode('utf-8', errors='replace'), resp.geturl()
    except Exception:
        return -1, None, url


def find_stay_url(base):
    if not base:
        return None
    if not base.startswith('http'):
        base = 'https://' + base
    base = base.rstrip('/')
    for p in STAY_PATHS:
        status, html, final = fetch(f"{base}/{p}")
        if status == 200 and html:
            low = html.lower()
            if any(k in low for k in ['stay', 'accommodation', 'room', 'book', 'guest', 'night']):
                return final
        time.sleep(0.15)
    return None


def process_all():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Add booking_type column if not exists
    try:
        cur.execute("ALTER TABLE stays ADD COLUMN booking_type VARCHAR(50)")
        conn.commit()
    except Exception:
        pass

    # Add booking_analysis JSON column
    try:
        cur.execute("ALTER TABLE stays ADD COLUMN booking_analysis TEXT")
        conn.commit()
    except Exception:
        pass

    cur.execute('''
        SELECT o.id, o.name, o.website, s.id as stay_id
        FROM organizations o
        JOIN stays s ON o.id = s.organization_id
    ''')
    rows = cur.fetchall()
    print(f"Analyzing {len(rows)} stay pages...")

    results = []
    for org_id, name, website, stay_id in rows:
        print(f"\n[{org_id}] {name}")
        stay_url = find_stay_url(website)
        if not stay_url:
            print("  No stay page found")
            cur.execute("UPDATE stays SET booking_type = 'unknown' WHERE id = ?", (stay_id,))
            conn.commit()
            continue

        status, html, final = fetch(stay_url)
        if status != 200 or not html:
            print(f"  Fetch failed ({status})")
            cur.execute("UPDATE stays SET booking_type = 'unknown' WHERE id = ?", (stay_id,))
            conn.commit()
            continue

        analyzer = BookingAnalyzer()
        try:
            analyzer.feed(html[:300000])
        except Exception:
            pass
        analyzer.analyze()
        btype = analyzer.classify()

        analysis = {
            'url': final,
            'has_form': analyzer.has_form,
            'has_iframe': analyzer.has_iframe,
            'has_email': analyzer.has_email,
            'has_phone': analyzer.has_phone,
            'has_calendar': analyzer.has_calendar,
            'external_links': analyzer.external_links[:5],
            'booking_keywords': analyzer.booking_keywords,
            'classified_as': btype,
        }

        print(f"  Type: {btype}")
        print(f"  Form: {analyzer.has_form}, Iframe: {analyzer.has_iframe}")
        print(f"  Email: {analyzer.has_email}, Phone: {analyzer.has_phone}")
        print(f"  Keywords: {analyzer.booking_keywords}")
        if analyzer.external_links:
            print(f"  External: {analyzer.external_links[:2]}")

        cur.execute('''
            UPDATE stays
            SET booking_type = ?, booking_analysis = ?
            WHERE id = ?
        ''', (btype, str(analysis), stay_id))
        conn.commit()
        results.append({'name': name, 'type': btype, 'analysis': analysis})
        time.sleep(0.5)

    conn.close()

    # Print summary
    print("\n=== Booking System Summary ===")
    from collections import Counter
    counts = Counter(r['type'] for r in results)
    for btype, count in counts.most_common():
        print(f"  {btype}: {count}")

    return results


if __name__ == '__main__':
    process_all()
