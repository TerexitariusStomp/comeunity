// Global variables
let map;
let allOrganizations = [];
window.allOrganizations = allOrganizations;
let visibleOrganizations = [];
let markers = [];
let currentLocation = null;
let filters = {
    jobs: false,
    stays: false,
    events: false
};
let toggleBtn, filterPanel, mapControls; // for responsive drawer

const MARKER_COLOR = '#3b82f6';
let searchScores = null; // Map<orgId, {rank, score, pct}> when search is active
let searchResultIds = null; // Array of org IDs from current AI search

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
    loadOrganizations().then(() => {
        handleOrgQueryParam();
    });
    updateStatistics();
    // Load embedding index and init WebLLM in background
    initSearch();
});

function handleOrgQueryParam() {
    const params = new URLSearchParams(window.location.search);
    const orgId = params.get('org');
    if (!orgId) return;
    const id = parseInt(orgId, 10);
    if (!id || !allOrganizations.length) return;
    const org = allOrganizations.find(o => o.id === id);
    if (org) {
        showOrganizationDetails(id);
        if (org.latitude && org.longitude) {
            map.setView([org.latitude, org.longitude], 12);
        }
    }
}

function setAIStatus(text, state) {
    const status = document.getElementById('aiStatus');
    const icon = document.getElementById('aiStatusIcon');
    const statusText = document.getElementById('aiStatusText');
    const bar = document.getElementById('aiProgressBar');
    if (!status) return;
    status.style.display = 'block';
    statusText.textContent = text;
    if (state === 'loading') {
        status.style.background = '#162a1e';
        status.style.color = '#7da882';
        icon.className = 'fas fa-circle-notch fa-spin';
        icon.style.marginRight = '6px';
        bar.style.display = 'block';
    } else if (state === 'ready') {
        status.style.background = '#162a1e';
        status.style.color = '#7da882';
        icon.className = 'fas fa-check-circle';
        icon.style.marginRight = '6px';
        bar.style.display = 'none';
    } else if (state === 'error') {
        status.style.background = '#162a1e';
        status.style.color = '#d4183d';
        icon.className = 'fas fa-exclamation-circle';
        icon.style.marginRight = '6px';
        bar.style.display = 'none';
    } else if (state === 'searching') {
        status.style.background = '#162a1e';
        status.style.color = '#c97a3a';
        icon.className = 'fas fa-circle-notch fa-spin';
        icon.style.marginRight = '6px';
        bar.style.display = 'none';
    }
}

function setAIProgress(pct) {
    const fill = document.getElementById('aiProgressFill');
    if (fill) fill.style.width = pct + '%';
}

async function initSearch() {
    try {
        setAIStatus('Loading embeddings...', 'loading');
        setAIProgress(10);
        await loadEmbeddingIndex();
        setAIProgress(30);

        // Try WebLLM first (fast, needs WebGPU)
        let hasWebGPU = false;
        try {
            if (navigator.gpu) {
                setAIStatus('Loading WebGPU AI model...', 'loading');
                const engine = await initWebLLMEngine();
                window.setWebllmEngine(engine);
                hasWebGPU = !!engine;
            }
        } catch (mlErr) {
            console.error('WebLLM init failed:', mlErr);
        }

        if (!hasWebGPU) {
            // Load Transformers.js model (WASM, works without WebGPU)
            setAIStatus('Downloading AI model (~23MB, cached after first load)...', 'loading');
            window.setInitProgressCb((data) => {
                if (data.status === 'progress') {
                    const pct = Math.round((data.progress || 0));
                    setAIProgress(30 + Math.round(pct * 0.6));
                    setAIStatus(`Downloading AI model: ${pct}%`, 'loading');
                } else if (data.status === 'ready') {
                    setAIProgress(90);
                    setAIStatus('AI model loaded, preparing search...', 'loading');
                }
            });
            await initTransformers();
        }

        setAIProgress(100);
        setAIStatus(hasWebGPU ? 'AI search ready (WebGPU)!' : 'AI search ready!', 'ready');
        setTimeout(() => {
            const status = document.getElementById('aiStatus');
            if (status) status.style.display = 'none';
        }, 4000);
    } catch (err) {
        console.error('Search init failed:', err);
        setAIStatus('AI search unavailable — check console for details', 'error');
    }
}

