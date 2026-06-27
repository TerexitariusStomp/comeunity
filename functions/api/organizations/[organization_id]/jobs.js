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


export async function onRequestGet({ request, env, params }) {
  const opts = handleOptions(request);
  if (opts) return opts;

  const orgId = params.organization_id;
  const rows = await env.DB.prepare(
    'SELECT id, title, description, role, commitment, source_url, application_email, skills_needed, remote_options FROM volunteer_opportunities WHERE organization_id = ?'
  ).bind(orgId).all();

  return jsonResponse((rows.results || []).map(r => ({
    id: r.id,
    title: r.title,
    description: r.description,
    role: r.role,
    commitment: r.commitment,
    source_url: r.source_url,
    application_email: r.application_email,
    skills_needed: r.skills_needed,
    remote_options: !!r.remote_options,
  })));
}

export async function onRequestOptions({ request }) {
  return handleOptions(request);
}
