const COLORS = { Lightning: '#f59f00', Human: '#d9480f', Unknown: '#868e96' };
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const fmt = new Intl.NumberFormat('en-CA');

const state = { year: 'all', cause: 'all' };
let fires = [];
let causeNames = [];
let map, layer, charts = {};

const causeGroup = (cause) =>
  cause === 'Lightning' ? 'Lightning' : cause === 'Undetermined' || cause === 'Under Investigation' ? 'Unknown' : 'Human';

async function init() {
  const data = await fetch('data/fires.json').then((r) => r.json());
  causeNames = data.causes;
  fires = data.rows.map(([year, month, lat, lon, ha, cause, area, response, name, id]) => ({
    year, month, lat, lon, ha, response, name, id,
    cause: data.causes[cause],
    group: causeGroup(data.causes[cause]),
    area: data.areas[area],
  }));

  const years = [...new Set(fires.map((f) => f.year))].sort((a, b) => b - a);
  const yearSelect = document.getElementById('year');
  yearSelect.innerHTML = `<option value="all">All years</option>` + years.map((y) => `<option>${y}</option>`).join('');
  document.getElementById('subtitle').textContent =
    `${fmt.format(fires.length)} recorded wildfires in Alberta's forest protection area, ${years.at(-1)}–${years[0]}`;

  yearSelect.addEventListener('change', (e) => setState({ year: e.target.value }));
  document.getElementById('cause').addEventListener('change', (e) => setState({ cause: e.target.value }));

  map = L.map('map', { preferCanvas: true, zoomSnap: 0.25 }).fitBounds([[49, -120], [60, -110]]);
  L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}', {
    attribution: 'Tiles &copy; Esri',
    maxZoom: 13,
  }).addTo(map);
  L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}', {
    maxZoom: 13,
    pane: 'shadowPane',
  }).addTo(map);

  buildCharts();
  // Open on the most recent season; "All years" is one click away
  setState({ year: String(years[0]) });
}

function setState(patch) {
  Object.assign(state, patch);
  document.getElementById('year').value = state.year;
  render();
}

function filtered({ ignoreYear = false } = {}) {
  return fires.filter(
    (f) =>
      (ignoreYear || state.year === 'all' || f.year === Number(state.year)) &&
      (state.cause === 'all' || f.group === state.cause),
  );
}

function median(values) {
  if (!values.length) return null;
  const s = [...values].sort((a, b) => a - b);
  const mid = s.length >> 1;
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

function formatMinutes(m) {
  if (m == null) return '–';
  return m < 90 ? `${Math.round(m)} min` : `${(m / 60).toFixed(1)} hrs`;
}

function render() {
  const rows = filtered();

  // KPIs
  const ha = rows.reduce((s, f) => s + f.ha, 0);
  const human = rows.filter((f) => f.group === 'Human').length;
  document.getElementById('k-fires').textContent = fmt.format(rows.length);
  document.getElementById('k-ha').textContent = fmt.format(Math.round(ha));
  document.getElementById('k-human').textContent = rows.length ? `${Math.round((human / rows.length) * 100)}%` : '–';
  document.getElementById('k-response').textContent = formatMinutes(
    median(rows.map((f) => f.response).filter((r) => r != null)),
  );

  // Map: draw small fires first so the big ones sit on top
  if (layer) layer.remove();
  layer = L.layerGroup();
  [...rows].sort((a, b) => a.ha - b.ha).forEach((f) => {
    L.circleMarker([f.lat, f.lon], {
      radius: Math.max(2.5, Math.min(26, Math.sqrt(f.ha) / 14)),
      color: COLORS[f.group],
      weight: f.ha > 10000 ? 1.5 : 0.5,
      fillColor: COLORS[f.group],
      fillOpacity: f.ha > 1000 ? 0.45 : 0.6,
    })
      .bindPopup(
        `<b>${f.name || f.id}</b><br>${fmt.format(Math.round(f.ha))} ha · ${f.year}<br>${f.cause} · ${f.area}`,
      )
      .addTo(layer);
  });
  layer.addTo(map);

  // Largest fires list
  const largest = [...rows].sort((a, b) => b.ha - a.ha).slice(0, 12);
  const list = document.getElementById('largest');
  list.innerHTML = largest
    .map(
      (f, i) =>
        `<li data-i="${i}"><div>${f.name || f.id}<small>${f.year} · ${f.cause}</small></div><b>${fmt.format(
          Math.round(f.ha),
        )} ha</b></li>`,
    )
    .join('');
  list.querySelectorAll('li').forEach((li) =>
    li.addEventListener('click', () => {
      const f = largest[li.dataset.i];
      map.flyTo([f.lat, f.lon], 8, { duration: 0.8 });
    }),
  );

  updateCharts(rows);
}

function buildCharts() {
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  Chart.defaults.color = '#7a7068';
  const grid = { color: '#efe9e2' };

  charts.years = new Chart(document.getElementById('c-years'), {
    type: 'bar',
    data: { labels: [], datasets: [{ data: [], borderRadius: 4 }] },
    options: {
      maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => `${fmt.format(c.raw)} ha` } } },
      scales: { y: { grid, ticks: { callback: (v) => (v >= 1e6 ? `${v / 1e6}M` : v >= 1e3 ? `${v / 1e3}k` : v) } }, x: { grid: { display: false } } },
      onClick: (_, elements) => {
        if (!elements.length) return;
        const year = String(charts.years.data.labels[elements[0].index]);
        setState({ year: state.year === year ? 'all' : year });
      },
    },
  });

  charts.months = new Chart(document.getElementById('c-months'), {
    type: 'bar',
    data: { labels: MONTHS, datasets: [{ data: [], backgroundColor: '#e8590c', borderRadius: 4 }] },
    options: {
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: { y: { grid }, x: { grid: { display: false } } },
    },
  });

  charts.causes = new Chart(document.getElementById('c-causes'), {
    type: 'bar',
    data: { labels: [], datasets: [{ data: [], borderRadius: 4 }] },
    options: {
      indexAxis: 'y',
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: { x: { grid }, y: { grid: { display: false } } },
    },
  });
}

function updateCharts(rows) {
  // Year chart always shows every year (filtered by cause) and highlights the selected one
  const byYear = new Map();
  filtered({ ignoreYear: true }).forEach((f) => byYear.set(f.year, (byYear.get(f.year) || 0) + f.ha));
  const years = [...byYear.keys()].sort();
  charts.years.data.labels = years;
  charts.years.data.datasets[0].data = years.map((y) => Math.round(byYear.get(y)));
  charts.years.data.datasets[0].backgroundColor = years.map((y) =>
    state.year === 'all' || String(y) === state.year ? '#d9480f' : '#f3c4a8',
  );
  charts.years.update();

  const months = new Array(12).fill(0);
  rows.forEach((f) => f.month && months[f.month - 1]++);
  charts.months.data.datasets[0].data = months;
  charts.months.update();

  const counts = new Map();
  rows.forEach((f) => counts.set(f.cause, (counts.get(f.cause) || 0) + 1));
  const top = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 7);
  charts.causes.data.labels = top.map(([c]) => c);
  charts.causes.data.datasets[0].data = top.map(([, n]) => n);
  charts.causes.data.datasets[0].backgroundColor = top.map(([c]) => COLORS[causeGroup(c)]);
  charts.causes.update();
}

init();
