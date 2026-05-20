const LOCATIONS = [
  { name: 'Auroville', country: 'India', focus: 'Sustainable living, education', lat: 12.0055, lon: 79.8103 },
  { name: 'Findhorn Ecovillage', country: 'Scotland', focus: 'Regenerative community, ecology', lat: 57.6545, lon: -3.6096 },
  { name: 'Dancing Rabbit Ecovillage', country: 'USA', focus: 'Low-impact living, natural building', lat: 40.0960, lon: -92.0015 },
  { name: 'Tamera', country: 'Portugal', focus: 'Water retention landscape, peace work', lat: 37.5270, lon: -8.3140 },
  { name: 'Sieben Linden', country: 'Germany', focus: 'Permaculture, straw-bale construction', lat: 52.7962, lon: 11.0304 },
  { name: 'Crystal Waters', country: 'Australia', focus: 'Permaculture settlement', lat: -26.6537, lon: 152.7390 },
  { name: 'Huehuecoyotl', country: 'Mexico', focus: 'Arts, ecological restoration', lat: 18.8924, lon: -99.1399 }
];

const map = L.map('map').setView([25, 5], 2);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19,
  attribution: '&copy; OpenStreetMap contributors'
}).addTo(map);

const markers = [];
const list = document.getElementById('locationList');
const search = document.getElementById('search');

function render(items) {
  list.innerHTML = '';
  markers.forEach(m => map.removeLayer(m));
  markers.length = 0;

  items.forEach((loc) => {
    const marker = L.marker([loc.lat, loc.lon]).addTo(map)
      .bindPopup(`<strong>${loc.name}</strong><br>${loc.country}<br>${loc.focus}`);
    markers.push(marker);

    const li = document.createElement('li');
    li.innerHTML = `<strong>${loc.name}</strong><br>${loc.country}<br><small>${loc.focus}</small>`;
    li.addEventListener('click', () => {
      map.setView([loc.lat, loc.lon], 8);
      marker.openPopup();
    });
    list.appendChild(li);
  });
}

search.addEventListener('input', (e) => {
  const q = e.target.value.trim().toLowerCase();
  const filtered = LOCATIONS.filter(l =>
    l.name.toLowerCase().includes(q) ||
    l.country.toLowerCase().includes(q) ||
    l.focus.toLowerCase().includes(q)
  );
  render(filtered);
});

render(LOCATIONS);
