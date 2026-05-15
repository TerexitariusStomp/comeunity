"""
High-quality semantic search engine for volunteer map.

Architecture:
  - Bi-encoder: all-MiniLM-L6-v2 (fast retrieval, 384-dim, pre-computed)
  - Re-ranker:  cross-encoder/ms-marco-MiniLM-L-12-v2 (precision ranking)
  
The cross-encoder directly compares query vs each document, giving far more
accurate relevance scoring than embedding cosine similarity alone.

Also supports: country / continent filtering, multi-field search text.
"""

import os
import json
import pickle
import sqlite3
import logging
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer, CrossEncoder

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
MODEL_DIR = BASE_DIR / '.models'
DB_PATH = BASE_DIR / 'organizations.db'
EMBEDDINGS_PATH = BASE_DIR / 'org_embeddings.pkl'

# ---------------------------------------------------------------------------
# Continent mapping (country name / ISO → continent)
# ---------------------------------------------------------------------------
CONTINENT_MAP = {
    'Africa': {xa := ('africa', 'dz', 'algeria', 'ao', 'angola', 'bj', 'benin', 'bw',
        'botswana', 'bf', 'burkina faso', 'bi', 'burundi', 'cm', 'cameroon',
        'cv', 'cape verde', 'cf', 'central african republic', 'td', 'chad',
        'km', 'comoros', 'cg', 'congo', 'cd', 'democratic republic of the congo',
        'ci', "côte d'ivoire", 'dj', 'djibouti', 'eg', 'egypt', 'gq',
        'equatorial guinea', 'er', 'eritrea', 'sz', 'eswatini', 'et', 'ethiopia',
        'ga', 'gabon', 'gm', 'gambia', 'gh', 'ghana', 'gn', 'guinea',
        'gw', 'guinea-bissau', 'ke', 'kenya', 'ls', 'lesotho', 'lr', 'liberia',
        'ly', 'libya', 'mg', 'madagascar', 'mw', 'malawi', 'ml', 'mali',
        'mr', 'mauritania', 'mu', 'mauritius', 'ma', 'morocco', 'mz', 'mozambique',
        'na', 'namibia', 'ne', 'niger', 'ng', 'nigeria', 'rw', 'rwanda',
        'st', 'sao tome and principe', 'sn', 'senegal', 'sc', 'seychelles',
        'sl', 'sierra leone', 'so', 'somalia', 'za', 'south africa',
        'ss', 'south sudan', 'sd', 'sudan', 'tz', 'tanzania', 'tg', 'togo',
        'tn', 'tunisia', 'ug', 'uganda', 'zm', 'zambia', 'zw', 'zimbabwe',
        'réunion', 'reunion')},
    'Antarctica': {('antarctica', 'aq')},
    'Asia': {('asia', 'af', 'afghanistan', 'am', 'armenia', 'az', 'azerbaijan',
        'bh', 'bahrain', 'bd', 'bangladesh', 'bt', 'bhutan', 'bn', 'brunei',
        'kh', 'cambodia', 'cn', 'china', 'cy', 'cyprus', 'ge', 'georgia',
        'in', 'india', 'id', 'indonesia', 'ir', 'iran', 'iq', 'iraq',
        'il', 'israel', 'jp', 'japan', 'jo', 'jordan', 'kz', 'kazakhstan',
        'kw', 'kuwait', 'kg', 'kyrgyzstan', 'la', 'laos', 'lb', 'lebanon',
        'my', 'malaysia', 'mv', 'maldives', 'mn', 'mongolia', 'mm', 'myanmar',
        'np', 'nepal', 'kp', 'north korea', 'om', 'oman', 'pk', 'pakistan',
        'ps', 'palestine', 'ph', 'philippines', 'qa', 'qatar', 'sa', 'saudi arabia',
        'sg', 'singapore', 'kr', 'south korea', 'lk', 'sri lanka', 'sy', 'syria',
        'tw', 'taiwan', 'tj', 'tajikistan', 'th', 'thailand', 'tl', 'timor-leste',
        'tr', 'turkey', 'tm', 'turkmenistan', 'ae', 'united arab emirates',
        'uz', 'uzbekistan', 'vn', 'vietnam', 'ye', 'yemen')},
    'Europe': {('europe', 'al', 'albania', 'ad', 'andorra', 'at', 'austria',
        'by', 'belarus', 'be', 'belgium', 'ba', 'bosnia and herzegovina',
        'bg', 'bulgaria', 'hr', 'croatia', 'cz', 'czech republic',
        'dk', 'denmark', 'nl', 'netherlands', 'holland', 'ee', 'estonia',
        'fi', 'finland', 'fr', 'france', 'de', 'germany', 'gr', 'greece',
        'hu', 'hungary', 'is', 'iceland', 'ie', 'ireland', 'it', 'italy',
        'xk', 'kosovo', 'lv', 'latvia', 'li', 'liechtenstein', 'lt', 'lithuania',
        'lu', 'luxembourg', 'mt', 'malta', 'md', 'moldova', 'mc', 'monaco',
        'me', 'montenegro', 'mk', 'north macedonia', 'no', 'norway',
        'pl', 'poland', 'pt', 'portugal', 'ro', 'romania', 'ru', 'russia',
        'sm', 'san marino', 'rs', 'serbia', 'sk', 'slovakia', 'si', 'slovenia',
        'es', 'spain', 'se', 'sweden', 'ch', 'switzerland', 'ua', 'ukraine',
        'gb', 'uk', 'united kingdom')},
    'North America': {('north america', 'ag', 'antigua and barbuda', 'bs', 'bahamas',
        'bb', 'barbados', 'bz', 'belize', 'ca', 'canada', 'cr', 'costa rica',
        'cu', 'cuba', 'dm', 'dominica', 'do', 'dominican republic',
        'sv', 'el salvador', 'gd', 'grenada', 'gt', 'guatemala', 'ht', 'haiti',
        'hn', 'honduras', 'jm', 'jamaica', 'mx', 'mexico', 'ni', 'nicaragua',
        'pa', 'panama', 'kn', 'saint kitts and nevis', 'lc', 'saint lucia',
        'vc', 'saint vincent', 'tt', 'trinidad and tobago',
        'us', 'usa', 'united states')},
    'South America': {('south america', 'ar', 'argentina', 'bo', 'bolivia',
        'br', 'brazil', 'cl', 'chile', 'co', 'colombia', 'ec', 'ecuador',
        'gy', 'guyana', 'py', 'paraguay', 'pe', 'peru', 'sr', 'suriname',
        'uy', 'uruguay', 've', 'venezuela')},
    'Oceania': {('oceania', 'au', 'australia', 'fj', 'fiji', 'ki', 'kiribati',
        'mh', 'marshall islands', 'fm', 'micronesia', 'nr', 'nauru',
        'nz', 'new zealand', 'pw', 'palau', 'pg', 'papua new guinea',
        'ws', 'samoa', 'sb', 'solomon islands', 'to', 'tonga',
        'tv', 'tuvalu', 'vu', 'vanuatu')},
}

