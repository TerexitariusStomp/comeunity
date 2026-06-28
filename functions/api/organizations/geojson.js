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

  let where = 'WHERE latitude IS NOT NULL AND longitude IS NOT NULL';
  const binds = [];

  if (params.get('source')) {
    where += ' AND source = ?';
    binds.push(params.get('source'));
  }
  if (params.get('accepts_volunteers') !== null) {
    where += ' AND accepts_volunteers = ?';
    binds.push(params.get('accepts_volunteers') === 'true' ? 1 : 0);
  }
  if (params.get('accepts_visitors') !== null) {
    where += ' AND accepts_visitors = ?';
    binds.push(params.get('accepts_visitors') === 'true' ? 1 : 0);
  }
  if (params.get('accepts_shortterm') !== null) {
    where += ' AND accepts_shortterm = ?';
    binds.push(params.get('accepts_shortterm') === 'true' ? 1 : 0);
  }
  if (params.get('accepts_longterm') !== null) {
    where += ' AND accepts_longterm = ?';
    binds.push(params.get('accepts_longterm') === 'true' ? 1 : 0);
  }
  if (params.get('has_jobs') !== null) {
    where += ' AND has_jobs = ?';
    binds.push(params.get('has_jobs') === 'true' ? 1 : 0);
  }
  if (params.get('has_stays') !== null) {
    where += ' AND has_stays = ?';
    binds.push(params.get('has_stays') === 'true' ? 1 : 0);
  }
  if (params.get('has_events') !== null) {
    where += ' AND has_events = ?';
    binds.push(params.get('has_events') === 'true' ? 1 : 0);
  }

  const rows = await env.DB.prepare(
    `SELECT id, name, description, website, email, phone, address, city, region, country, postal_code, latitude, longitude, source, accepts_volunteers, accepts_visitors, accepts_shortterm, accepts_longterm, has_jobs, has_stays, has_events, popup_html, organization_type FROM organizations ${where}`
  ).bind(...binds).all();

  const features = (rows.results || []).map(org => ({
    type: 'Feature',
    geometry: { type: 'Point', coordinates: [org.longitude, org.latitude] },
    properties: {
      id: org.id,
      name: org.name,
      description: org.description || '',
      popup: org.popup_html || generatePopup(org),
      source: org.source || '',
      country: org.country || '',
      city: org.city || '',
      region: org.region || '',
      address: org.address || '',
      postalCode: org.postal_code || '',
      website: org.website || '',
      email: org.email || '',
      phone: org.phone || '',
      organizationType: org.organization_type || '',
      acceptsVolunteers: !!org.accepts_volunteers,
      acceptsVisitors: !!org.accepts_visitors,
      acceptsShortterm: !!org.accepts_shortterm,
      acceptsLongterm: !!org.accepts_longterm,
      hasJobs: !!org.has_jobs,
      hasStays: !!org.has_stays,
      hasEvents: !!org.has_events,
      schemaOrg: buildSchemaOrg(org)
    }
  }));

  return jsonResponse({ type: 'FeatureCollection', features });
}

function buildSchemaOrg(org) {
  const schema = {
    '@context': 'https://schema.org',
    '@type': 'Organization',
    '@id': `https://volunteer.templeearth.cc/?org=${org.id}`,
    name: org.name,
    description: org.description || '',
    url: org.website || `https://volunteer.templeearth.cc/?org=${org.id}`,
    identifier: { '@type': 'PropertyValue', propertyID: 'ComeUnity ID', value: String(org.id) }
  };
  if (org.email) schema.email = org.email;
  if (org.phone) schema.telephone = org.phone;
  if (org.latitude && org.longitude) {
    schema.geo = {
      '@type': 'GeoCoordinates',
      latitude: org.latitude,
      longitude: org.longitude
    };
  }
  const addressParts = [org.address, org.city, org.region, org.postal_code, org.country].filter(Boolean);
  if (addressParts.length) {
    schema.address = {
      '@type': 'PostalAddress',
      streetAddress: org.address || '',
      addressLocality: org.city || '',
      addressRegion: org.region || '',
      postalCode: org.postal_code || '',
      addressCountry: org.country || ''
    };
  }
  return schema;
}

export async function onRequestOptions({ request }) {
  return handleOptions(request);
}