function initMap() {
    map = L.map('map', {
        zoomControl: false,
        attributionControl: true,
        preferCanvas: true
    }).setView([20, 0], 2);

    L.control.zoom({ position: 'bottomright' }).addTo(map);

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '&copy; OpenStreetMap contributors'
    }).addTo(map);

    L.control.scale().addTo(map);

    map.on('click', function() {
        map.closePopup();
        // On mobile, collapse the drawer when tapping the map
        if (window.innerWidth <= 768 && mapControls.classList.contains('expanded')) {
            mapControls.classList.remove('expanded');
            toggleBtn.classList.remove('rotated');
        }
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
            updateResetButton();
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

    // Filter toggle — desktop: show/hide panel, mobile: expand/collapse drawer
    toggleBtn = document.getElementById('filterToggle');
    filterPanel = document.getElementById('filterPanel');
    mapControls = document.querySelector('.map-controls');
    
    // Check if we're on mobile
    const isMobile = window.innerWidth <= 768;
    
    // On mobile, use a chevron icon instead of filter icon
    if (isMobile) {
        toggleBtn.innerHTML = '<i class="fas fa-chevron-up"></i>';
    }
    
    toggleBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        if (isMobile) {
            // Mobile: toggle the drawer expand/collapse
            mapControls.classList.toggle('expanded');
            toggleBtn.classList.toggle('rotated');
        } else {
            // Desktop: just toggle the filter panel visibility
            filterPanel.classList.toggle('active');
        }
    });

    // On mobile, tapping the panel header also expands the drawer
    if (isMobile) {
        document.querySelector('.panel-header').addEventListener('click', function(e) {
            // Don't toggle if they clicked the toggle button itself (already handled)
            if (e.target.closest('.toggle-btn')) return;
            mapControls.classList.toggle('expanded');
            toggleBtn.classList.toggle('rotated');
        });
    }

    // On desktop, the panel content starts visible
    if (!isMobile) {
        filterPanel.classList.add('active');
    }

    // Reset button
    document.getElementById('resetBtn').addEventListener('click', resetAll);

    // Modal close
    document.querySelector('.close-modal').addEventListener('click', closeModal);
    document.getElementById('orgDetailsModal').addEventListener('click', function(e) {
        if (e.target === this) closeModal();
    });

    // Submit ecovillage
    document.getElementById('submitLink').addEventListener('click', function(e) {
        e.preventDefault();
        document.getElementById('submitError').style.display = 'none';
        document.getElementById('submitModal').classList.add('active');
    });
    document.querySelector('.close-submit').addEventListener('click', closeSubmitModal);
    document.getElementById('submitModal').addEventListener('click', function(e) {
        if (e.target === this) closeSubmitModal();
    });
    document.getElementById('submitForm').addEventListener('submit', handleSubmit);

    // Keyboard shortcut: Escape clears active search
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            clearSemanticSearch();
        }
    });

    // Handle window resize for responsive behavior
    let lastWidth = window.innerWidth;
    window.addEventListener('resize', function() {
        const width = window.innerWidth;
        // Only act on meaningful width changes (not scrollbar toggles)
        if (Math.abs(width - lastWidth) > 50) {
            if (width > 768) {
                // Switching to desktop: ensure panel is in desktop mode
                document.querySelector('.map-controls').classList.remove('expanded');
                document.getElementById('filterPanel').classList.add('active');
                toggleBtn.innerHTML = '<i class="fas fa-filter"></i>';
                toggleBtn.classList.remove('rotated');
            } else {
                // Switching to mobile: collapse drawer, swap icon
                document.querySelector('.map-controls').classList.remove('expanded');
                document.getElementById('filterPanel').classList.remove('active');
                toggleBtn.innerHTML = '<i class="fas fa-chevron-up"></i>';
                toggleBtn.classList.remove('rotated');
            }
            lastWidth = width;
        }
    });

    // On mobile, swipe down on the drawer to collapse it
    let touchStartY = 0;
    const controlsEl = document.querySelector('.map-controls');
    controlsEl.addEventListener('touchstart', function(e) {
        touchStartY = e.touches[0].clientY;
    }, { passive: true });
    controlsEl.addEventListener('touchmove', function(e) {
        if (!controlsEl.classList.contains('expanded')) return;
        const deltaY = e.touches[0].clientY - touchStartY;
        if (deltaY > 80) {
            // Swiped down far enough — collapse
            controlsEl.classList.remove('expanded');
            toggleBtn.classList.remove('rotated');
            touchStartY = 0;
        }
    }, { passive: true });
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
        let response;
        try {
            response = await fetch('/api/organizations/geojson/');
        } catch (e) {
            console.warn('[load] API fetch failed, falling back to static file:', e);
            response = await fetch('data/organizations.geojson');
        }
        if (!response.ok) {
            console.warn('[load] API returned ' + response.status + ', falling back to static file');
            response = await fetch('data/organizations.geojson');
            if (!response.ok) {
                throw new Error('HTTP error! status: ' + response.status);
            }
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
                email: props.email || '',
                phone: props.phone || '',
                address: props.address || '',
                city: props.city || '',
                region: props.region || '',
                postalCode: props.postalCode || '',
                country: props.country || '',
                organizationType: props.organizationType || '',
                source: props.source,
                latitude: feature.geometry.coordinates[1],
                longitude: feature.geometry.coordinates[0],
                accepts_volunteers: props.acceptsVolunteers,
                accepts_visitors: props.acceptsVisitors,
                accepts_shortterm: props.acceptsShortterm,
                accepts_longterm: props.acceptsLongterm,
                has_jobs: props.hasJobs,
                has_stays: props.hasStays,
                has_events: props.hasEvents,
                schemaOrg: props.schemaOrg || null
            };
        });
        window.allOrganizations = allOrganizations;

        visibleOrganizations = allOrganizations.slice();
        createMarkers(allOrganizations);
        updateStatistics();
    } catch (error) {
        console.error('Error loading organizations:', error);
    } finally {
        showLoading(false);
        updateResetButton();
    }
}

