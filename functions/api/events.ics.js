function icsEscape(s) {
  if (!s) return '';
  return String(s)
    .replace(/\\/g, '\\\\')
    .replace(/;/g, '\\;')
    .replace(/,/g, '\\,')
    .replace(/\n/g, '\\n')
    .replace(/\r/g, '');
}

function toIcsDate(dt) {
  // Input is ISO-ish like "2023-02-12T00:00:00" or "2023-02-12"
  if (!dt) return '';
  const str = String(dt).replace(/[-:]/g, '').replace(/\.\d+/, '');
  return str.split('T')[0];
}

function toIcsDateTime(dt) {
  if (!dt) return '';
  return String(dt).replace(/[-:]/g, '').replace(/\.\d+/, '');
}

function handleOptions(request) {
  if (request.method === 'OPTIONS') {
    return new Response(null, {
      headers: {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type',
      },
    });
  }
  return null;
}

export async function onRequestGet({ request, env }) {
  const opts = handleOptions(request);
  if (opts) return opts;

  const url = new URL(request.url);
  const upcoming = url.searchParams.get('upcoming');

  let sql = `SELECT e.*, o.name as org_name, o.website as org_website, o.country as org_country, o.city as org_city
    FROM events e JOIN organizations o ON e.organization_id = o.id`;

  if (upcoming === 'true') {
    sql += " WHERE e.start_date >= datetime('now')";
  }

  sql += ' ORDER BY e.start_date ASC';

  const rows = await env.DB.prepare(sql).all();
  const events = rows.results || [];

  const lines = [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'PRODID:-//Global Ecovillage Map//Events//EN',
    'CALSCALE:GREGORIAN',
    'METHOD:PUBLISH',
    'X-WR-CALNAME:Ecovillage Events',
    'X-WR-TIMEZONE:UTC',
  ];

  const now = new Date().toISOString().replace(/[-:]/g, '').split('.')[0] + 'Z';

  for (const e of events) {
    const uid = `event-${e.id}@volunteer.templeearth.cc`;
    const summary = icsEscape(e.title || 'Ecovillage Event');
    const description = icsEscape(e.description || '');
    const location = icsEscape([e.location, e.org_city, e.org_country].filter(Boolean).join(', ')) || 'TBD';
    const url = e.event_url || e.registration_url || e.org_website || '';

    const start = e.start_date ? toIcsDateTime(e.start_date) : '';
    const end = e.end_date ? toIcsDateTime(e.end_date) : '';
    const hasTime = e.start_date && e.start_date.includes('T') && e.start_date.split('T')[1] !== '00:00:00';

    lines.push('BEGIN:VEVENT');
    lines.push(`UID:${uid}`);
    lines.push(`DTSTAMP:${now}`);
    lines.push(`SUMMARY:${summary}`);
    if (description) lines.push(`DESCRIPTION:${description}`);
    if (url) lines.push(`URL:${url}`);
    lines.push(`LOCATION:${location}`);

    if (start && end) {
      if (hasTime) {
        lines.push(`DTSTART:${start}`);
        lines.push(`DTEND:${end}`);
      } else {
        lines.push(`DTSTART;VALUE=DATE:${toIcsDate(e.start_date)}`);
        lines.push(`DTEND;VALUE=DATE:${toIcsDate(e.end_date)}`);
      }
    } else if (start) {
      if (hasTime) {
        lines.push(`DTSTART:${start}`);
      } else {
        lines.push(`DTSTART;VALUE=DATE:${toIcsDate(e.start_date)}`);
      }
    }

    lines.push('END:VEVENT');
  }

  lines.push('END:VCALENDAR');

  const body = lines.map(l => {
    if (l.length <= 75) return l;
    const chunks = [];
    for (let i = 0; i < l.length; i += 73) {
      const prefix = i === 0 ? '' : ' ';
      chunks.push(prefix + l.slice(i, i + 73));
    }
    return chunks.join('\r\n');
  }).join('\r\n');

  return new Response(body, {
    headers: {
      'Content-Type': 'text/calendar; charset=utf-8',
      'Content-Disposition': 'attachment; filename="ecovillage-events.ics"',
      'Access-Control-Allow-Origin': '*',
    },
  });
}

export async function onRequestOptions({ request }) {
  return handleOptions(request);
}
