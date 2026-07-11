const Re = 6.371e6;
const Mu = 3.986004418e14;

let simData     = null;
let frameIdx    = 0;
let animTimer   = null;
let animSpeed   = 1;
let isPlaying   = false;
let selectedOrbit = { key: "iss", alt: 400 };

// ─────────────────────────────────────────────
// Propellant types — typical Isp values (s)
// ─────────────────────────────────────────────
const PROPELLANT_ISP = {
  rp1lox : { label: "RP-1 / LOX",  isp: 285 },
  lh2lox : { label: "LH2 / LOX",   isp: 420 },
  solid  : { label: "Solid",       isp: 250 },
  custom : { label: "Custom",      isp: null },
};

// ─────────────────────────────────────────────
// Rocket presets — approximate real vehicle data
// ─────────────────────────────────────────────
const ROCKET_PRESETS = {
  falcon9: {
    name: "Falcon 9", payload: 22800,
    stages: [
      { dry: 22200, prop: 395700, thrust: 7607000, isp: 282, cd: 0.3, area: 10.52, propellant: "rp1lox" },
      { dry: 4000,  prop: 92670,  thrust: 934000,  isp: 348, cd: 0.3, area: 10.52, propellant: "rp1lox" },
    ],
  },
  falconheavy: {
    name: "Falcon Heavy", payload: 63800,
    stages: [
      { dry: 96000, prop: 1187100, thrust: 22819000, isp: 282, cd: 0.4, area: 32.0, propellant: "rp1lox" },
      { dry: 4000,  prop: 92670,   thrust: 934000,   isp: 348, cd: 0.3, area: 10.52, propellant: "rp1lox" },
    ],
  },
  ariane5: {
    name: "Ariane 5 ECA", payload: 10000,
    stages: [
      { dry: 33000, prop: 408000, thrust: 13000000, isp: 275, cd: 0.4, area: 25.0, propellant: "solid" },
      { dry: 4540,  prop: 14900,  thrust: 67000,    isp: 446, cd: 0.3, area: 8.0,  propellant: "lh2lox" },
    ],
  },
  saturnv: {
    name: "Saturn V", payload: 118000,
    stages: [
      { dry: 130000, prop: 2160000, thrust: 34020000, isp: 263, cd: 0.4, area: 79.0, propellant: "rp1lox" },
      { dry: 40100,  prop: 443000,  thrust: 5141000,  isp: 421, cd: 0.35, area: 79.0, propellant: "lh2lox" },
      { dry: 13300,  prop: 106600,  thrust: 1001000,  isp: 421, cd: 0.3, area: 79.0, propellant: "lh2lox" },
    ],
  },
};

let stageCount = 0; // number of currently rendered stages, assigned by renderStages()

// ─────────────────────────────────────────────
// Dynamic stage cards
// ─────────────────────────────────────────────
function stageCardHTML(i, s) {
  s = s || { dry: 20000, prop: 100000, thrust: 1000000, isp: 300, cd: 0.3, area: 10.52, propellant: "rp1lox" };
  const propOptions = Object.keys(PROPELLANT_ISP).map(key =>
    `<option value="${key}" ${key === s.propellant ? "selected" : ""}>${PROPELLANT_ISP[key].label}</option>`
  ).join("");

  return `
    <div class="stage-card" data-stage="${i}">
      <div class="stage-card-header">
        <h3>Stage ${i + 1}</h3>
        <button type="button" class="remove-stage-btn" onclick="removeStage(${i})">✕ Remove</button>
      </div>
      <div class="field-grid">
        <div class="field">
          <label>Dry mass (kg)</label>
          <input type="number" id="s${i}-dry" value="${s.dry}" min="0">
        </div>
        <div class="field">
          <label>Propellant mass (kg)</label>
          <input type="number" id="s${i}-prop" value="${s.prop}" min="0">
        </div>
        <div class="field">
          <label>Thrust (N)</label>
          <input type="number" id="s${i}-thrust" value="${s.thrust}" min="0">
        </div>
        <div class="field">
          <label>Propellant type</label>
          <select id="s${i}-propellant" onchange="onPropellantChange(${i})">
            ${propOptions}
          </select>
        </div>
        <div class="field">
          <label>Isp (s)</label>
          <input type="number" id="s${i}-isp" value="${s.isp}" min="0">
        </div>
        <div class="field">
          <label>Drag coefficient</label>
          <input type="number" id="s${i}-cd" value="${s.cd}" step="0.01" min="0">
        </div>
        <div class="field">
          <label>Cross-section area (m²)</label>
          <input type="number" id="s${i}-area" value="${s.area}" step="0.01" min="0">
        </div>
      </div>
    </div>
  `;
}

