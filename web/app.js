const MQTT_BASE    = 'drums';
const MQTT_WS_PORT = 9001;
const NOTES        = [38, 45, 46, 48, 49, 51];

// Default map matches gpio_controller.py defaults
const DEFAULT_GPIO_MAP = { 38: 5, 45: 19, 46: 16, 48: 6, 49: 20, 51: 13 };
let padGpioMap = { ...DEFAULT_GPIO_MAP };  // note(int) → pin(int)
let pinToNote  = buildReverseMap(DEFAULT_GPIO_MAP);  // pin(int) → note(int)

function buildReverseMap(map) {
  const rev = {};
  Object.entries(map).forEach(([note, pin]) => { rev[pin] = parseInt(note); });
  return rev;
}

// ── Pad grid ───────────────────────────────────────────────

function buildPadGrid() {
  const grid = document.getElementById('padGrid');
  grid.innerHTML = '';
  NOTES.forEach(note => {
    const pin = padGpioMap[note] ?? '?';
    const col = document.createElement('div');
    col.className = 'col';
    col.innerHTML = `
      <div class="pad-card" id="pad-${note}" data-note="${note}">
        <div class="pad-note">${note}</div>
        <div class="pad-pin" id="pad-pin-${note}">pin ${pin}</div>
      </div>`;
    col.querySelector('.pad-card').addEventListener('click', () => triggerPad(note));
    grid.appendChild(col);
  });
}

function updatePadPins() {
  NOTES.forEach(note => {
    const el = document.getElementById(`pad-pin-${note}`);
    if (el) el.textContent = `pin ${padGpioMap[note] ?? '?'}`;
  });
}

function triggerPad(note) {
  const ms = parseInt(document.getElementById('triggerMs').value) || 200;
  client.publish(`${MQTT_BASE}/pad/${note}`, String(ms));
}

function allOff() {
  NOTES.forEach(note => client.publish(`${MQTT_BASE}/pad/${note}`, '0'));
}

document.getElementById('allOffBtn').addEventListener('click', allOff);

function setPadActive(pin, active) {
  const note = pinToNote[pin];
  if (note === undefined) return;
  const el = document.getElementById(`pad-${note}`);
  if (!el) return;
  el.classList.toggle('active', active);
}

// ── PAD_GPIO_MAP table ─────────────────────────────────────

