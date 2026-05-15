// Global variables
let map;
let allOrganizations = [];
let visibleOrganizations = [];
let markers = [];
let currentLocation = null;
let filters = {
    volunteer: false,
    shortterm: false,
    longterm: false,
    jobs: false
};

const MARKER_COLOR = '#007bff';
let searchScores = null; // Map<orgId, {rank, score, pct}> when search is active

// Color scale for ranked results — interpolate from red (#1) to blue (last)
function scoreToColor(score, maxScore, rank, total) {
    if (!searchScores) return MARKER_COLOR;
    // Normalize rank to 0 (top) … 1 (last)
    const t = total > 1 ? (rank - 1) / (total - 1) : 0;
    // HSL: hue goes 0 (red) → 220 (blue), lightness stays high for visibility
    const hue = Math.round(220 * t);
    return `hsl(${hue}, 85%, 55%)`;
}

// Initialize
document.addEventListener('DOMContentLoaded', function() {
    initMap();
    setupEventListeners();
    loadOrganizations();
    updateStatistics();
});

function initMap() {
    map = L.map('map', {
        zoomControl: true,
        attributionControl: true,
        preferCanvas: true
    }).setView([20, 0], 2);

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '&copy; OpenStreetMap contributors'
    }).addTo(map);

    L.control.scale().addTo(map);

    map.on('click', function() {
        map.closePopup();
    });

    map.on('locationfound', function(e) {
        const radius = e.accuracy / 2;
        L.circle(e.latlng, radius, {
            color: '#3b82f6',
            fillColor: '#3b82f6',
            fillOpacity: 0.1,
            weight: 1
        }).addTo(map);
    });
}

function setupEventListeners() {
    // Feature checkboxes
    document.querySelectorAll('.feature-checkbox').forEach(checkbox => {
        checkbox.addEventListener('change', function() {
            const feature = this.getAttribute('data-feature');
            filters[feature] = this.checked;
            filterOrganizations();
            updateMarkers();
        });
    });

    // Semantic search
    document.getElementById('semanticSearchBtn').addEventListener('click', performSemanticSearch);
    document.getElementById('semanticQuery').addEventListener('keydown', function(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            performSemanticSearch();
        }
    });

    // Filter toggle
    document.getElementById('filterToggle').addEventListener('click', function() {
        document.getElementById('filterPanel').classList.toggle('active');
    });

    // Modal close
    document.querySelector('.close-modal').addEventListener('click', closeModal);
    document.getElementById('orgDetailsModal').addEventListener('click', function(e) {
        if (e.target === this) closeModal();
    });

    // Keyboard shortcut: Escape clears active search
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            clearSemanticSearch();
        }
    });
}

// ---------------------------------------------------------------------------
// Simple location parser: extract "in <Place>" or trailing place name
// ---------------------------------------------------------------------------
function extractLocationFromQuery(query) {
    // Match "in <CapitalizedWord>" or "in <Capitalized Word(s)>" at the end of the query
    const inMatch = query.match(/\bin\s+([A-Z][a-zà-ü]{2,}(?:\s+[A-Z][a-zà-ü]{2,})?)\s*[,.]?\s*$/);
    if (inMatch) {
        const place = inMatch[1].trim();
        // Skip false positives from common English patterns
        const skipWords = ['Peace', 'Love', 'Nature', 'General', 'Need', 
                          'Practice', 'Touch', 'Person', 'People', 'World',
                          'Fact', 'Case', 'Part', 'Order', 'Place',
                          'Future', 'Present', 'Past', 'Truth', 'Kind',
                          'Question', 'Answer', 'Return', 'Spring', 'Summer',
                          'Autumn', 'Winter', 'North', 'South', 'East', 'West',
                          'Central', 'About', 'Which', 'Where', 'What'];
        if (!skipWords.includes(place)) {
            return place;
        }
    }
    return '';
}

async function loadOrganizations() {
    showLoading(true);
    try {
        const response = await fetch('/api/organizations/geojson/');
        if (!response.ok) {
            throw new Error('HTTP error! status: ' + response.status);
        }
        const data = await response.json();
        allOrganizations = data.features.map(feature => {
            const props = feature.properties;
            return {
                id: props.id,
                name: props.name,
                popup: props.popup || '',
                description: props.description || '',
                website: props.website || '',
                source: props.source,
                latitude: feature.geometry.coordinates[1],
                longitude: feature.geometry.coordinates[0],
                accepts_volunteers: props.acceptsVolunteers,
                accepts_visitors: props.acceptsVisitors,
                accepts_shortterm: props.acceptsShortterm,
                accepts_longterm: props.acceptsLongterm,
                has_jobs: props.hasJobs
            };
        });

        visibleOrganizations = allOrganizations.slice();
        createMarkers(allOrganizations);
        updateStatistics();
    } catch (error) {
        console.error('Error loading organizations:', error);
    } finally {
        showLoading(false);
    }
}