function onPropellantChange(i) {
  const sel = document.getElementById(`s${i}-propellant`).value;
  const typical = PROPELLANT_ISP[sel] ? PROPELLANT_ISP[sel].isp : null;
  if (typical !== null) {
    document.getElementById(`s${i}-isp`).value = typical;
  }
}

function renderStages(stagesArr) {
  stageCount = stagesArr.length;
  const container = document.getElementById("stages-container");
  container.innerHTML = stagesArr.map((s, i) => stageCardHTML(i, s)).join("");
  updateRemoveButtons();
}

function updateRemoveButtons() {
  const cards = document.querySelectorAll(".stage-card");
  cards.forEach(card => {
    const btn = card.querySelector(".remove-stage-btn");
    btn.disabled = cards.length <= 1;
  });
}

function addStage() {
  const last = stageCount > 0
    ? readStageFromDOM(stageCount - 1)
    : { dry: 20000, prop: 100000, thrust: 1000000, isp: 300, cd: 0.3, area: 10.52, propellant: "rp1lox" };

  const container = document.getElementById("stages-container");
  container.insertAdjacentHTML("beforeend", stageCardHTML(stageCount, last));
  stageCount++;
  updateRemoveButtons();
}

function removeStage(i) {
  if (stageCount <= 1) return;
  // Read remaining stages (skipping i), then re-render with fresh sequential indices
  const remaining = [];
  for (let k = 0; k < stageCount; k++) {
    if (k === i) continue;
    remaining.push(readStageFromDOM(k));
  }
  renderStages(remaining);
}

function readStageFromDOM(i) {
  return {
    dry       : parseFloat(document.getElementById(`s${i}-dry`).value),
    prop      : parseFloat(document.getElementById(`s${i}-prop`).value),
    thrust    : parseFloat(document.getElementById(`s${i}-thrust`).value),
    isp       : parseFloat(document.getElementById(`s${i}-isp`).value),
    cd        : parseFloat(document.getElementById(`s${i}-cd`).value),
    area      : parseFloat(document.getElementById(`s${i}-area`).value),
    propellant: document.getElementById(`s${i}-propellant`).value,
  };
}

// ─────────────────────────────────────────────
// Rocket presets selection
// ─────────────────────────────────────────────
function selectRocketPreset(btn, key) {
  document.querySelectorAll(".rocket-preset-btn").forEach(b => b.classList.remove("active"));
  btn.classList.add("active");

  if (key === "custom") return; // keep current configuration as-is

  const preset = ROCKET_PRESETS[key];
  document.getElementById("vehicle-name").value = preset.name;
  document.getElementById("payload-mass").value = preset.payload;
  renderStages(preset.stages);
}

// Initial render — Falcon 9 default stages
renderStages(ROCKET_PRESETS.falcon9.stages);

// ─────────────────────────────────────────────
// Panel navigation
// ─────────────────────────────────────────────
function showPanel(name) {
  document.querySelectorAll(".panel").forEach(p => p.classList.remove("active"));
  document.querySelectorAll(".nav-btn").forEach(b => b.classList.remove("active"));
  document.getElementById("panel-" + name).classList.add("active");
  document.querySelector(`.nav-btn[onclick*="${name}"]`).classList.add("active");

  // Force Plotly to resize when switching to viewer
  if (name === "viewer") {
    setTimeout(() => {
      const el = document.getElementById("plot3d");
      if (el && el.data) Plotly.Plots.resize(el);
    }, 50);
  }
}

// ─────────────────────────────────────────────
// Orbit presets
// ─────────────────────────────────────────────
const V_CIRC = alt => Math.sqrt(Mu / (Re + alt * 1000)).toFixed(2);

