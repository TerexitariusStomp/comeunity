// Inlined helpers
// Shared helpers for all API functions

function jsonResponse(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      'Content-Type': 'application/json',
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    },
  });
}

function errorResponse(detail, status = 400) {
  return jsonResponse({ detail }, status);
}

function handleOptions(request) {
  if (request.method === 'OPTIONS') {
    return new Response(null, {
      headers: {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type',
      },
    });
  }
  return null;
}

// Ecovillage keyword verification
const ECOVILLAGE_KEYWORDS = [
  'ecovillage', 'eco-village', 'eco village', 'permaculture', 'intentional community',
  'sustainable', 'organic farm', 'community', 'off-grid', 'off grid', 'homestead',
  'co-housing', 'cohousing', 'natural building', 'transition town',
  'spiritual community', 'eco-community', 'farm', 'garden', 'sustainability',
  'regenerative', 'biodynamic', 'agroecology', 'agroforestry', 'rewilding',
  'earthship', 'tiny house', 'natural living', 'simple living', 'communal',
  'collective', 'retreat', 'healing', 'wellness', 'spiritual', 'meditation',
  'yoga', 'indigenous', 'traditional', 'artisan', 'craft', 'woodland',
  'forest', 'land project', 'land trust', 'stewardship', 'volunteer',
  'woofing', 'wwOOF', 'work exchange', 'help exchange'
];

function checkEcovillageKeywords(text) {
  const lower = text.toLowerCase();
  return ECOVILLAGE_KEYWORDS.filter(kw => lower.includes(kw));
}

// Generate popup HTML for an org
function generatePopup(org) {
  const parts = [`<strong>${org.name}</strong><br>`];
  const desc = org.description || '';
  if (desc.length > 10) {
    parts.push(`<p style="max-height:200px;overflow-y:auto;font-size:12px;line-height:1.4;">${desc}</p>`);
  }
  const badges = [];
  if (org.accepts_volunteers) badges.push('<span style="background:#ffc107;color:black;padding:2px 6px;border-radius:3px;margin:1px;">Volunteer</span>');
  if (org.accepts_visitors) {
    if (org.accepts_shortterm) badges.push('<span style="background:#17a2b8;color:white;padding:2px 6px;border-radius:3px;margin:1px;">Short-term</span>');
    if (org.accepts_longterm) badges.push('<span style="background:#17a2b8;color:white;padding:2px 6px;border-radius:3px;margin:1px;">Long-term</span>');
  }
  if (org.has_jobs) badges.push('<span style="background:#dc3545;color:white;padding:2px 6px;border-radius:3px;margin:1px;">Jobs</span>');
  if (badges.length) parts.push(badges.join(' ') + '<br>');

  if (org.address) parts.push(`<div style="margin:4px 0;font-size:11px;color:#555;"><i class="fas fa-map-marker-alt" style="color:#e74c3c;"></i> ${org.address.slice(0, 150)}</div>`);

  const locParts = [org.city, org.region, org.country].filter(Boolean);
  if (locParts.length) parts.push(`<div style="margin:2px 0;font-size:11px;color:#666;font-style:italic;">${locParts.join(', ')}</div>`);

  const links = [];
  if (org.website) links.push(`<a href="${org.website}" target="_blank" style="color:#007bff;text-decoration:none;">Website</a>`);
  if (org.email) links.push(`<a href="mailto:${org.email}" style="color:#007bff;">Email</a>`);
  if (org.phone) links.push(org.phone);
  if (links.length) parts.push(`<div style="margin:4px 0;">${links.join(' | ')}</div>`);

  return parts.join(' ');
}


export async function onRequestGet({ request, env }) {
  const opts = handleOptions(request);
  if (opts) return opts;

  const url = new URL(request.url);
  const params = url.searchParams;
  const skip = parseInt(params.get('skip') || '0');
  const limit = parseInt(params.get('limit') || '100');
  const search = params.get('search');
  const upcoming = params.get('upcoming');
  const year = params.get('year');
  const month = params.get('month');
  const eventFormat = params.get('event_format');

  let sql = `SELECT e.*, o.name as org_name, o.website as org_website, o.country as org_country, o.city as org_city, o.latitude as org_lat, o.longitude as org_lon
    FROM events e JOIN organizations o ON e.organization_id = o.id`;
  const binds = [];
  const conditions = [];

  if (eventFormat === 'remote') {
    conditions.push('e.is_online = 1');
  } else if (eventFormat === 'in_person') {
    conditions.push('e.is_in_person = 1');
  }

  if (search) {
    conditions.push('(e.title LIKE ? OR e.description LIKE ? OR o.name LIKE ? OR o.country LIKE ?)');
    const s = `%${search}%`;
    binds.push(s, s, s, s);
  }

  if (upcoming === 'true') {
    conditions.push("e.start_date >= datetime('now')");
  }

  if (year) {
    const y = parseInt(year);
    conditions.push(`e.start_date >= '${y}-01-01T00:00:00' AND e.start_date < '${y + 1}-01-01T00:00:00'`);
    if (month) {
      const m = parseInt(month);
      if (m === 12) {
        conditions.push(`e.start_date >= '${y}-12-01T00:00:00' AND e.start_date < '${y + 1}-01-01T00:00:00'`);
      } else {
        conditions.push(`e.start_date >= '${y}-${String(m).padStart(2, '0')}-01T00:00:00' AND e.start_date < '${y}-${String(m + 1).padStart(2, '0')}-01T00:00:00'`);
      }
    }
  }

  let where = conditions.length ? ' WHERE ' + conditions.join(' AND ') : '';
  let orderBy = (upcoming === 'true' || year) ? ' ORDER BY e.start_date ASC' : '';
  sql += where + orderBy + ' LIMIT ? OFFSET ?';
  binds.push(limit, skip);

  const rows = await env.DB.prepare(sql).bind(...binds).all();

  const results = (rows.results || []).map(r => ({
    id: r.id,
    title: r.title,
    description: r.description,
    event_type: r.event_type,
    start_date: r.start_date,
    end_date: r.end_date,
    location: r.location,
    is_online: !!r.is_online,
    is_in_person: !!r.is_in_person,
    registration_url: r.registration_url,
    event_url: r.event_url,
    organization: {
      id: r.organization_id,
      name: r.org_name,
      website: r.org_website,
      country: r.org_country,
      city: r.org_city,
      latitude: r.org_lat,
      longitude: r.org_lon
    }
  }));

  return jsonResponse(results);
}

export async function onRequestOptions({ request }) {
  return handleOptions(request);
}