# Build reverse lookup: country_key -> continent
_COUNTRY_TO_CONTINENT = {}
# Also: set of known continent names
_CONTINENT_NAMES = {c.lower() for c in CONTINENT_MAP}

# Additional mapping: common country names/ISO codes to their DB-safe uppercase form
# This maps user inputs like 'Brazil', 'BR' -> 'BR' (the DB value)
_COUNTRY_ISO_MAP = {
    # South America
    'argentina': 'AR', 'ar': 'AR',
    'bolivia': 'BO', 'bo': 'BO',
    'brazil': 'BR', 'br': 'BR',
    'chile': 'CL', 'cl': 'CL',
    'colombia': 'CO', 'co': 'CO',
    'ecuador': 'EC', 'ec': 'EC',
    'guyana': 'GY', 'gy': 'GY',
    'paraguay': 'PY', 'py': 'PY',
    'peru': 'PE', 'pe': 'PE',
    'suriname': 'SR', 'sr': 'SR',
    'uruguay': 'UY', 'uy': 'UY',
    'venezuela': 'VE', 've': 'VE',
    # North / Central America
    'canada': 'CA', 'ca': 'CA',
    'united states': 'US', 'us': 'US', 'usa': 'US',
    'mexico': 'MX', 'mx': 'MX',
    'costa rica': 'CR', 'cr': 'CR',
    'guatemala': 'GT', 'gt': 'GT',
    'honduras': 'HN', 'hn': 'HN',
    'nicaragua': 'NI', 'ni': 'NI',
    'panama': 'PA', 'pa': 'PA',
    'el salvador': 'SV', 'sv': 'SV',
    'cuba': 'CU', 'cu': 'CU',
    'dominican republic': 'DO', 'do': 'DO',
    'haiti': 'HT', 'ht': 'HT',
    'jamaica': 'JM', 'jm': 'JM',
    'trinidad and tobago': 'TT', 'tt': 'TT',
    'belize': 'BZ', 'bz': 'BZ',
    'bahamas': 'BS', 'bs': 'BS',
    'barbados': 'BB', 'bb': 'BB',
    # Europe
    'united kingdom': 'GB', 'gb': 'GB', 'uk': 'GB',
    'france': 'FR', 'fr': 'FR',
    'germany': 'DE', 'de': 'DE',
    'spain': 'ES', 'es': 'ES',
    'italy': 'IT', 'it': 'IT',
    'portugal': 'PT', 'pt': 'PT',
    'netherlands': 'NL', 'nl': 'NL', 'holland': 'NL',
    'switzerland': 'CH', 'ch': 'CH',
    'austria': 'AT', 'at': 'AT',
    'belgium': 'BE', 'be': 'BE',
    'sweden': 'SE', 'se': 'SE',
    'denmark': 'DK', 'dk': 'DK',
    'norway': 'NO', 'no': 'NO',
    'finland': 'FI', 'fi': 'FI',
    'iceland': 'IS', 'is': 'IS',
    'ireland': 'IE', 'ie': 'IE',
    'greece': 'GR', 'gr': 'GR',
    'poland': 'PL', 'pl': 'PL',
    'czech republic': 'CZ', 'cz': 'CZ',
    'romania': 'RO', 'ro': 'RO',
    'hungary': 'HU', 'hu': 'HU',
    'russia': 'RU', 'ru': 'RU',
    'ukraine': 'UA', 'ua': 'UA',
    'croatia': 'HR', 'hr': 'HR',
    'serbia': 'RS', 'rs': 'RS',
    # Asia
    'india': 'IN', 'in': 'IN',
    'japan': 'JP', 'jp': 'JP',
    'thailand': 'TH', 'th': 'TH',
    'china': 'CN', 'cn': 'CN',
    'nepal': 'NP', 'np': 'NP',
    'indonesia': 'ID', 'id': 'ID',
    'israel': 'IL', 'il': 'IL',
    'turkey': 'TR', 'tr': 'TR',
    'vietnam': 'VN', 'vn': 'VN',
    'philippines': 'PH', 'ph': 'PH',
    'south korea': 'KR', 'kr': 'KR',
    'taiwan': 'TW', 'tw': 'TW',
    'malaysia': 'MY', 'my': 'MY',
    # Africa
    'south africa': 'ZA', 'za': 'ZA',
    'ghana': 'GH', 'gh': 'GH',
    'kenya': 'KE', 'ke': 'KE',
    'morocco': 'MA', 'ma': 'MA',
    'ethiopia': 'ET', 'et': 'ET',
    'tanzania': 'TZ', 'tz': 'TZ',
    'uganda': 'UG', 'ug': 'UG',
    'nigeria': 'NG', 'ng': 'NG',
    'egypt': 'EG', 'eg': 'EG',
    # Oceania
    'australia': 'AU', 'au': 'AU',
    'new zealand': 'NZ', 'nz': 'NZ',
}