const ORBIT_LABELS = {
  iss:    "ISS — 400 km LEO",
  sso:    "SSO — 600 km polar",
  meo:    "MEO — 20 000 km",
  geo:    "GEO — 35 786 km",
  custom: "Custom altitude",
};

function selectOrbit(btn, key, altKm) {
  document.querySelectorAll(".preset-btn").forEach(b => b.classList.remove("active"));
  btn.classList.add("active");
  selectedOrbit = { key, alt: altKm };

  document.getElementById("custom-alt-field").style.display =
    key === "custom" ? "block" : "none";

  const alt = key === "custom"
    ? parseFloat(document.getElementById("custom-alt").value)
    : altKm;

  document.getElementById("orbit-label").textContent = ORBIT_LABELS[key];
  document.getElementById("orbit-v").innerHTML =
    alt ? `v<sub>circ</sub> ≈ ${V_CIRC(alt)} km/s` : "—";
}

document.getElementById("custom-alt").addEventListener("input", function () {
  const alt = parseFloat(this.value);
  if (alt) document.getElementById("orbit-v").innerHTML =
    `v<sub>circ</sub> ≈ ${V_CIRC(alt)} km/s`;
});

// ─────────────────────────────────────────────
// Run simulation
// ─────────────────────────────────────────────
async function runSimulation() {
  const btn    = document.getElementById("launch-btn");
  const status = document.getElementById("status-bar");
  const msg    = document.getElementById("status-msg");

  let altKm = selectedOrbit.key === "custom"
    ? parseFloat(document.getElementById("custom-alt").value)
    : selectedOrbit.alt;

  console.log("Target orbit:", selectedOrbit.key, "| Alt:", altKm, "km |", altKm * 1000, "m");

  const stages = [];
  for (let i = 0; i < stageCount; i++) {
    const s = readStageFromDOM(i);
    stages.push({
      dry_mass : s.dry,
      prop_mass: s.prop,
      thrust   : s.thrust,
      isp      : s.isp,
      cd       : s.cd,
      area     : s.area,
    });
  }

  const payload = {
    stages,
    payload_mass: document.getElementById("payload-mass").value,
    target_alt  : altKm * 1000,   // metres
    t_vertical  : document.getElementById("t-vertical").value,
    n_orbits    : document.getElementById("n-orbits").value,
    n_frames    : document.getElementById("n-frames").value,
  };

  btn.disabled = true;
  status.classList.remove("hidden");
  msg.textContent = "Running simulation…";

  try {
    const res  = await fetch("/run", {
      method : "POST",
      headers: { "Content-Type": "application/json" },
      body   : JSON.stringify(payload),
    });
    const data = await res.json();
    simData = data;

    msg.textContent = "Building animation…";
    buildPlot(data);
    fillSummary(data.summary);

    document.getElementById("btn-viewer").disabled = false;
    showPanel("viewer");
    status.classList.add("hidden");

  } catch (err) {
    msg.textContent = "Error: " + err.message;
    console.error(err);
  } finally {
    btn.disabled = false;
  }
}

// ─────────────────────────────────────────────
// Earth sphere
// ─────────────────────────────────────────────
function earthSphere(n = 60) {
  const u = linspace(0, 2 * Math.PI, n);
  const v = linspace(0, Math.PI, n);
  const x = [], y = [], z = [];
  for (let vi of v) {
    const xrow = [], yrow = [], zrow = [];
    for (let ui of u) {
      xrow.push(Re * Math.cos(ui) * Math.sin(vi));
      yrow.push(Re * Math.sin(ui) * Math.sin(vi));
      zrow.push(Re * Math.cos(vi));
    }
    x.push(xrow); y.push(yrow); z.push(zrow);
  }
  return {
    type: "surface", x, y, z,
    surfacecolor: x.map(r => r.map(_ => 0)),
    colorscale: [[0, "rgb(10,40,80)"], [1, "rgb(30,80,120)"]],
    showscale: false, opacity: 1,
    lighting: { ambient: 0.6, diffuse: 0.8, specular: 0.3, roughness: 0.5 },
    lightposition: { x: 100000, y: 100000, z: 100000 },
    hoverinfo: "skip", name: "Earth",
  };
}