function buildPopupHtml(org) {
    const body = org.popup || '<p>' + escapeHtml(org.name) + '</p>';
    // Add match score badge when search is active
    let scoreBadge = '';
    const scoreInfo = searchScores && searchScores[org.id];
    if (scoreInfo) {
        scoreBadge = `<div style="font-size:11px;color:#666;margin:2px 0;">
            <span style="display:inline-block;background:${scoreToColor(scoreInfo.score, 1, scoreInfo.rank, scoreInfo.total)};color:white;padding:1px 8px;border-radius:10px;font-weight:600;">#${scoreInfo.rank} · ${scoreInfo.pct}% match</span>
        </div>`;
    }
    // Data source label
    const sourceLabel = getSourceLabel(org.source);
    const sourceHtml = sourceLabel
        ? `<div style="font-size:10px;color:#999;margin-top:2px;border-top:1px solid #eee;padding-top:2px;">${sourceLabel}</div>`
        : '';
    return '<div class="org-popup">' +
        scoreBadge +
        body +
        sourceHtml +
        '<br><div class="org-actions"><button class="btn view-details-btn" data-org-id="' + org.id + '">View Details</button></div>' +
        '</div>';
}

function getSourceLabel(source) {
    if (!source) return '';
    const s = source.toLowerCase();
    if (s === 'ecovillage') return 'Listed on <a href="https://ecovillage.org" target="_blank" style="color:#666;">ecovillage.org</a> (GEN)';
    if (s === 'ic-directory') return 'Listed on <a href="https://ic.org" target="_blank" style="color:#666;">ic.org</a> (FIC)';
    if (s === 'ecobasa') return 'Listed on <a href="https://ecobasa.org" target="_blank" style="color:#666;">ecobasa.org</a>';
    if (s === 'agartha') return 'Listed on <a href="https://agartha.one" target="_blank" style="color:#666;">agartha.one</a>';
    if (s === 'tribes') return 'Listed on <a href="https://ic.org" target="_blank" style="color:#666;">ic.org</a>';
    if (s === 'facebook') return 'Found on <a href="https://facebook.com" target="_blank" style="color:#666;">Facebook</a>';
    return 'Source: ' + escapeHtml(source);
}

function createMarkers(orgs) {
    markers.forEach(marker => map.removeLayer(marker));
    markers = [];

    orgs.forEach(org => {
        const color = searchScores && searchScores[org.id]
            ? scoreToColor(searchScores[org.id].score, 1, searchScores[org.id].rank, searchScores[org.id].total)
            : MARKER_COLOR;

        const icon = L.divIcon({
            className: 'custom-marker',
            html: '<i class="fas fa-map-marker-alt" style="color:' + color + '; font-size: 18px;"></i>',
            iconSize: [18, 18],
            iconAnchor: [9, 18]
        });

        const marker = L.marker([org.latitude, org.longitude], { icon: icon }).addTo(map);

        const popupContent = buildPopupHtml(org);
        marker.bindPopup(popupContent);
        marker.on('click', function() {
            setTimeout(() => {
                const popupEl = marker.getPopup().getElement();
                if (popupEl) {
                    const detailsBtn = popupEl.querySelector('.view-details-btn');
                    if (detailsBtn) {
                        detailsBtn.addEventListener('click', () => showOrganizationDetails(org.id));
                    }
                }
            }, 100);
        });
        markers.push(marker);
    });
}

function buildBadges(org) {
    let html = '';
    if (org.accepts_volunteers) html += '<span style="background:#ffc107;color:black;padding:1px 5px;border-radius:3px;margin:1px;font-size:11px;">Volunteer</span> ';
    if (org.accepts_visitors) {
        if (org.accepts_shortterm) html += '<span style="background:#17a2b8;color:white;padding:1px 5px;border-radius:3px;margin:1px;font-size:11px;">Short-term</span> ';
        if (org.accepts_longterm) html += '<span style="background:#17a2b8;color:white;padding:1px 5px;border-radius:3px;margin:1px;font-size:11px;">Long-term</span> ';
    }
    if (org.has_jobs) html += '<span style="background:#dc3545;color:white;padding:1px 5px;border-radius:3px;margin:1px;font-size:11px;">Jobs</span>';
    return html;
}