function buildPopupHtml(org) {
    // Title (italic serif)
    const title = `<h3 class="popup-title">${escapeHtml(org.name)}</h3>`;

    // Short description (clamped)
    let descHtml = '';
    const desc = org.description || '';
    if (desc && desc.length > 10) {
        descHtml = `<div class="popup-desc">${escapeHtml(desc)}</div>`;
    }

    // Badges
    let badgesHtml = '<div class="popup-badges">';
    if (org.accepts_volunteers) {
        badgesHtml += '<span class="popup-badge popup-badge-volunteer"><i class="fas fa-hands-helping"></i> Volunteer</span>';
    }
    if (org.has_jobs) {
        badgesHtml += '<span class="popup-badge popup-badge-jobs"><i class="fas fa-briefcase"></i> Jobs</span>';
    }
    if (org.has_stays) {
        badgesHtml += '<span class="popup-badge popup-badge-stays"><i class="fas fa-bed"></i> Stays</span>';
    }
    if (org.has_events) {
        badgesHtml += '<span class="popup-badge popup-badge-events"><i class="fas fa-calendar-alt"></i> Events</span>';
    }
    badgesHtml += '</div>';
    if (badgesHtml === '<div class="popup-badges"></div>') badgesHtml = '';

    // Match score badge when search is active
    let scoreBadge = '';
    const scoreInfo = searchScores && searchScores[org.id];
    if (scoreInfo) {
        scoreBadge = `<div class="popup-score">
            <span style="background:${scoreToColor(scoreInfo.score, 1, scoreInfo.rank, scoreInfo.total)};">#${scoreInfo.rank} · ${scoreInfo.pct}% match</span>
        </div>`;
    }

    // Location + website link
    const locationHtml = '<div class="popup-location"><i class="fas fa-map-marker-alt"></i> ' +
        (org.latitude && org.longitude ? `${org.latitude.toFixed(4)}, ${org.longitude.toFixed(4)}` : 'Global map') + '</div>';

    let websiteLink = '';
    if (org.website) {
        websiteLink = `<a href="${escapeHtml(org.website)}" target="_blank" style="color:#7da882;text-decoration:none;"><i class="fas fa-globe"></i> Website</a>`;
    }

    // Data source label
    const sourceLabel = getSourceLabel(org.source);
    const sourceHtml = sourceLabel
        ? `<div class="popup-meta">${sourceLabel}</div>`
        : '';

    return '<div class="org-popup">' +
        scoreBadge +
        title +
        descHtml +
        badgesHtml +
        locationHtml +
        (websiteLink ? `<div class="popup-meta">${websiteLink}</div>` : '') +
        sourceHtml +
        '<div class="popup-actions"><button class="btn view-details-btn" data-org-id="' + org.id + '">View Details <i class="fas fa-arrow-right"></i></button></div>' +
        '</div>';
}