def country_to_continent(country_name: str) -> str:
    """Resolve a country name or ISO code to a continent name."""
    if not country_name:
        return ''
    key = country_name.strip().lower()
    # Remove parenthetical notes like 'CR (Costa Rica)'
    space_idx = key.find(' ')
    if space_idx > 0:
        key = key[:space_idx]
    return _COUNTRY_TO_CONTINENT.get(key, '')


def resolve_location_filter(country: str):
    """Resolve 'country' param — may be continent, country name, or ISO code.
    
    - 'South America', 'Europe', 'Africa' → continent filter (all countries in continent)
    - 'Brazil', 'BR', 'Costa Rica', 'CR' → specific country filter
    Returns (set_of_allowed_upper_countries_or_None, continent_or_empty, is_continent_bool).
    """
    if not country or not country.strip():
        return None, '', False

    key = country.strip().lower()

    # Check if it's a continent name first
    if key in _CONTINENT_NAMES:
        allowed = set()
        for continent_name, country_sets in CONTINENT_MAP.items():
            if continent_name.lower() == key:
                for country_set in country_sets:
                    for c in country_set:
                        if c != continent_name.lower():  # skip the continent entry itself
                            allowed.add(c.upper())
        return allowed, continent_name, True

    # Not a continent — it's a specific country name or ISO code
    # Look up in the ISO map to get the DB-safe country code
    iso_code = _COUNTRY_ISO_MAP.get(key)
    if iso_code:
        return {iso_code}, '', False
    
    # Try the raw uppercased input as fallback
    return {key.upper()}, '', False