function filterOrganizations() {
    if (!filters.volunteer && !filters.shortterm && !filters.longterm && !filters.jobs) {
        visibleOrganizations = allOrganizations.slice();
        return;
    }
    visibleOrganizations = allOrganizations.filter(org => {
        if (filters.volunteer && !org.accepts_volunteers) return false;
        if (filters.shortterm && !org.accepts_shortterm) return false;
        if (filters.longterm && !org.accepts_longterm) return false;
        if (filters.jobs && !org.has_jobs) return false;
        return true;
    });
}

function updateMarkers() {
    markers.forEach(marker => map.removeLayer(marker));
    markers = [];

    visibleOrganizations.forEach(org => {
        const color = searchScores && searchScores[org.id]
            ? scoreToColor(searchScores[org.id].score, 1, searchScores[org.id].rank, searchScores[org.id].total)
            : MARKER_COLOR;

        const icon = L.divIcon({
            className: 'custom-marker',
            html: '<i class="fas fa-map-marker-alt" style="color:' + color + '; font-size: 18px;"></i>',
            iconSize: [18, 18],
            iconAnchor: [9, 18]
        });

        const marker = L.marker([org.latitude, org.longitude], { icon: icon }).addTo(map);
        const popupContent = buildPopupHtml(org);
        marker.bindPopup(popupContent);
        marker.on('click', function() {
            setTimeout(() => {
                const popupEl = marker.getPopup().getElement();
                if (popupEl) {
                    const detailsBtn = popupEl.querySelector('.view-details-btn');
                    if (detailsBtn) {
                        detailsBtn.addEventListener('click', () => showOrganizationDetails(org.id));
                    }
                }
            }, 100);
        });
        markers.push(marker);
    });
    updateStatistics();
}

function showOrganizationDetails(orgId) {
    const org = allOrganizations.find(o => o.id === orgId);
    if (!org) return;
    
    const modalBody = document.querySelector('.modal-body');
    const badgeHtml = buildBadges(org);
    
    let descHtml = '';
    const desc = org.description || '';
    if (desc && desc.length > 10) {
        descHtml = '<div class="org-section"><h4><i class="fas fa-info-circle"></i> About</h4>' +
            '<div style="max-height:250px;overflow-y:auto;padding-right:8px;line-height:1.5;font-size:14px;">' +
            escapeHtml(desc) +
            '</div></div>';
    }
    
    let linksHtml = '';
    if (org.website) {
        linksHtml = '<a href="' + escapeHtml(org.website) + '" target="_blank" style="margin-right:12px;"><i class="fas fa-globe"></i> Website</a>';
    }
    if (org.email) {
        linksHtml += '<a href="mailto:' + escapeHtml(org.email) + '" style="margin-right:12px;"><i class="fas fa-envelope"></i> Email</a>';
    }
    if (org.phone) {
        linksHtml += '<span><i class="fas fa-phone"></i> ' + escapeHtml(org.phone) + '</span>';
    }
    
    // Data source
    const sourceLabel = getSourceLabel(org.source);
    const sourceSection = sourceLabel
        ? '<div class="org-section"><h4><i class="fas fa-database"></i> Data Source</h4><div style="font-size:13px;color:#666;">' + sourceLabel + '</div></div>'
        : '';
    
    modalBody.innerHTML = 
        '<div class="org-details">' +
        '<h2 style="margin:0 0 4px;font-size:20px;">' + escapeHtml(org.name) + '</h2>' +
        '<div style="margin-bottom:12px;">' + badgeHtml + '</div>' +
        descHtml +
        '<div class="org-section"><h4><i class="fas fa-map-marked-alt"></i> Location</h4><p>Lat: ' + org.latitude.toFixed(4) + ', Lon: ' + org.longitude.toFixed(4) + '</p></div>' +
        (linksHtml ? '<div class="org-section"><h4><i class="fas fa-link"></i> Links</h4><div>' + linksHtml + '</div></div>' : '') +
        sourceSection +
        '</div>';
    
    document.getElementById('orgDetailsModal').classList.add('active');
}