function getSourceLabel(source) {
    if (!source) return '';
    const s = source.toLowerCase();
    const linkStyle = 'style="color:#7da882;text-decoration:none;"';
    if (s === 'ecovillage') return 'Listed on <a href="https://ecovillage.org" target="_blank" ' + linkStyle + '>ecovillage.org</a> (GEN)';
    if (s === 'ic-directory') return 'Listed on <a href="https://ic.org" target="_blank" ' + linkStyle + '>ic.org</a> (FIC)';
    if (s === 'ecobasa') return 'Listed on <a href="https://ecobasa.org" target="_blank" ' + linkStyle + '>ecobasa.org</a>';
    if (s === 'agartha') return 'Listed on <a href="https://agartha.one" target="_blank" ' + linkStyle + '>agartha.one</a>';
    if (s === 'tribes') return 'Listed on <a href="https://ic.org" target="_blank" ' + linkStyle + '>ic.org</a>';
    if (s === 'facebook') return 'Found on <a href="https://facebook.com" target="_blank" ' + linkStyle + '>Facebook</a>';
    return 'Source: ' + escapeHtml(source);
}

function createMarkers(orgs) {
    markers.forEach(marker => map.removeLayer(marker));
    markers = [];

    orgs.forEach(org => {
        const color = searchScores && searchScores[org.id]
            ? scoreToColor(searchScores[org.id].score, 1, searchScores[org.id].rank, searchScores[org.id].total)
            : MARKER_COLOR;

        const markerSvg =
            '<svg width="28" height="36" viewBox="0 0 28 36" class="marker-svg">' +
            '<path d="M14 0C6.3 0 0 6.3 0 14c0 10.5 14 22 14 22s14-11.5 14-22C28 6.3 21.7 0 14 0z" fill="' + color + '" stroke="rgba(255,255,255,0.9)" stroke-width="2"/>' +
            '<circle cx="14" cy="14" r="4.5" fill="rgba(255,255,255,0.9)"/>' +
            '</svg>';

        const icon = L.divIcon({
            className: 'custom-marker',
            html: markerSvg,
            iconSize: [28, 36],
            iconAnchor: [14, 36]
        });

        const marker = L.marker([org.latitude, org.longitude], { icon: icon }).addTo(map);

        const popupContent = buildPopupHtml(org);
        marker.bindPopup(popupContent, { autoPan: false, closeButton: true, className: 'te-popup' });
        marker.on('click', function() {
            setTimeout(() => {
                const popupEl = marker.getPopup().getElement();
                if (popupEl) {
                    const detailsBtn = popupEl.querySelector('.view-details-btn');
                    if (detailsBtn) {
                        detailsBtn.addEventListener('click', () => showOrganizationDetails(org.id));
                    }
                }
            }, 30);
        });
        markers.push(marker);
    });
}

function buildBadges(org) {
    let html = '';
    if (org.accepts_volunteers) html += '<span class="org-badge org-badge-volunteer"><i class="fas fa-hands-helping"></i> Volunteer</span> ';
    if (org.accepts_visitors) {
        if (org.accepts_shortterm) html += '<span class="org-badge org-badge-stays"><i class="fas fa-clock"></i> Short-term</span> ';
        if (org.accepts_longterm) html += '<span class="org-badge org-badge-stays"><i class="fas fa-calendar-check"></i> Long-term</span> ';
    }
    if (org.has_jobs) html += '<span class="org-badge org-badge-jobs"><i class="fas fa-briefcase"></i> Jobs</span> ';
    if (org.has_stays) html += '<span class="org-badge org-badge-stays"><i class="fas fa-bed"></i> Stays</span> ';
    if (org.has_events) html += '<span class="org-badge org-badge-events"><i class="fas fa-calendar-alt"></i> Events</span> ';
    return html;
}