# ---------------------------------------------------------------------------
# Location auto-detection from query text
# ---------------------------------------------------------------------------

# Set of known place names for fast lookup (generated from _COUNTRY_ISO_MAP)
_PLACE_NAMES = set(k for k in _COUNTRY_ISO_MAP
                    if not k.isupper() and len(k) > 2)
# Also include continent names
for cn in _CONTINENT_NAMES:
    _PLACE_NAMES.add(cn)


def extract_location_from_query(query: str):
    """Detect and extract a location mention from a user query.
    
    Handles patterns:
      - "permaculture in Brazil" → ("permaculture", "Brazil")
      - "tech forward ecovillage Argentina" → ("tech forward ecovillage", "Argentina")
      - "eco village in Europe" → ("eco village", "Europe")
      - "organic farm Costa Rica" → ("organic farm", "Costa Rica")
    
    Returns (cleaned_query: str, country_or_none: str | None).
    The cleaned query has the location mention stripped so it doesn't
    pollute the semantic search — the location is applied as a filter.
    """
    if not query:
        return query, None
    
    text = query.strip()
    
    # Pattern 1: "something in <Place>" at end
    import re
    m = re.search(r'\bin\s+([A-Z][a-zà-ü]{2,}(?:\s+[A-Z][a-zà-ü]{2,})?)\s*$', text)
    if m:
        place = m.group(1)
        place_key = place.lower()
        if place_key in _COUNTRY_ISO_MAP or place_key in _CONTINENT_NAMES:
            cleaned = text[:m.start()].strip().rstrip(',').strip()
            # Resolve to country code
            allowed, _, _ = resolve_location_filter(place)
            if allowed:
                # For continent, pass the continent name; for country, pass ISO
                resolved = place if place_key in _CONTINENT_NAMES else next(iter(allowed))
                return cleaned, resolved
    
    # Pattern 2: trailing standalone country/continent name (no "in")
    # Try last word first
    words = text.split()
    if len(words) >= 2:
        last_word = words[-1].lower()
        # Remove trailing punctuation
        last_word_stripped = last_word.rstrip(',.!?;')
        if last_word_stripped in _COUNTRY_ISO_MAP:
            # Found a country name at the end
            cleaned = ' '.join(words[:-1])
            iso = _COUNTRY_ISO_MAP[last_word_stripped]
            return cleaned, iso
        
        if last_word_stripped in _CONTINENT_NAMES:
            cleaned = ' '.join(words[:-1])
            return cleaned, last_word_stripped.title()
        
        # Try last two words (e.g. "Costa Rica", "South Africa", "New Zealand")
        if len(words) >= 2:
            last_two = ' '.join(w.lower() for w in words[-2:])
            if last_two in _COUNTRY_ISO_MAP:
                cleaned = ' '.join(words[:-2])
                iso = _COUNTRY_ISO_MAP[last_two]
                return cleaned, iso
    
    return query, None