function linspace(a, b, n) {
  const arr = [];
  for (let i = 0; i < n; i++) arr.push(a + (b - a) * i / (n - 1));
  return arr;
}

// ─────────────────────────────────────────────
// Build Plotly scene
// ─────────────────────────────────────────────
function buildPlot(data) {
  const d = data;
  const traces = [];

  // Earth
  traces.push(earthSphere());

  // Ghost trajectory
  traces.push({
    type: "scatter3d", mode: "lines",
    x: d.x, y: d.x.map(_ => 0), z: d.y,
    line: { color: "rgba(255,200,100,0.1)", width: 2 },
    hoverinfo: "skip", showlegend: false,
  });

  // Ascent transfer ellipse
  traces.push({
    type: "scatter3d", mode: "lines",
    x: d.ellipse_x, y: d.ellipse_x.map(_ => 0), z: d.ellipse_y,
    line: { color: "magenta", width: 2, dash: "dash" },
    name: "Ascent ellipse", hoverinfo: "skip",
  });

  // Parking orbit
  if (d.needs_hohmann && d.park_orbit_x && d.park_orbit_x.length > 0) {
    traces.push({
      type: "scatter3d", mode: "lines",
      x: d.park_orbit_x, y: d.park_orbit_x.map(_ => 0), z: d.park_orbit_y,
      line: { color: "deepskyblue", width: 2, dash: "dash" },
      name: `Parking orbit (${d.summary.park_alt_km.toFixed(0)} km)`,
      hoverinfo: "skip",
    });
  }

  // Hohmann transfer ellipse
  if (d.needs_hohmann && d.transfer_x && d.transfer_x.length > 0) {
    traces.push({
      type: "scatter3d", mode: "lines",
      x: d.transfer_x, y: d.transfer_x.map(_ => 0), z: d.transfer_y,
      line: { color: "gold", width: 2, dash: "dot" },
      name: `Hohmann transfer ellipse`,
      hoverinfo: "skip",
    });
  }

  // Final target orbit
  traces.push({
    type: "scatter3d", mode: "lines",
    x: d.final_orbit_x, y: d.final_orbit_x.map(_ => 0), z: d.final_orbit_y,
    line: { color: "limegreen", width: 3 },
    name: `Target orbit (${d.summary.target_alt_km.toFixed(0)} km)`,
    hoverinfo: "skip",
  });

  // Circularization burn marker
  traces.push({
    type: "scatter3d", mode: "markers",
    x: [d.burn_x], y: [0], z: [d.burn_y],
    marker: { color: "cyan", size: 6, symbol: "diamond" },
    name: `Park. circ. burn  Δv = ${d.summary.delta_v_ms.toFixed(0)} m/s`,
  });

  // Launch marker
  traces.push({
    type: "scatter3d", mode: "markers",
    x: [d.launch_x], y: [0], z: [d.launch_y],
    marker: { color: "lime", size: 6 },
    name: "Launch",
  });

  // Dynamic trajectory
  traces.push({
    type: "scatter3d", mode: "lines",
    x: [d.x[0]], y: [0], z: [d.y[0]],
    line: { color: "darkorange", width: 4 },
    name: "Trajectory", hoverinfo: "skip",
  });

  // Rocket marker
  traces.push({
    type: "scatter3d", mode: "markers",
    x: [d.x[0]], y: [0], z: [d.y[0]],
    marker: { color: "white", size: 9, symbol: "circle",
              line: { color: "darkorange", width: 2 } },
    name: "Rocket", hoverinfo: "skip",
  });

  window._trajIdx   = traces.length - 2;
  window._rocketIdx = traces.length - 1;

  const orbitX = d.final_orbit_x || d.park_orbit_x || [];
  const orbitY = d.final_orbit_y || d.park_orbit_y || [];
  const maxR = orbitX.length > 0
    ? Math.max(...orbitX.map(Math.abs), ...orbitY.map(Math.abs)) * 1.3
    : Re * 1.8;
  const r = Math.max(maxR, Re * 1.5);

  const layout = {
    paper_bgcolor: "black",
    margin: { l: 0, r: 0, t: 0, b: 0 },
    autosize: true,
    scene: {
      bgcolor: "black",
      xaxis: { range: [-r, r], showgrid: false, zeroline: false, showticklabels: false, title: "" },
      yaxis: { range: [-r, r], showgrid: false, zeroline: false, showticklabels: false, title: "" },
      zaxis: { range: [-r, r], showgrid: false, zeroline: false, showticklabels: false, title: "" },
      camera: { eye: { x: 1.8, y: 0.8, z: 0.6 }, up: { x: 0, y: 0, z: 1 } },
      aspectmode: "cube",
    },
    legend: {
      font: { color: "white", size: 11 },
      bgcolor: "rgba(0,0,0,0.5)",
      bordercolor: "rgba(255,255,255,0.2)",
      borderwidth: 1, x: 0.01, y: 0.99,
    },
  };

  Plotly.newPlot("plot3d", traces, layout, { responsive: true, displayModeBar: false });

  frameIdx  = 0;
  isPlaying = false;
  buildControls(data);

  window.addEventListener("resize", () => Plotly.Plots.resize("plot3d"));
  setTimeout(() => Plotly.Plots.resize("plot3d"), 200);
}