function filterOrganizations() {
    // Start from either search results or all orgs
    const base = (isSearchActive && searchResultIds)
        ? allOrganizations.filter(org => searchResultIds.includes(org.id))
        : allOrganizations.slice();

    if (!filters.jobs && !filters.stays && !filters.events) {
        visibleOrganizations = base;
        return;
    }
    visibleOrganizations = base.filter(org => {
        if (filters.jobs && !org.has_jobs) return false;
        if (filters.stays && !org.has_stays) return false;
        if (filters.events && !org.has_events) return false;
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

        const markerSvg =
            '<svg width="28" height="36" viewBox="0 0 28 36" class="marker-svg">' +
            '<path d="M14 0C6.3 0 0 6.3 0 14c0 10.5 14 22 14 22s14-11.5 14-22C28 6.3 21.7 0 14 0z" fill="' + color + '" stroke="rgba(255,255,255,0.9)" stroke-width="2"/>' +
            '<circle cx="14" cy="14" r="4.5" fill="rgba(255,255,255,0.9)"/>' +
            '</svg>';

        const icon = L.divIcon({
            className: 'custom-marker',
            html: markerSvg,
            iconSize: [28, 36],
            iconAnchor: [14, 36]
        });

        const marker = L.marker([org.latitude, org.longitude], { icon: icon }).addTo(map);
        const popupContent = buildPopupHtml(org);
        marker.bindPopup(popupContent, { autoPan: false, closeButton: true, className: 'te-popup' });
        marker.on('click', function() {
            setTimeout(() => {
                const popupEl = marker.getPopup().getElement();
                if (popupEl) {
                    const detailsBtn = popupEl.querySelector('.view-details-btn');
                    if (detailsBtn) {
                        detailsBtn.addEventListener('click', () => showOrganizationDetails(org.id));
                    }
                }
            }, 30);
        });
        markers.push(marker);
    });
    updateStatistics();
}

async function showOrganizationDetails(orgId) {
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
        linksHtml = '<a href="' + escapeHtml(org.website) + '" target="_blank"><i class="fas fa-globe"></i> Website</a>';
    }
    if (org.email) {
        linksHtml += '<a href="mailto:' + escapeHtml(org.email) + '"><i class="fas fa-envelope"></i> Email</a>';
    }
    if (org.phone) {
        linksHtml += '<span style="color:#7da882;font-size:13px;"><i class="fas fa-phone"></i> ' + escapeHtml(org.phone) + '</span>';
    }

    const sourceLabel = getSourceLabel(org.source);
    const sourceSection = sourceLabel
        ? '<div class="org-section"><h4><i class="fas fa-database"></i> Data Source</h4><div style="font-size:13px;color:#7da882;">' + sourceLabel + '</div></div>'
        : '';

    modalBody.innerHTML =
        '<div class="org-details">' +
        '<h2>' + escapeHtml(org.name) + '</h2>' +
        '<div style="margin-bottom:14px;">' + badgeHtml + '</div>' +
        descHtml +
        '<div class="org-section"><h4><i class="fas fa-map-marked-alt"></i> Location</h4><p>Lat: ' + org.latitude.toFixed(4) + ', Lon: ' + org.longitude.toFixed(4) + '</p></div>' +
        (linksHtml ? '<div class="org-section"><h4><i class="fas fa-link"></i> Links</h4><div>' + linksHtml + '</div></div>' : '') +
        '<div id="jobsSection"></div>' +
        '<div id="staysSection"></div>' +
        sourceSection +
        '</div>';

    document.getElementById('orgDetailsModal').classList.add('active');

    // Update browser title and inject JSON-LD for this community
    if (org.schemaOrg) {
        document.title = `${org.name} — ComeUnity`;
        injectOrgJsonLd(org.schemaOrg);
    }

    // Fetch jobs and stays in parallel
    var jobsPromise = fetch('/api/organizations/' + orgId + '/jobs').then(function(r) { return r.json(); }).catch(function() { return []; });
    var staysPromise = fetch('/api/organizations/' + orgId + '/stays').then(function(r) { return r.json(); }).catch(function() { return []; });

    var results = await Promise.all([jobsPromise, staysPromise]);
    var jobs = results[0];
    var stays = results[1];

    // Render jobs
    var jobsEl = document.getElementById('jobsSection');
    if (jobs && jobs.length > 0) {
        var roleLabels = { 'volunteer': 'Volunteer', 'paid_job': 'Paid Position', 'internship': 'Internship', 'apprenticeship': 'Apprenticeship', 'volunteer/work': 'Volunteer / Work' };
        var jh = '<div class="org-section"><h4><i class="fas fa-briefcase"></i> Job Opportunities (' + jobs.length + ')</h4>';
        jobs.forEach(function(job) {
            var roleLabel = roleLabels[job.role] || job.role || 'Position';
            var title = escapeHtml(job.title || 'Untitled');
            var jd = job.description ? '<div class="card-text">' + escapeHtml(job.description.substring(0, 200)) + (job.description.length > 200 ? '...' : '') + '</div>' : '';
            var cm = job.commitment ? '<span class="card-meta"><i class="fas fa-clock"></i> ' + escapeHtml(job.commitment) + '</span>' : '';
            var al = job.source_url ? '<a href="' + escapeHtml(job.source_url) + '" target="_blank" class="card-action">Apply <i class="fas fa-arrow-right"></i></a>' : '';
            jh += '<div class="detail-card">' +
                '<div class="detail-card-title">' + title + '</div>' +
                '<div class="detail-card-subtitle">' + escapeHtml(roleLabel) + '</div>' +
                jd + '<div style="margin-top:6px;">' + cm + al + '</div></div>';
        });
        jh += '</div>';
        jobsEl.innerHTML = jh;
    }

    // Render stays
    var staysEl = document.getElementById('staysSection');
    if (stays && stays.length > 0) {
        var bookingLabels = { 'external_widget': 'External Booking', 'calendar_tool': 'Calendar Tool', 'email_phone': 'Email / Phone', 'direct_form': 'Direct Form', 'unknown': 'Contact Directly' };
        var sh = '<div class="org-section"><h4><i class="fas fa-home"></i> Stays Available (' + stays.length + ')</h4>';
        stays.forEach(function(stay) {
            var title = escapeHtml(stay.title || 'Stay');
            var sd = stay.description ? '<div class="card-text">' + escapeHtml(stay.description.substring(0, 200)) + (stay.description.length > 200 ? '...' : '') + '</div>' : '';
            var pr = stay.price_info ? '<span class="card-meta"><i class="fas fa-tag"></i> ' + escapeHtml(stay.price_info) + '</span>' : '';
            var bl = bookingLabels[stay.booking_type] || 'Contact Directly';
            var bk = stay.booking_url ? '<a href="' + escapeHtml(stay.booking_url) + '" target="_blank" class="card-action">Book <i class="fas fa-arrow-right"></i></a>' : '';
            sh += '<div class="detail-card">' +
                '<div class="detail-card-title">' + title + '</div>' +
                '<div class="detail-card-subtitle">' + escapeHtml(bl) + '</div>' +
                sd + '<div style="margin-top:6px;">' + pr + bk + '</div></div>';
        });
        sh += '</div>';
        staysEl.innerHTML = sh;
    }
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
    document.title = 'ComeUnity';
    const ld = document.getElementById('org-jsonld');
    if (ld) ld.remove();
}

