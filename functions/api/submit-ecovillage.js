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


export async function onRequestPost({ request, env }) {
  const opts = handleOptions(request);
  if (opts) return opts;

  let body;
  try {
    body = await request.json();
  } catch {
    return jsonResponse({ detail: 'Invalid JSON body' }, 400);
  }

  const name = (body.name || '').trim();
  const description = (body.description || '').trim();
  const country = (body.country || '').trim();
  const website = (body.website || '').trim();
  const lat = body.latitude;
  const lng = body.longitude;

  if (!name || name.length < 2) return jsonResponse({ detail: 'Name is required (min 2 characters)' }, 400);
  if (!description || description.length < 20) return jsonResponse({ detail: 'Description is required (min 20 characters)' }, 400);
  if (!country) return jsonResponse({ detail: 'Country is required' }, 400);
  if (lat == null || lng == null) return jsonResponse({ detail: 'Latitude and longitude are required' }, 400);

  const text = `${name} ${description} ${body.organization_type || ''}`;
  const matched = checkEcovillageKeywords(text);
  if (matched.length === 0) {
    return jsonResponse({
      detail: "This doesn't appear to be an ecovillage or intentional community. Please include relevant keywords in the description (e.g. 'ecovillage', 'permaculture', 'intentional community', 'sustainable', 'organic farming')."
    }, 400);
  }

  // Check for duplicate name
  const existing = await env.DB.prepare('SELECT id FROM organizations WHERE LOWER(name) = LOWER(?)').bind(name).first();
  if (existing) {
    return jsonResponse({ detail: `An organization named '${name}' already exists in the database.` }, 409);
  }

  // Insert
  const stmt = env.DB.prepare(`
    INSERT INTO organizations (name, description, organization_type, website, email, phone, address, city, region, country, postal_code, latitude, longitude, source, accepts_volunteers, accepts_visitors, accepts_shortterm, accepts_longterm, has_jobs, has_stays, has_events, direct_website, last_updated, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'user_submitted', ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
  `);
  const result = await stmt.bind(
    name, description, body.organization_type || null, website || null, body.email || null,
    body.phone || null, body.address || null, body.city || null, body.region || null,
    country, body.postal_code || null, parseFloat(lat), parseFloat(lng),
    body.accepts_volunteers ? 1 : 0, body.accepts_visitors ? 1 : 0,
    body.accepts_shortterm ? 1 : 0, body.accepts_longterm ? 1 : 0,
    body.has_jobs ? 1 : 0, body.has_stays ? 1 : 0, body.has_events ? 1 : 0,
    website || null
  ).run();

  const newId = result.meta.last_row_id;

  return jsonResponse({
    success: true,
    id: newId,
    name,
    message: `Submitted successfully! '${name}' has been added to the database and will appear on the map. It will be scraped for jobs, stays, and events on the next run.`,
    matched_keywords: matched
  });
}

export async function onRequestOptions({ request }) {
  return handleOptions(request);
}