function updateStatistics() {
    document.getElementById('totalOrgs').textContent = allOrganizations.length;
    document.getElementById('visibleCount').textContent = visibleOrganizations.length;
}

function showLoading(show) {
    document.getElementById('loadingIndicator').style.display = show ? 'block' : 'none';
}

function closeModal() {
    document.getElementById('orgDetailsModal').classList.remove('active');
}

// ---------------------------------------------------------------------------
// AI Search — results show ONLY on the map, no separate list
// ---------------------------------------------------------------------------
let isSearchActive = false;

function showToast(msg, isError) {
    const toast = document.getElementById('semanticToast');
    toast.textContent = msg;
    toast.style.display = 'block';
    toast.style.background = isError ? '#ffebee' : '#e8f5e9';
    toast.style.color = isError ? '#c62828' : '#2e7d32';
    // Clear the search-active indicator when showing empty/error
    if (isError) {
        isSearchActive = false;
    }
    // Auto-hide after 6 seconds
    clearTimeout(toast._hideTimer);
    toast._hideTimer = setTimeout(() => {
        toast.style.display = 'none';
    }, 6000);
}

async function performSemanticSearch() {
    const queryInput = document.getElementById('semanticQuery');
    const query = queryInput.value.trim();
    
    if (!query) {
        alert('Please describe what you are looking for.');
        return;
    }
    
    // Auto-extract location from query text
    const country = extractLocationFromQuery(query);
    
    const btn = document.getElementById('semanticSearchBtn');
    const toast = document.getElementById('semanticToast');
    
    // Clear any previous search results before starting new one
    searchScores = null;
    isSearchActive = false;

    // Show loading
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Searching...';
    btn.disabled = true;
    toast.style.display = 'none';
    
    try {
        const payload = { query: query, top_k: 200 };
        if (country) {
            payload.country = country;
        }
        
        const response = await fetch('/api/semantic-search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        if (!response.ok) {
            throw new Error('Search failed: ' + response.status);
        }
        
        const data = await response.json();
        const results = data.results || [];
        
        if (results.length > 0) {
            isSearchActive = true;
            
            // Store search scores for color-coded markers
            searchScores = {};
            const total = results.length;
            results.forEach((r, idx) => {
                // Use rank-based percentage so it's always meaningful
                // Cross-encoder logits and bi-encoder scores are on different scales
                const pct = total > 1 
                    ? Math.round(5 + 94 * (1 - idx / (total - 1)))
                    : 99;
                searchScores[r.id] = {
                    rank: idx + 1,
                    score: r.score,
                    pct: pct,
                    total: total
                };
            });
            
            // Show only matching orgs on the map
            const resultIds = results.map(r => r.id);
            visibleOrganizations = allOrganizations.filter(org => resultIds.includes(org.id));
            updateMarkers();
            
            // Zoom to show results
            if (results.length === 1) {
                map.setView([results[0].latitude, results[0].longitude], 10);
            } else {
                const bounds = L.latLngBounds(results.map(r => [r.latitude, r.longitude]));
                map.fitBounds(bounds, { padding: [50, 50] });
            }
            
            // Brief toast with match count
            let msg = `Found ${results.length} matching location${results.length !== 1 ? 's' : ''}`;
            if (country) msg += ` in ${country}`;
            msg += ` · red=best match → blue`;
            showToast(msg, false);
        } else {
            isSearchActive = false;
            let msg = 'No matching locations found';
            if (country) msg += ` in ${country}`;
            msg += '. Try a different description.';
            showToast(msg, false);
        }
        
    } catch (error) {
        console.error('Semantic search error:', error);
        showToast('Search failed. Please try again.', true);
    } finally {
        btn.innerHTML = '<i class="fas fa-search"></i> Find Matching Locations';
        btn.disabled = false;
    }
}

function clearSemanticSearch() {
    if (!isSearchActive) return;
    
    document.getElementById('semanticQuery').value = '';
    const toast = document.getElementById('semanticToast');
    toast.style.display = 'none';
    clearTimeout(toast._hideTimer);
    isSearchActive = false;
    searchScores = null;
    
    // Reset markers to show all (respecting feature filters only)
    filterOrganizations();
    updateMarkers();
}

function escapeHtml(text) {
    if (!text) return '';
    const esc = document.createElement('div');
    esc.textContent = text;
    return esc.innerHTML;
}