// ─────────────────────────────────────────────
// Animation controls
// ─────────────────────────────────────────────
function buildControls(data) {
  const old = document.getElementById("anim-controls");
  if (old) old.remove();

  const bar = document.createElement("div");
  bar.id = "anim-controls";
  bar.style.cssText = `
    position: absolute; bottom: 16px; left: 50%; transform: translateX(-50%);
    display: flex; align-items: center; gap: 8px; z-index: 10;
    background: rgba(10,14,26,0.88); border: 1px solid rgba(255,255,255,0.12);
    border-radius: 10px; padding: 8px 14px; backdrop-filter: blur(4px);
  `;

  const btnStyle = `
    background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.15);
    color: #e2e8f0; border-radius: 6px; padding: 5px 12px;
    font-size: 12px; font-weight: 600; cursor: pointer; transition: background 0.15s;
  `;

  [["▶ ×1", 1], ["▶ ×5", 5], ["▶ ×20", 20], ["▶ ×100", 100]].forEach(([label, spd]) => {
    const b = document.createElement("button");
    b.textContent = label; b.style.cssText = btnStyle;
    b.onclick = () => { animSpeed = spd; startAnim(); };
    bar.appendChild(b);
  });

  const pause = document.createElement("button");
  pause.textContent = "⏸ Pause"; pause.style.cssText = btnStyle;
  pause.onclick = stopAnim;
  bar.appendChild(pause);

  const slider = document.createElement("input");
  slider.type = "range"; slider.min = 0;
  slider.max = data.t.length - 1; slider.value = 0;
  slider.style.cssText = "width: 200px; accent-color: #4fc3f7; cursor: pointer;";
  slider.oninput = function () {
    stopAnim();
    frameIdx = parseInt(this.value);
    updateFrame(data, frameIdx);
  };
  bar.appendChild(slider);
  window._slider = slider;

  document.querySelector(".plot-area").appendChild(bar);
}

// ─────────────────────────────────────────────
// Animation loop
// ─────────────────────────────────────────────
function startAnim() {
  stopAnim();
  if (!simData) return;
  isPlaying = true;
  function tick() {
    if (!isPlaying) return;
    frameIdx = Math.min(frameIdx + animSpeed, simData.t.length - 1);
    updateFrame(simData, frameIdx);
    if (window._slider) window._slider.value = frameIdx;
    if (frameIdx < simData.t.length - 1) {
      animTimer = setTimeout(tick, 16);
    } else {
      isPlaying = false;
    }
  }
  tick();
}

function stopAnim() {
  isPlaying = false;
  if (animTimer) { clearTimeout(animTimer); animTimer = null; }
}

function updateFrame(data, i) {
  Plotly.restyle("plot3d", {
    x: [data.x.slice(0, i + 1)],
    y: [data.x.slice(0, i + 1).map(_ => 0)],
    z: [data.y.slice(0, i + 1)],
  }, [window._trajIdx]);

  Plotly.restyle("plot3d", {
    x: [[data.x[i]]],
    y: [[0]],
    z: [[data.y[i]]],
  }, [window._rocketIdx]);

  updateHUD(data, i);
}

