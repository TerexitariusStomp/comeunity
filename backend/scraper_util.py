#!/usr/bin/env python3
import sqlite3, sys, re, subprocess

def fetch_meta_desc(url, timeout=6):
    "Fetch page and extract meta description using curl"
    try:
        result = subprocess.run(
            ['curl', '-s', '--max-time', str(timeout), '--connect-timeout', '3', '-L',
             '-A', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'],
            input=url + '\n', capture_output=True, text=True
        )
        if result.returncode != 0:
            # curl with -d doesn't work, try direct URL
            result2 = subprocess.run(
                ['curl', '-s', '--max-time', str(timeout), '--connect-timeout', '3', '-L',
                 '-A', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)', url],
                capture_output=True, text=True, timeout=timeout+2
            )
            if result2.returncode != 0:
                return None
            content = result2.stdout
        else:
            content = result.stdout
            
        # Parse meta description
        match = re.search(r'<meta\s+[^>]*name=["']description["'][^>]*content=["']([^"']+)["']', content, re.I)
        if match:
            desc = match.group(1).strip()
            if len(desc) > 40:
                return desc
        
        # Fallback: find first substantial paragraph
        text = re.sub(r'<[^>]+>', ' ', content)
        sentences = [s.strip() for s in text.split('\n') if len(s.strip()) > 50]
        if sentences:
            return sentences[0][:500]
    except Exception as e:
        pass
    return None

if __name__ == '__main__':
    db_path = '/opt/volunteer-map/backend/organizations.db'
    url = sys.argv[1] if len(sys.argv) > 1 else None
    
    if url:
        desc = fetch_meta_desc(url)
        if desc:
            print(desc[:500])
        else:
            sys.exit(1)
