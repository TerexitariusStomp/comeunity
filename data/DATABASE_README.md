# Ecovillage & Intentional Community Database v4

## Overview
Global database of ecovillages, intentional communities, permaculture projects, solidarity economy initiatives, and grassroots collectives — compiled from 8 open directory sources.

**Total records: 14,839** (deduplicated from 15,149 raw entries across 8 sources)

## Schema
| Field | Type | Description |
|-------|------|-------------|
| id | int | Sequential unique ID |
| name | string | Community/organization name |
| lat | float | Latitude (WGS84) |
| lng | float | Longitude (WGS84) |
| category | string | ecovillage, permaculture_project, intentional_community, solidarity_economy, ecoversity, alternative_movement, grassroots_collective |
| sources | string[] | Origin databases (may be multiple) |
| source_urls | string[] | Links to source listings |
| country | string | ISO 3166-1 alpha-2 country code |
| city | string | City/locality |
| description | string | Short description |
| url | string | Community website |
| tags | string[] | Topic tags |

## Source Breakdown
| Source | Records | Method |
|--------|---------|--------|
| Murmurations Network | 5,357 | API pagination: index.murmurations.network/v2/nodes |
| Transiscope/GoGoCarto | 4,902 | GoGoCarto JSON API (transiscope-en.gogocarto.fr) |
| EcovillageMap.org (GEN) | 1,088 | ecovillage.org WP REST API (gen_project post type) |
| PermacultureGlobal.org | 2,314 | Regex extraction from inline JS |
| IC.org | 791 | WP REST API + Open-Meteo geocoding |
| Ecoversities | 191 | Inline JS array extraction |
| Agartha.one | 106 | /api/hubs?rating=N (found via browser network tab) |
| Diggers & Dreamers | 47 | Postcode extraction + postcodes.io geocoding |
| GTA (Global Tapestry of Alternatives) | 46 | MediaWiki API wikitext parsing |
| Crianza Mutua | 36 | MediaWiki API grupo:lugar field |

## Geographic Distribution (top 20)
| Country | Records |
|---------|---------|
| FR | 4,412 |
| GB | 3,166 |
| US | 628 |
| DE | 312 |
| EC | 156 |
| CA | 74 |
| CH | 64 |
| ES | 62 |
| AU | 53 |
| MX | 48 |
| BE | 47 |
| PT | 30 |
| IT | 19 |
| RU | 17 |
| AT | 17 |
| CR | 17 |
| IN | 16 |
| ZA | 16 |
| SE | 13 |
| CO | 12 |

~5,436 records have no country code (PermacultureGlobal entries with coords only).

## Category Distribution
| Category | Count |
|----------|-------|
| ecovillage | 6,530 |
| solidarity_economy | 4,902 |
| permaculture_project | 2,318 |
| intentional_community | 817 |
| ecoversity | 191 |
| alternative_movement | 45 |
| grassroots_collective | 36 |

## Deduplication
- **Merge key**: `(round(lat, 4), round(lng, 4))` — ~11m precision
- 133 duplicate groups merged; 42 records now have multiple sources
- When merging: prefer records with real names over generic labels

## Files
- `ecovillage_database_v4.json` — Master database (7.3 MB, 14,839 records)
- `ecovillage_database_v4.csv` — Flat file export (2.2 MB)
- `murmurations_nodes.json` — Raw Murmurations data (5,792 records)
- `ic_org_listings_geo_v2.json` — IC.org 1,105 listings (1,087 geocoded)
- `agartha_hubs.json` — Agartha hubs
- `diggers_dreamers.json` — D&D geocoded communities
- `gta_cases.json` — GTA raw data
- `crianza_mutua.json` — Crianza Mutua raw data
- `transiscope_full.json` — Transiscope raw data (5,000 records)
- `geocode_ic_v2.py` — Open-Meteo geocoder (working, verified writes)

## Pending Improvements
1. **PermacultureGlobal name enrichment** — 2,317 entries still named "PermacultureGlobal Project #N"
2. **volunteer.templeearth.cc** — Offline (Cloudflare Tunnel error 1033); needs tunnel restoration
3. **Country codes for PermacultureGlobal** — 5,436 records have no country (coords only)
4. **Transition Network** — Data exists behind auth wall; may need partner access
5. **18 IC.org entries** failed geocoding (no city/state match)

## Update Workflow
```bash
# Re-scrape Murmurations
curl -sL "https://index.murmurations.network/v2/nodes?tags=eco-village&page=1" | jq '.data'

# Re-scrape GTA MediaWiki
curl -sL "https://map.globaltapestryofalternatives.org/api.php?action=parse&page=Case:Example&prop=wikitext&format=json"

# Re-geocode IC.org (if new listings)
python geocode_ic_v2.py
```
