// ---------------------------------------------------------------------------
// MED Property listings: loaded LIVE from the same database that powers
// medpropertygh.com, so the 3D site always shows exactly the agency's current
// properties (title, price, photos, rooms, location). Nothing here is sample data.
// ---------------------------------------------------------------------------

export const AGENCY = {
  name: 'MED Property',
  short: 'MED',
  tagline: 'Walk through every MED Property home before you visit.',
  website: 'https://medpropertygh.com/',
  whatsapp: '233246415202',
  phone: '+233 24 641 5202',
  email: 'medproperty6@gmail.com',
};

// Public, read-only ("anon") key — the same one medpropertygh.com ships to every visitor.
const SUPABASE_URL = 'https://opdcvhgryhanqcknkztr.supabase.co';
const SUPABASE_ANON = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im9wZGN2aGdyeWhhbnFja25renRyIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTk5NDE4MzIsImV4cCI6MjA3NTUxNzgzMn0.0mH-FYtdgi1rOMZpb10t1f6jT-aayJ30k4Uk9ZNGKz8';
const FIELDS = 'id,title,description,category,listing_type,price,currency,location,region,bedrooms,bathrooms,area_sqm,image_urls,video_url,features,property_subtype,published_at';

export async function loadListings() {
  const url = `${SUPABASE_URL}/rest/v1/properties?select=${FIELDS}&status=eq.approved&order=published_at.desc.nullslast`;
  const res = await fetch(url, { headers: { apikey: SUPABASE_ANON, Authorization: `Bearer ${SUPABASE_ANON}` } });
  if (!res.ok) throw new Error(`Listings request failed (${res.status})`);
  const rows = await res.json();
  return rows.map(toListing);
}

// ---------------------------------------------------------------------------
// Turn a database row into what the 3D scene needs
// ---------------------------------------------------------------------------
const PALETTES = [
  { wall: '#f3eee6', accent: '#1f3b57', trim: '#c9a227' },
  { wall: '#efe4d2', accent: '#7a4b2a', trim: '#8a3b2e' },
  { wall: '#e9e9e4', accent: '#35524a', trim: '#4b4b4b' },
  { wall: '#fbfaf7', accent: '#111827', trim: '#b8892f' },
  { wall: '#ece6dc', accent: '#5b3e8a', trim: '#2e2e2e' },
  { wall: '#f2e9dc', accent: '#2f6b4f', trim: '#a0522d' },
];
const hash = (s) => [...s].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7);
const titleCase = (s) => s.toLowerCase().replace(/(^|[\s(–-])([a-z])/g, (m, a, b) => a + b.toUpperCase()).replace(/\bEn-Suite\b/g, 'En-suite');

function fmtPrice(p, cur, type) {
  if (p == null) return 'Price on request';
  const n = Number(p).toLocaleString('en-US', { maximumFractionDigits: 0 });
  const s = cur === 'GHS' ? `GH₵ ${n}` : cur === 'USD' ? `$${n}` : `${cur || ''} ${n}`.trim();
  return type === 'buy' ? s : `${s} / month`;
}

function styleFor(r) {
  const t = (r.title || '').toLowerCase();
  if (r.category === 'commercial' || /apartment|units|flat|studio|office|warehouse|plaza/.test(t)) return 'apartment';
  if (/townhouse|town house|terrace/.test(t)) return 'townhouse';
  const beds = r.bedrooms || 0;
  if (beds >= 5 || /luxury|mansion|villa|pool|smart/.test(t)) return 'villa';
  return beds >= 4 ? 'villa' : 'bungalow';
}

// A believable floor plan from the bedroom/bathroom counts (MED's database
// doesn't store room sizes, so sizes scale with the home's size class).
function roomsFor(r) {
  const beds = Math.max(0, Math.min(r.bedrooms || 0, 6));
  const baths = Math.max(1, Math.min(r.bathrooms || 1, 3));
  const big = beds >= 4 ? 1.15 : beds <= 1 ? 0.85 : 1;
  const z = (w, d) => [+(w * big).toFixed(1), +(d * big).toFixed(1)];
  if (r.category === 'commercial') {
    const offices = Math.max(2, Math.min(beds || 3, 6));
    return [
      ['Reception', 'living', ...z(5.5, 5)],
      ['Conference Room', 'dining', ...z(4.5, 4.5)],
      ...Array.from({ length: offices }, (_, i) => [`Office ${i + 1}`, 'study', ...z(3.6, 3.8)]),
      ['Washroom', 'bath', ...z(2.6, 3)],
    ];
  }
  const out = [['Living Room', 'living', ...z(5.8, 5)], ['Kitchen', 'kitchen', ...z(4, 4)]];
  if (beds >= 3) out.push(['Dining', 'dining', ...z(4, 4.2)]);
  if (beds >= 1) out.push([beds > 1 ? 'Master Bedroom' : 'Bedroom', 'master', ...z(4.8, 4.6)]);
  for (let i = 2; i <= beds; i++) out.push([`Bedroom ${i}`, 'bedroom', ...z(3.9, 4.1)]);
  for (let i = 1; i <= baths; i++) out.push([baths > 1 ? `Bathroom ${i}` : 'Bathroom', 'bath', ...z(2.6, 3)]);
  if (beds === 0 && r.category !== 'commercial') out.push(['Bedroom', 'master', ...z(4.2, 4.2)]);
  return out;
}

function toListing(r) {
  const pal = PALETTES[hash(r.id) % PALETTES.length];
  const feats = [...new Set((r.features || []).map((f) => titleCase(String(f).trim())).filter(Boolean))];
  const status = r.category === 'short-stay' ? 'Short Stay' : r.listing_type === 'buy' ? 'For Sale' : 'For Rent';
  return {
    id: r.id,
    title: titleCase((r.title || 'Property').trim()),
    area: [r.location, r.region].filter(Boolean).filter((v, i, a) => a.indexOf(v) === i).join(', '),
    shortArea: (r.location || r.region || '').split(',')[0],
    region: r.region || 'Other',
    price: fmtPrice(r.price, r.currency, r.listing_type),
    status,
    kind: r.category === 'commercial' ? 'commercial' : r.category === 'short-stay' ? 'short-stay' : r.listing_type,
    beds: r.bedrooms ?? '–',
    baths: r.bathrooms ?? '–',
    size: r.area_sqm ? `${r.area_sqm} m²` : '—',
    style: styleFor(r),
    ...pal,
    description: (r.description || '').trim(),
    features: feats.slice(0, 8),
    images: r.image_urls || [],
    video: r.video_url || null,
    link: AGENCY.website,
    rooms: roomsFor(r),
  };
}
