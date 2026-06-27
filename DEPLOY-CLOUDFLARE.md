# Cloudflare Pages Deployment Guide

## Prerequisites
- Cloudflare account (free tier is sufficient)
- Node.js 18+ and npm
- This repo cloned locally

## Step 1: Install Wrangler

```bash
npm install -g wrangler
wrangler login
```

## Step 2: Create D1 Database

```bash
wrangler d1 create volunteer-map-db
```

Copy the `database_id` from the output and paste it into `wrangler.toml`:

```toml
[[d1_databases]]
binding = "DB"
database_name = "volunteer-map-db"
database_id = "PASTE_ID_HERE"
```

## Step 3: Create Tables in D1

```bash
wrangler d1 execute volunteer-map-db --file=schema.sql
```

## Step 4: Migrate Existing Data to D1

Export your SQLite data to per-table SQL files:

```bash
python3 export-to-d1.py
```

This creates `d1-organizations.sql`, `d1-volunteer_opportunities.sql`, `d1-stays.sql`, and `d1-events.sql`.

Import each table into D1:

```bash
wrangler d1 execute volunteer-map-db --remote --file=d1-organizations.sql
wrangler d1 execute volunteer-map-db --remote --file=d1-volunteer_opportunities.sql
wrangler d1 execute volunteer-map-db --remote --file=d1-stays.sql
wrangler d1 execute volunteer-map-db --remote --file=d1-events.sql
```

## Step 5: Test Locally

```bash
wrangler pages dev frontend --d1 DB=volunteer-map-db
```

This starts a local dev server at http://localhost:8788 with D1 binding.

## Step 6: Deploy to Cloudflare Pages

```bash
wrangler pages deploy frontend
```

Or connect your GitHub repo to Cloudflare Pages dashboard for automatic deploys on push.

## Step 7: Verify

- Visit your Pages URL (e.g. `https://volunteer-map.pages.dev`)
- The map should load all organizations from D1
- Submit an ecovillage via the form — it should appear on the map after reload

## API Endpoints (Pages Functions)

| Path | Method | Description |
|------|--------|-------------|
| `/api/organizations/geojson/` | GET | All orgs as GeoJSON (dynamic from D1) |
| `/api/submit-ecovillage/` | POST | Submit new ecovillage (writes to D1) |
| `/api/statistics/` | GET | Aggregate stats |
| `/api/jobs-detailed/` | GET | Jobs with org info (search, pagination) |
| `/api/stays-detailed/` | GET | Stays with org info (search, pagination) |
| `/api/events-detailed/` | GET | Events with org info (search, filter, pagination) |
| `/api/organizations/[id]/jobs` | GET | Jobs for a specific org |
| `/api/organizations/[id]/stays` | GET | Stays for a specific org |

## Notes

- The static `data/organizations.geojson` file is kept as a fallback. The frontend tries the dynamic D1 API first, then falls back to the static file.
- D1 free tier: 5M reads/day, 100k writes/day, 5GB storage — more than enough.
- The `export-to-d1.py` script can be re-run anytime to sync local SQLite to D1.
- The local SQLite database (`backend/organizations.db`) is kept only for scraping and data management. FastAPI has been removed; all serving is done by Cloudflare Pages + D1.
- For scraping new submissions: run your existing scraping scripts locally against the SQLite DB, then re-export the affected tables to D1.
