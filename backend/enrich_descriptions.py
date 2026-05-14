#!/usr/bin/env python3
"""Batch-enrich IC Directory org descriptions using Jina Reader API."""
import sqlite3, requests, time, re, sys

DB_PATH = '/opt/volunteer-map/backend/organizations.db'

def get_orgs_to_enrich():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, name, direct_website, directory_url 
        FROM organizations 
        WHERE description = name AND id >= 1250
        ORDER BY id
    """)
    orgs = cur.fetchall()
    conn.close()
    return orgs

def scrape_with_jina(url, timeout=15):
    """Scrape URL using Jina Reader and extract meaningful description."""
    try:
        resp = requests.get(
            f"https://r.jina.ai/{url}",
            timeout=timeout,
            headers={'Accept': 'text/plain'}
        )
        if resp.status_code != 200 or not resp.text.strip():
            return None
        
        text = resp.text.strip()
        # Find content after metadata
        idx = text.find('Markdown Content:')
        if idx == -1:
            return None
        
        content = text[idx + len('Markdown Content:'):].strip()
        
        # Split by markdown headers and get individual blocks
        blocks = re.split(r'\n(#{1,3}\s+)', content)
        current_block = ""
        
        for block in blocks:
            if re.match(r'^#{1,3}\s+$', block):
                # This is a header - process accumulated block
                if process_block(current_block):
                    return process_block(current_block)
                current_block = ""
                # Remove header from block
                continue
            current_block += block
        
        # Try the first block
        result = process_block(current_block)
        if result:
            return result
        
        # Fallback: try entire content with cleaning
        clean = clean_content(content)
        if clean and len(clean) > 60:
            return clean[:2000]
            
    except Exception as e:
        print(f"  Error: {e}", file=sys.stderr)
    return None

def process_block(text):
    """Process a content block and return if it's a good description."""
    if not text:
        return None
    
    # Clean it
    text = clean_content(text)
    if not text:
        return None
    
    # Must contain community-relevant content
    keywords = ['community', 'village', 'sustainable', 'cooperative', 'ecological',
                'intentional', 'members', 'residents', 'established', 'founded',
                'sustainability', 'eco', 'shared', 'coliving', 'cohousing']
    text_lower = text.lower()
    if not any(kw in text_lower for kw in keywords):
        return None
    
    return text[:2000]

def clean_content(text):
    """Remove markdown formatting and clean up text."""
    # Remove images
    text = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', text)
    # Remove links but keep text
    text = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', text)
    # Remove headers
    text = re.sub(r'#+\s*', '', text)
    # Remove emphasis markers
    text = re.sub(r'[\*_]{1,3}', '', text)
    # Remove list markers at start
    text = re.sub(r'^[\*\-]\s+', '', text, flags=re.M)
    # Collapse whitespace
    text = ' '.join(text.split())
    return text.strip() if text.strip() else None

def main():
    orgs = get_orgs_to_enrich()
    print(f"Found {len(orgs)} IC Directory orgs with bare names (ID >= 1250)\n")
    
    # Also get ecobasa-gen orgs that are bare
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, name, direct_website, directory_url 
        FROM organizations 
        WHERE (description = name OR description LIKE '%Markdown Content%')
        AND (direct_website IS NOT NULL OR directory_url LIKE '%ecovillage.org%')
        AND id < 1250
        ORDER BY id
        LIMIT 50
    """)
    ecobasa_orgs = cur.fetchall()
    print(f"Plus {len(ecobasa_orgs)} ecobasa/GEN orgs with bare names\n")
    
    all_orgs = []
    for org in orgs:
        all_orgs.append(org)
    for org in ecobasa_orgs:
        all_orgs.append(org)
    
    print(f"Total to process: {len(all_orgs)}\n")
    
    enriched = 0
    for i, (org_id, name, direct, directory) in enumerate(all_orgs):
        # Get best URL
        url = direct if (direct and direct.startswith('http')) else directory
        if not url or 'bipocicc' in url or 'ecobasa.org/en/communities' in url:
            # Skip bipocicc (generic) and ecobasa community pages (low quality)
            # unless it's a project page on ecovillage.org
            if directory and 'ecovillage.org/project' in directory:
                url = directory
            else:
                continue
        
        url = url.replace('](', '').rstrip(')')
        if len(url) > 150 or not url.startswith('http'):
            continue
        
        desc = scrape_with_jina(url, timeout=12)
        if desc:
            cur.execute("UPDATE organizations SET description = ? WHERE id = ?", (desc, org_id))
            enriched += 1
            print(f"✓ {enriched}. {name[:45]}")
            print(f"   URL: {url[:70]}")
            print(f"   {desc[:120]}...\n\n")
            conn.commit()
        
        time.sleep(1.2)
        
        # Progress indicator every 10
        if (i + 1) % 10 == 0:
            print(f"[Processed {i+1}, enriched {enriched} so far]\n")

    conn.commit()
    
    # Final status
    cur.execute("SELECT COUNT(*) FROM organizations WHERE description = name")
    still_bare = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM organizations WHERE description LIKE '%Markdown Content%'")
    still_bad = cur.fetchone()[0]
    
    print(f"\n{'='*60}")
    print(f"FINAL STATUS")
    print(f"{'='*60}")
    print(f"Enriched: {enriched}/{len(all_orgs)}")
    print(f"Still bare-name: {still_bare}")
    print(f"Still bad content: {still_bad}")
    
    conn.close()

if __name__ == '__main__':
    main()