// ─────────────────────────────────────────────
// HUD
// ─────────────────────────────────────────────
function updateHUD(data, i) {
  const t   = data.t[i];
  const alt = data.alt[i];
  const spd = data.speed[i];
  const s   = data.summary;

  const mins = Math.floor(t / 60).toString().padStart(2, "0");
  const secs = Math.floor(t % 60).toString().padStart(2, "0");
  document.getElementById("hud-clock").textContent = `T+ ${mins}:${secs}`;

  let phase = null;
  const burnouts = s.stage_burnouts || [];
  for (let k = 0; k < burnouts.length; k++) {
    if (t < burnouts[k]) { phase = `Stage ${k + 1} burn`; break; }
  }
  if (phase === null) {
    phase = t < s.t_coast_start ? "Coast to apoapsis" : "Circular orbit";
  }
  document.getElementById("hud-phase").textContent = phase;

  document.getElementById("hud-alt").textContent      = (alt / 1000).toFixed(1) + " km";
  document.getElementById("hud-speed").textContent    = (spd / 1000).toFixed(2) + " km/s";

  const accel = data.accel_g ? Math.abs(data.accel_g[i]) : 0;
  document.getElementById("hud-accel").textContent    = Math.min(accel, 20).toFixed(2) + " g";

  const dr = data.downrange ? data.downrange[i] : 0;
  document.getElementById("hud-downrange").textContent =
  dr >= 1e6 ? (dr / 1e6).toFixed(2) + " Mm" : (dr / 1000).toFixed(1) + " km";

  const mass = data.mass ? data.mass[i] : 0;
  document.getElementById("hud-mass").textContent = (mass / 1000).toFixed(1) + " t";
}

// ─────────────────────────────────────────────
// Summary tables
// ─────────────────────────────────────────────
function fillSummary(s) {
  const stageRows = (s.stage_burnouts || []).map(
    (tb, i) => [`Stage ${i + 1} burnout`, tb.toFixed(1) + " s"]
  );

  const summaryRows = [
    ...stageRows,
    ["Max altitude",         s.max_alt_km.toFixed(1) + " km"],
    ["Max speed",            s.max_speed_kms.toFixed(2) + " km/s"],
    ["Max dynamic pressure", s.max_q_kpa.toFixed(1) + " kPa"],
    ["Parking orbit",        s.park_alt_km.toFixed(1) + " km"],
    ["Δv circularization",   s.delta_v_ms.toFixed(0) + " m/s"],
    ["Target orbit",         s.target_alt_km.toFixed(0) + " km"],
    ["Target v_circ",        s.v_target_kms.toFixed(2) + " km/s"],
    ["Orbital period",       s.T_orbit_min.toFixed(1) + " min"],
  ];

  if (s.needs_hohmann) {
    summaryRows.push(
      ["── Hohmann transfer ──", ""],
      ["Δv burn 1 (perigee)",  s.transfer_dv1.toFixed(0) + " m/s"],
      ["Δv burn 2 (apogee)",   s.transfer_dv2.toFixed(0) + " m/s"],
      ["Δv total",             s.transfer_dv_total.toFixed(0) + " m/s"],
      ["Transfer coast time",  s.transfer_time_min.toFixed(0) + " min"],
    );
  }

  const orbitalRows = [
    ["Eccentricity (MECO)",  s.ecc_meco.toFixed(4)],
    ["Apoapsis (MECO)",      s.apo_km.toFixed(1) + " km"],
    ["Periapsis (MECO)",     s.peri_km.toFixed(1) + " km"],
    ["Eccentricity (final)", s.ecc_final.toFixed(6)],
  ];

  const fill = (id, rows) => {
    document.getElementById(id).innerHTML =
      rows.map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join("");
  };

  fill("summary-table", summaryRows);
  fill("orbital-table", orbitalRows);
  document.getElementById("summary-card").style.display = "block";
  document.getElementById("orbital-card").style.display = "block";
}