function buildMapTable(map) {
  const tbody = document.getElementById('padMapTable');
  tbody.innerHTML = '';
  Object.entries(map).forEach(([note, pin]) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><input type="number" class="form-control form-control-sm map-table"
                 data-role="note" value="${note}" style="width:80px"></td>
      <td><input type="number" class="form-control form-control-sm map-table"
                 data-role="pin"  value="${pin}"  style="width:80px"></td>`;
    tbody.appendChild(tr);
  });
}

function readMapTable() {
  const map = {};
  document.querySelectorAll('#padMapTable tr').forEach(row => {
    const n = parseInt(row.querySelector('[data-role="note"]')?.value);
    const p = parseInt(row.querySelector('[data-role="pin"]')?.value);
    if (!isNaN(n) && !isNaN(p)) map[n] = p;
  });
  return map;
}

// ── Form population ────────────────────────────────────────

function populateDrumkitForm(cfg) {
  const set = (id, val) => { if (val !== undefined) document.getElementById(id).value = val; };
  set('dk_MIDI_CHANNEL',     cfg.MIDI_CHANNEL);
  set('dk_MIN_ON_MS',        cfg.MIN_ON_MS);
  set('dk_MAX_ON_MS',        cfg.MAX_ON_MS);
  set('dk_MIN_RETRIGGER_MS', cfg.MIN_RETRIGGER_MS);
  if (Array.isArray(cfg.PAD_CONFIG))
    document.getElementById('dk_PAD_CONFIG').value = cfg.PAD_CONFIG.join(', ');
  // Pre-fill trigger ms from drumkit's MIN_ON_MS
  if (cfg.MIN_ON_MS !== undefined)
    document.getElementById('triggerMs').value = cfg.MIN_ON_MS;
}

function populateGpioForm(cfg) {
  if (cfg.MAX_ON_MS    !== undefined) document.getElementById('gp_MAX_ON_MS').value   = cfg.MAX_ON_MS;
  if (cfg.COOLDOWN_MS  !== undefined) document.getElementById('gp_COOLDOWN_MS').value = cfg.COOLDOWN_MS;
  if (cfg.OVERRIDE_MODE !== undefined) document.getElementById('gp_OVERRIDE_MODE').checked = cfg.OVERRIDE_MODE;
  if (cfg.PAD_GPIO_MAP !== undefined) {
    // Pydantic serialises dict keys as strings
    padGpioMap = {};
    Object.entries(cfg.PAD_GPIO_MAP).forEach(([n, p]) => { padGpioMap[parseInt(n)] = p; });
    pinToNote = buildReverseMap(padGpioMap);
    buildMapTable(padGpioMap);
    updatePadPins();
  }
}

// ── Flash save status briefly ──────────────────────────────

function flashSaved(spanId) {
  const el = document.getElementById(spanId);
  el.classList.remove('d-none');
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.add('d-none'), 2000);
}

// ── Form submission ────────────────────────────────────────

document.getElementById('drumkitForm').addEventListener('submit', e => {
  e.preventDefault();
  const padConfig = document.getElementById('dk_PAD_CONFIG').value
    .split(',').map(s => parseInt(s.trim())).filter(n => !isNaN(n));
  const payload = JSON.stringify({
    MIDI_CHANNEL:     parseInt(document.getElementById('dk_MIDI_CHANNEL').value),
    MIN_ON_MS:        parseFloat(document.getElementById('dk_MIN_ON_MS').value),
    MAX_ON_MS:        parseFloat(document.getElementById('dk_MAX_ON_MS').value),
    MIN_RETRIGGER_MS: parseFloat(document.getElementById('dk_MIN_RETRIGGER_MS').value),
    PAD_CONFIG:       padConfig,
  });
  // drumkit's message_callback_add is registered for the exact base topic
  client.publish(`${MQTT_BASE}`, payload, { qos: 0, retain: false });
  flashSaved('drumkitSaveStatus');
});

document.getElementById('gpioForm').addEventListener('submit', e => {
  e.preventDefault();
  const payload = JSON.stringify({
    MAX_ON_MS:    parseInt(document.getElementById('gp_MAX_ON_MS').value),
    COOLDOWN_MS:  parseInt(document.getElementById('gp_COOLDOWN_MS').value),
    OVERRIDE_MODE: document.getElementById('gp_OVERRIDE_MODE').checked,
    PAD_GPIO_MAP:  readMapTable(),
  });
  client.publish(`${MQTT_BASE}/poofer`, payload, { qos: 0, retain: true });
  flashSaved('gpioSaveStatus');
});

// ── MQTT ───────────────────────────────────────────────────

const statusEl = document.getElementById('mqttStatus');
const client   = mqtt.connect(`ws://${window.location.hostname}:${MQTT_WS_PORT}/mqtt`);

client.on('connect', () => {
  statusEl.textContent = 'Connected';
  statusEl.className   = 'badge bg-success';
  client.subscribe(`${MQTT_BASE}/#`);
});

client.on('reconnect', () => {
  statusEl.textContent = 'Reconnecting\u2026';
  statusEl.className   = 'badge bg-warning text-dark';
});

client.on('close', () => {
  statusEl.textContent = 'Disconnected';
  statusEl.className   = 'badge bg-danger';
});

client.on('error', err => {
  statusEl.textContent = 'Error';
  statusEl.className   = 'badge bg-danger';
  console.error('MQTT error:', err);
});

client.on('message', (topic, payload) => {
  const msg = payload.toString();

  if (topic === `${MQTT_BASE}/pad`) {
    try { populateDrumkitForm(JSON.parse(msg)); } catch (_) {}

  } else if (topic === `${MQTT_BASE}/poofer`) {
    try { populateGpioForm(JSON.parse(msg)); } catch (_) {}

  } else if (topic.startsWith(`${MQTT_BASE}/poofer/`)) {
    const pin = parseInt(topic.split('/').pop());
    if (!isNaN(pin)) setPadActive(pin, parseInt(msg) > 0);
  }
});

// ── Init ───────────────────────────────────────────────────
buildPadGrid();
buildMapTable(DEFAULT_GPIO_MAP);
