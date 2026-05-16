# API Key Requirements & Free Tiers for Enrichment Tools

## Chickadee

| API | Needs Key? | Free Tier | Rate Limit |
|-----|-----------|-----------|------------|
| **ip-api.com** | ✅ **No** (used by default) | ✓ Free | 45 req/min (unlimited for non-commercial with key) |
| **ip-api.com** (pro) | Optional key | — | Higher limits, $10/mo |
| **VirusTotal** | ✅ **Yes** | ✓ Free | 500 req/day, 4 req/min |

**Current setup**: Using ip-api.com free tier (no key needed). VirusTotal disabled unless `VT_API_KEY` env var is set.

---

## theHarvester (DNS/domain recon)

| Source | Needs Key? | Free Tier | Notes |
|--------|-----------|-----------|-------|
| **DNS** (built-in) | ❌ No | Unlimited | Resolving via system DNS |
| **Bing** | ❌ No | Rate-limited | ~50 results per query |
| **DuckDuckGo** | ❌ No | Rate-limited | ~30 results per query |
| **Brave** | ✅ Optional | ✓ Free (250/mo) | brave.com/search/api |
| **Censys** | ✅ Yes | ✓ Free (250/mo) | search.censys.io/register |
| **Shodan** | ✅ Yes | ✓ Free (50 credits/mo) | account.shodan.io |
| **Hunter** | ✅ Yes | ✓ Free (50 searches/mo) | hunter.io/api |
| **SecurityTrails** | ✅ Yes | ✓ Free (50 req/mo) | securitytrails.com/api |
| **IntelX** | ✅ Yes | ✓ Free | intelx.io |
| **VirusTotal** | ✅ Yes | ✓ Free (500/day) | virustotal.com |
| **HackerTarget** | ✅ Yes | ✓ Free (50/day) | hackertarget.com/api |
| **AlienVault OTX** | ✅ Yes | ✓ Free | otx.alienvault.com |
| **URLScan** | ✅ Yes | ✓ Free (100/day) | urlscan.io |
| **Dehashed** | ✅ Yes | ❌ Paid only | $19/mo+ |
| **GitHub** | ✅ Yes | ✓ Free (60 req/hr) | github.com/token |

**Current setup**: Using DNS + Bing (no keys needed). Good for basic reverse DNS.

---

## SpiderFoot (deep OSINT)

SpiderFoot has **200+ modules**. ~85 need API keys. The most valuable ones with free tiers:

| Module | Needs Key? | Free Tier | What It Does |
|--------|-----------|-----------|-------------|
| **AbuseIPDB** | ✅ Yes | ✓ Free (1000/day) | IP blacklist/reputation |
| **AlienVault OTX** | ✅ Yes | ✓ Free | Threat intelligence pulses |
| **GreyNoise** | ✅ Yes | ✓ Free (500 req/mo) | IP context (is it scanning the internet?) |
| **IPInfo** | ✅ Yes | ✓ Free (50k/mo) | IP → city/ISP/org/hostname |
| **IPQualityScore** | ✅ Yes | ✓ Free (5000/mo) | Fraud score, proxy/VPN/tor detection |
| **Shodan** | ✅ Yes | ✓ Free (50 credits/mo) | Open ports, services, banners |
| **SecurityTrails** | ✅ Yes | ✓ Free (50 req/mo) | Reverse DNS, subdomains |
| **Spamhaus** | ❌ No | ✓ Free | DNSBL blacklist check |
| **BGPView** | ❌ No | ✓ Free | ASN / CIDR information |
| **CIRCL** | ✅ Yes | ✓ Free | Passive DNS, malware hashes |
| **Have I Been Pwned** | ✅ Yes | ✓ Free | Email breach lookup |
| **Pulsedive** | ✅ Yes | ✓ Free (5000/mo) | IP threat scoring |
| **URLScan.io** | ✅ Yes | ✓ Free (100/day) | URL/domain screenshot + analysis |
| **DNS Lookups** | ❌ No | Unlimited | A, AAAA, MX, NS, TXT etc. |
| **WHOIS** | ❌ No | ✓ Free (rate-limited) | Domain/IP registration data |
| **OpenPorts** (built-in) | ❌ No | Unlimited | TCP port scanning |
| **Cookie/JS** (built-in) | ❌ No | Unlimited | Website content scraping |

**Current setup**: Using free/no-key modules (WHOIS, DNS, BGPView, Spamhaus, port scanning). Adding API keys would enable ~20 additional data points per IP.

---

## Recommendation: Most Impactful Free APIs to Add

| Service | Free Tier | What it adds | Signup |
|---------|----------|-------------|--------|
| **AbuseIPDB** | 1000/day | Blacklist, abuse confidence score, ISP, domain, usage type | abuseipdb.com/register |
| **Shodan** | 50 credits/mo | Open ports, services, banners, vulns | account.shodan.io |
| **IPQualityScore** | 5000/mo | Fraud score, proxy/VPN/Tor detection, mobile, carrier | ipqualityscore.com |
| **VirusTotal** | 500/day | Reputation, malicious samples, WHOIS, JARM | virustotal.com/gui/join |
| **HackerTarget** | 50/day | Open ports, DNS lookups | hackertarget.com/api |

These 5 free APIs cover almost everything the current pipeline is missing: blacklists, open ports, fraud detection, threat scoring, and security reputation.
