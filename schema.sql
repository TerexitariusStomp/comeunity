-- D1 schema for volunteer-map
-- Run with: npx wrangler d1 execute volunteer-map-db --file=schema.sql

CREATE TABLE IF NOT EXISTS organizations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    organization_type VARCHAR(100),
    popup_html TEXT,
    website VARCHAR(500),
    email VARCHAR(200),
    phone VARCHAR(50),
    address VARCHAR(500),
    city VARCHAR(100),
    region VARCHAR(100),
    country VARCHAR(100),
    postal_code VARCHAR(20),
    latitude FLOAT,
    longitude FLOAT,
    location VARCHAR,
    source VARCHAR(50),
    accepts_volunteers BOOLEAN DEFAULT 0,
    accepts_visitors BOOLEAN DEFAULT 0,
    accepts_shortterm BOOLEAN DEFAULT 0,
    accepts_longterm BOOLEAN DEFAULT 0,
    has_jobs BOOLEAN DEFAULT 0,
    has_stays BOOLEAN DEFAULT 0,
    has_events BOOLEAN DEFAULT 0,
    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    directory_url VARCHAR(500),
    direct_website VARCHAR(500),
    last_scrape_attempt DATETIME,
    being_processed_since DATETIME,
    events_scraped_at DATETIME,
    jobs_rescraped INTEGER DEFAULT 0,
    jobs_being_processed_since DATETIME
);

CREATE TABLE IF NOT EXISTS volunteer_opportunities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL,
    title VARCHAR(200) NOT NULL,
    description TEXT NOT NULL,
    role VARCHAR(100),
    skills_needed VARCHAR(200),
    start_date DATETIME,
    end_date DATETIME,
    commitment VARCHAR(100),
    remote_options BOOLEAN DEFAULT 0,
    application_email VARCHAR(200),
    source_url TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS stays (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL,
    title VARCHAR(200),
    description TEXT,
    stay_type VARCHAR(100),
    price_info VARCHAR(200),
    booking_type VARCHAR(50),
    booking_analysis TEXT,
    booking_url TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL,
    title VARCHAR(500),
    description TEXT,
    event_type VARCHAR(100),
    start_date DATETIME,
    end_date DATETIME,
    location VARCHAR(500),
    is_online BOOLEAN DEFAULT 0,
    is_in_person BOOLEAN DEFAULT 0,
    registration_url TEXT,
    event_url TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_orgs_country ON organizations(country);
CREATE INDEX IF NOT EXISTS idx_orgs_source ON organizations(source);
CREATE INDEX IF NOT EXISTS idx_jobs_org ON volunteer_opportunities(organization_id);
CREATE INDEX IF NOT EXISTS idx_stays_org ON stays(organization_id);
CREATE INDEX IF NOT EXISTS idx_events_org ON events(organization_id);
CREATE INDEX IF NOT EXISTS idx_events_start ON events(start_date);
