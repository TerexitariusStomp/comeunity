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

    // Search
    document.getElementById('searchBtn').addEventListener('click', searchLocation);
    document.getElementById('locationSearch').addEventListener('keypress', function(e) {
        if (e.key === 'Enter') searchLocation();
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
}

function searchLocation() {
    const locationInput = document.getElementById('locationSearch');
    const location = locationInput.value.trim();
    if (!location) {
        alert('Please enter a location');
        return;
    }
    fetch('https://nominatim.openstreetmap.org/search?format=json&q=' + encodeURIComponent(location))
        .then(function(r) { return r.json(); })
        .then(function(results) {
            if (results && results.length > 0) {
                const r = results[0];
                map.setView([parseFloat(r.lat), parseFloat(r.lon)], 10);
                currentLocation = [parseFloat(r.lat), parseFloat(r.lon)];
            } else {
                alert('Location not found');
            }
        })
        .catch(function() {
            alert('Search failed. Try a different location.');
        });
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
    // org.popup is already safe HTML from the backend (name, badges, website, email, phone)
    // Just wrap it and add the View Details button
    const body = org.popup || '<p>' + escapeHtml(org.name) + '</p>';
    return '<div class="org-popup">' +
        body +
        '<br><div class="org-actions"><button class="btn view-details-btn" data-org-id="' + org.id + '">View Details</button></div>' +
        '</div>';
}

function createMarkers(orgs) {
    markers.forEach(marker => map.removeLayer(marker));
    markers = [];

    const icon = L.divIcon({
        className: 'custom-marker',
        html: '<i class="fas fa-map-marker-alt" style="color:' + MARKER_COLOR + '; font-size: 18px;"></i>',
        iconSize: [18, 18],
        iconAnchor: [9, 18]
    });

    orgs.forEach(org => {
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

    const icon = L.divIcon({
        className: 'custom-marker',
        html: '<i class="fas fa-map-marker-alt" style="color:' + MARKER_COLOR + '; font-size: 18px;"></i>',
        iconSize: [18, 18],
        iconAnchor: [9, 18]
    });

    visibleOrganizations.forEach(org => {
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
    
    // Full description from org.description (plain text, not the HTML popup)
    let descHtml = '';
    const desc = org.description || '';
    if (desc && desc.length > 10) {
        descHtml = '<div class="org-section"><h4><i class="fas fa-info-circle"></i> About</h4>' +
            '<div style="max-height:250px;overflow-y:auto;padding-right:8px;line-height:1.5;font-size:14px;">' +
            escapeHtml(desc) +
            '</div></div>';
    }
    
    // Links row - show website link at minimum
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
    
    modalBody.innerHTML = 
        '<div class="org-details">' +
        '<h2 style="margin:0 0 4px;font-size:20px;">' + escapeHtml(org.name) + '</h2>' +
        '<div style="margin-bottom:12px;">' + badgeHtml + '</div>' +
        descHtml +
        '<div class="org-section"><h4><i class="fas fa-map-marked-alt"></i> Location</h4><p>Lat: ' + org.latitude.toFixed(4) + ', Lon: ' + org.longitude.toFixed(4) + '</p></div>' +
        (linksHtml ? '<div class="org-section"><h4><i class="fas fa-link"></i> Links</h4><div>' + linksHtml + '</div></div>' : '') +
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

function escapeHtml(text) {
    if (!text) return '';
    const esc = document.createElement('div');
    esc.textContent = text;
    return esc.innerHTML;
}