# ---------------------------------------------------------------------------
# Build search text
# ---------------------------------------------------------------------------
def build_search_text(org: dict) -> str:
    """Build a rich search document for better matching across fields."""
    parts = [org.get('name', '')]
    org_type = org.get('organization_type') or ''
    if org_type:
        parts.append(org_type)
    desc = org.get('description', '') or ''
    if desc:
        parts.append(desc)
    country = org.get('country', '') or ''
    if country:
        parts.append(country)
    city = org.get('city', '') or ''
    if city:
        parts.append(city)
    return ' '.join(p for p in parts if p)


# ---------------------------------------------------------------------------
# SemanticEngine class
# ---------------------------------------------------------------------------
class SemanticEngine:
    """High-quality semantic search with bi-encoder retrieval + cross-encoder re-ranking."""

    def __init__(self, device: str = 'cpu'):
        self.device = device
        self.model = None
        self.reranker = None
        self.org_ids: list[int] = []
        self.embeddings: np.ndarray = None  # (N, dim), normalized

        self._load_models()
        self._load_index()

    def _load_models(self):
        import time
        t0 = time.time()

        # Load bi-encoder (all-MiniLM-L6-v2)
        from sentence_transformers import SentenceTransformer
        local_path = str(MODEL_DIR / 'all-MiniLM-L6-v2')
        if os.path.exists(local_path):
            self.model = SentenceTransformer(local_path, device=self.device)
        else:
            self.model = SentenceTransformer('all-MiniLM-L6-v2', device=self.device)
            os.makedirs(MODEL_DIR, exist_ok=True)
            self.model.save(local_path)

        logger.info(f"Bi-encoder loaded in {time.time()-t0:.1f}s — dim={self.model.get_sentence_embedding_dimension()}")

        # Load cross-encoder for re-ranking
        t0 = time.time()
        local_ce = str(MODEL_DIR / 'cross-encoder-ms-marco-MiniLM-L-12-v2')
        reranker_path = local_ce if os.path.exists(local_ce) else 'cross-encoder/ms-marco-MiniLM-L-12-v2'
        self.reranker = CrossEncoder(reranker_path, device=self.device)
        logger.info(f"Cross-encoder loaded in {time.time()-t0:.1f}s")

    def _load_index(self):
        """Load pre-computed embeddings from disk."""
        if EMBEDDINGS_PATH.exists():
            with open(EMBEDDINGS_PATH, 'rb') as f:
                data = pickle.load(f)
            self.org_ids = data['ids']
            self.embeddings = data['embeddings']
            logger.info(f"Loaded {len(self.org_ids)} embeddings — shape={self.embeddings.shape}")
        else:
            logger.warning(f"No embeddings found. Run build_index() first.")
            self.org_ids = []
            self.embeddings = np.array([])

    def _get_orgs_batch(self, ids: list[int]) -> list[dict]:
        """Fetch org details from DB for given IDs."""
        if not ids:
            return []
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        placeholders = ','.join('?' for _ in ids)
        rows = conn.execute(f"""
            SELECT id, name, description, website, latitude, longitude,
                   city, region, country, accepts_volunteers, accepts_visitors,
                   accepts_shortterm, accepts_longterm, has_jobs
            FROM organizations WHERE id IN ({placeholders})
        """, ids).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def search(self, query: str, top_k: int = 20,
               country: str = None) -> list[dict]:
        """High-quality semantic search with cross-encoder re-ranking.
        
        If no country is specified, auto-detects location mentions in the
        query text (e.g. "ecovillage Argentina", "permaculture in Brazil").
        """
        if not query or not len(self.org_ids):
            return []

        # Auto-detect location from query text if not explicitly provided
        original_query = query
        if not country:
            _, detected = extract_location_from_query(query)
            if detected:
                country = detected
                logger.info(f"Auto-detected country={country!r} from: {query!r}")
                # Keep original query for encoding — the location name adds useful signal
                # The country filter ensures only target-country results are returned

        # 1. Encode query
        q_vec = self.model.encode([query], normalize_embeddings=True)[0]

        # 2. Cosine similarity retrieval (fast dot product on normalized vectors)
        similarities = np.dot(self.embeddings, q_vec)

        # 3. Retrieve generous candidates for re-ranking
        # Always scan enough to catch orgs from target country when filtering
        retrieval_k = min(300, len(self.org_ids))
        if country:
            retrieval_k = min(1000, len(self.org_ids))
        top_indices = np.argsort(-similarities)[:retrieval_k]
        top_ids = [self.org_ids[i] for i in top_indices]
        top_scores = [float(similarities[i]) for i in top_indices]

        # 4. Fetch orgs from DB
        orgs = self._get_orgs_batch(top_ids)
        org_map = {o['id']: o for o in orgs}

        # 5. Apply location filter
        allowed_countries, continent_name, is_continent = resolve_location_filter(country) if country else (None, '', False)

        candidates = []
        for idx, org_id in enumerate(top_ids):
            org = org_map.get(org_id)
            if not org:
                continue
            if allowed_countries:
                org_country = (org.get('country') or '').upper().strip()
                if org_country not in allowed_countries:
                    continue
            org['_score'] = top_scores[idx]
            candidates.append(org)
            if len(candidates) >= top_k * 3:
                break

        if not candidates:
            return []

        # 6. Cross-encoder re-ranking — capped for performance on CPU
        # Top N get cross-encoder precision; rest sorted by bi-encoder score
        CE_CAP = 30
        ce_batch = candidates[:CE_CAP]
        remainder = candidates[CE_CAP:]

        if ce_batch:
            pairs = [(query, build_search_text(org)) for org in ce_batch]
            rerank_scores = self.reranker.predict(pairs, show_progress_bar=False)
            # Apply sigmoid to normalize cross-encoder logits to 0-1 range
            # so they're comparable with bi-encoder cosine similarity scores
            rerank_scores = 1.0 / (1.0 + np.exp(-np.array(rerank_scores)))
            reranked = sorted(zip(ce_batch, rerank_scores), key=lambda x: x[1], reverse=True)
        else:
            reranked = []

        # Append remainder sorted by bi-encoder similarity score
        remainder.sort(key=lambda x: x['_score'], reverse=True)

        # Merge: cross-encoder results first, then bi-encoder remainder
        all_scored = [(org, score) for org, score in reranked]
        all_scored += [(org, org['_score']) for org in remainder]
        all_scored = all_scored[:top_k]

        # Build response
        results = []
        for org, score in all_scored:
            desc = (org.get('description') or '')[:300]
            results.append({
                'id': org['id'],
                'name': org['name'],
                'country': org.get('country', ''),
                'city': org.get('city', ''),
                'latitude': org.get('latitude'),
                'longitude': org.get('longitude'),
                'score': round(float(score), 4),
                'accepts_volunteers': bool(org.get('accepts_volunteers')),
                'accepts_shortterm': bool(org.get('accepts_shortterm')),
                'accepts_longterm': bool(org.get('accepts_longterm')),
                'accepts_visitors': bool(org.get('accepts_visitors')),
                'has_jobs': bool(org.get('has_jobs')),
                'description': desc,
            })

        return results

    def build_index(self, force: bool = False):
        """Compute and save embeddings for ALL orgs."""
        if EMBEDDINGS_PATH.exists() and not force:
            logger.info("Embeddings already exist. Use force=True to rebuild.")
            self._load_index()
            return

        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT id, name, organization_type, description, city, country
            FROM organizations
        """).fetchall()
        conn.close()

        texts = []
        ids = []
        for row in rows:
            org = dict(row)
            text = build_search_text(org)
            if text.strip():
                texts.append(text)
                ids.append(org['id'])

        logger.info(f"Encoding {len(texts)} texts with all-MiniLM-L6-v2...")
        embeddings = self.model.encode(texts, show_progress_bar=True,
                                        normalize_embeddings=True)

        with open(EMBEDDINGS_PATH, 'wb') as f:
            pickle.dump({'ids': ids, 'embeddings': embeddings}, f)

        self.org_ids = ids
        self.embeddings = embeddings
        logger.info(f"Saved {len(ids)} embeddings — shape={embeddings.shape}")


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_engine: SemanticEngine = None

def get_engine() -> SemanticEngine:
    global _engine
    if _engine is None:
        _engine = SemanticEngine()
    return _engine


if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO)
    force = '--force' in sys.argv
    eng = get_engine()
    eng.build_index(force=force)