function injectOrgJsonLd(schema) {
    let ld = document.getElementById('org-jsonld');
    if (!ld) {
        ld = document.createElement('script');
        ld.id = 'org-jsonld';
        ld.type = 'application/ld+json';
        document.head.appendChild(ld);
    }
    ld.textContent = JSON.stringify(schema, null, 2);
}

function closeSubmitModal() {
    document.getElementById('submitModal').classList.remove('active');
    document.getElementById('submitError').style.display = 'none';
}

async function handleSubmit(e) {
    e.preventDefault();
    const errDiv = document.getElementById('submitError');
    const successDiv = document.getElementById('submitSuccess');
    const btn = document.getElementById('submitBtn');
    errDiv.style.display = 'none';
    successDiv.style.display = 'none';

    const data = {
        name: document.getElementById('subName').value.trim(),
        description: document.getElementById('subDesc').value.trim(),
        organization_type: document.getElementById('subType').value.trim() || null,
        website: document.getElementById('subWebsite').value.trim() || null,
        email: document.getElementById('subEmail').value.trim() || null,
        phone: document.getElementById('subPhone').value.trim() || null,
        address: document.getElementById('subAddress').value.trim() || null,
        city: document.getElementById('subCity').value.trim() || null,
        region: document.getElementById('subRegion').value.trim() || null,
        country: document.getElementById('subCountry').value.trim(),
        postal_code: document.getElementById('subPostal').value.trim() || null,
        latitude: parseFloat(document.getElementById('subLat').value),
        longitude: parseFloat(document.getElementById('subLng').value),
        accepts_volunteers: document.getElementById('subVolunteers').checked,
        accepts_visitors: document.getElementById('subVisitors').checked,
        accepts_shortterm: document.getElementById('subShortterm').checked,
        accepts_longterm: document.getElementById('subLongterm').checked,
        has_stays: document.getElementById('subShortterm').checked || document.getElementById('subLongterm').checked,
        has_jobs: document.getElementById('subJobs').checked,
        has_events: document.getElementById('subEvents').checked,
    };

    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Submitting...';

    try {
        const resp = await fetch('/api/submit-ecovillage/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        const result = await resp.json();

        if (resp.ok && result.success) {
            successDiv.textContent = result.message;
            successDiv.style.display = 'block';
            document.getElementById('submitForm').reset();
            // Reload the map data after a short delay so the new org appears
            setTimeout(() => {
                loadOrganizations();
            }, 1500);
        } else {
            const detail = result.detail || result.message || 'Submission failed';
            errDiv.textContent = detail;
            errDiv.style.display = 'block';
        }
    } catch (err) {
        errDiv.textContent = 'Network error: ' + err.message;
        errDiv.style.display = 'block';
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-paper-plane"></i> Submit for Review';
    }
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

    if (!window.getEmbeddingIndex()) {
        setAIStatus('Still loading AI model, please wait...', 'loading');
        return;
    }

    const country = extractLocationFromQuery(query);
    const btn = document.getElementById('semanticSearchBtn');
    const toast = document.getElementById('semanticToast');

    // Clear previous search
    searchScores = null;
    searchResultIds = null;
    isSearchActive = false;

    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Searching...';
    btn.disabled = true;
    toast.style.display = 'none';
    setAIStatus('Embedding your query with AI model...', 'searching');

    try {
        const results = await searchEmbeddings(query, 200);

        if (results.length > 0) {
            isSearchActive = true;

            searchScores = {};
            searchResultIds = results.map(r => r.id);
            const total = results.length;
            results.forEach((r, idx) => {
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

            visibleOrganizations = allOrganizations.filter(org => searchResultIds.includes(org.id));
            filterOrganizations();
            updateMarkers();

            if (results.length === 1) {
                map.setView([results[0].lat, results[0].lon], 10);
            } else {
                const bounds = L.latLngBounds(results.map(r => [r.lat, r.lon]));
                map.fitBounds(bounds, { padding: [50, 50] });
            }

            let msg = `Found ${results.length} matching location${results.length !== 1 ? 's' : ''}`;
            if (country) msg += ` in ${country}`;
            msg += ' · red=best match → blue';
            showToast(msg, false);
            setAIStatus(`Found ${results.length} matches — see map`, 'ready');
            setTimeout(() => {
                const s = document.getElementById('aiStatus');
                if (s) s.style.display = 'none';
            }, 5000);
        } else {
            isSearchActive = false;
            let msg = 'No matching locations found';
            if (country) msg += ` in ${country}`;
            msg += '. Try a different description.';
            showToast(msg, false);
            setAIStatus('No matches found — try different keywords', 'error');
        }

    } catch (error) {
        console.error('Semantic search error:', error);
        showToast('Search failed. Please try again.', true);
        setAIStatus('Search failed — ' + (error.message || 'unknown error'), 'error');
    } finally {
        btn.innerHTML = '<i class="fas fa-search"></i> Find Matching Locations';
        btn.disabled = false;
        updateResetButton();
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
    searchResultIds = null;
    
    // Reset markers to show all (respecting feature filters only)
    filterOrganizations();
    updateMarkers();
    updateResetButton();
}

function resetAll() {
    // Clear search
    const queryInput = document.getElementById('semanticQuery');
    queryInput.value = '';
    const toast = document.getElementById('semanticToast');
    toast.style.display = 'none';
    clearTimeout(toast._hideTimer);
    isSearchActive = false;
    searchScores = null;
    searchResultIds = null;
    
    // Uncheck all filters
    document.querySelectorAll('.feature-checkbox').forEach(cb => {
        cb.checked = false;
    });
    filters = { volunteer: false, shortterm: false, longterm: false, jobs: false };
    
    // Show all orgs
    visibleOrganizations = allOrganizations.slice();
    updateMarkers();
    updateResetButton();
}

function updateResetButton() {
    const btn = document.getElementById('resetBtn');
    const hasSearch = isSearchActive;
    const hasFilters = filters.volunteer || filters.shortterm || filters.longterm || filters.jobs;
    btn.style.display = (hasSearch || hasFilters) ? 'inline-block' : 'none';
}

function escapeHtml(text) {
    if (!text) return '';
    const esc = document.createElement('div');
    esc.textContent = text;
    return esc.innerHTML;
}
