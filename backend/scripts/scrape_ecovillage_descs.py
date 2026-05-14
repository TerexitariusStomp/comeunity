#!/usr/bin/env python3
"""Scrape ecovillage.org directory pages for org descriptions."""
import json, re, sqlite3, time
from urllib.request import urlopen, Request
from concurrent.futures import ThreadPoolExecutor, as_completed

db_path = "/opt/volunteer-map/backend/organizations.db"
checkpoint_path = "/opt/volunteer-map/backend/scripts/scrape_checkpoint.json"

def load_checkpoint():
    import os
    if os.path.exists(checkpoint_path):
        with open(checkpoint_path) as f:
            return json.load(f)
    return {"completed_ids": []}

def save_checkpoint(completed_ids, total_found):
    with open(checkpoint_path, 'w') as f:
        json.dump({"completed_ids": completed_ids, "total_found": total_found}, f)

def scrape(url, timeout=8):
    try:
        req = Request(url)
        req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0')
        resp = urlopen(req, timeout=timeout)
        html = resp.read().decode('utf-8', errors='replace')[:15000]
        og = re.search(r'og:description[^>]*content=["\'\' ]([^"\']+)', html)
        if og and len(og.group(1).strip()) > 30:
            return og.group(1).strip()
        p = re.search(r'entry-content[^>]*>.*?<p>(.*?)</p>', html, re.DOTALL)
        if p:
            text = re.sub(r'<[^>]+>', '', p.group(1)).strip()
            if len(text) > 30:
                return text[:800]
        return None
    except:
        return None

def main():
    with open("/root/.hermes/volunteer-map/geo_data.json") as f:
        geo = json.load(f)

    geo_urls = {}
    for d in geo:
        if d['properties']['source'] == 'ecovillage':
            m = re.search(r'p=(\d+)', d['properties']['popup'])
            if m:
                geo_urls[d['properties']['name']] = f"https://ecovillage.org/?post_type=gen_project&p={m.group(1)}"

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT id, name, website, email, accepts_volunteers, accepts_visitors, has_jobs FROM organizations WHERE source='ecovilage' AND description LIKE '%Global Ecovillage Network%'")
    rows = cur.fetchall()
    
    ckpt = load_checkpoint()
    done_ids = set(ckpt.get("completed_ids", []))
    total_found = ckpt.get("total_found", 0)
    
    remaining = [r for r in rows if r[0] not in done_ids and r[1] in geo_urls]
    print(f"Remaining: {len(remaining)}")
    
    BATCH = 50
    for i in range(0, len(remaining), BATCH):
        batch = remaining[i:i+BATCH]
        print(f"\nBatch {i+1}-{min(i+BATCH, len(remaining))} of {len(remaining)}")
        start = time.time()
        
        t0 = [(r[0], r[1], geo_urls[r[1]], r[2], r[3], r[4], r[5], r[6]) for r in batch]
        results = []
        with ThreadPoolExecutor(max_workers=4) as ex:
            futs = {ex.submit(scrape, url): (oid, nm, site, eml, vol, vis, jb) for oid, nm, url, site, eml, vol, vis, jb in t0}
            for f in as_completed(futs):
                oid, nm, site, eml, vol, vis, jb = futs[f]
                desc = f.result()
                if desc:
                    cur.execute("UPDATE organizations SET description = ? WHERE id = ?", (desc, oid))
                    done_ids.add(oid)
                    total_found += 1
                    results.append(nm)
                    # Rebuild popup_html
                    parts = [f"<strong>{nm}</strong>"]
                    dd = desc[:200] + ("..." if len(desc) > 200 else "")
                    parts.append(f"<p>{dd}</p>")
                    badges = []
                    if vol: badges.append('<span style="background:#ffc107;color:black;padding:2px 6px;border-radius:3px;margin:1px;">Volunteer</span>')
                    if vis: badges.append('<span style="background:#17a2b8;color:white;padding:2px 6px;border-radius:3px;margin:1px;">Visitors</span>')
                    if jb: badges.append('<span style="background:#dc3545;color:white;padding:2px 6px;border-radius:3px;margin:1px;">Jobs</span>')
                    if badges: parts.append(f'<div>{" ".join(badges)}</div>')
                    links = []
                    if site: links.append(f'<a href="{site}" target="_blank">🌐 Website</a>')
                    if eml: links.append(f'<a href="mailto:{eml}">Email</a>')
                    if links: parts.append("".join(links))
                    cur.execute("UPDATE organizations SET popup_html = ? WHERE id = ?", ("".join(parts), oid))
        
        conn.commit()
        save_checkpoint(list(done_ids), total_found)
        elapsed = time.time() - start
        print(f"  Found {len(results)}/{len(batch)} in {elapsed:.0f}s (total found: {total_found})")
        time.sleep(1)
    
    cur.execute("SELECT COUNT(*) FROM organizations WHERE source='ecovillage' AND description NOT LIKE '%Global Ecovillage Network%' AND description != ''")
    final = cur.fetchone()[0]
    print(f"\nDone! Ecovillage with real descriptions: {final}")
    conn.close()

if __name__ == "__main__":
    main()
