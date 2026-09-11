const Re = 6.371e6;
const Mu = 3.986004418e14;
const OMEGA_EARTH = 7.2921150e-5; // rad/s — Earth's rotation rate

// Layer visibility toggles (Ground track / Terminator / Staging markers)
const layerVisible = { groundtrack: true, terminator: true, staging: true };

// Fixed inertial sun direction (arbitrary but constant — the sim has no
// real calendar epoch, so we just pick a direction that gives a nice
// day/night split and terminator geometry).
const SUN_DIR = (() => {
  const v = [0.55, -0.7, 0.35];
  const n = Math.hypot(v[0], v[1], v[2]);
  return [v[0] / n, v[1] / n, v[2] / n];
})();

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

// The loaded values above are the maximum usable propellant capacities for
// the simplified stage model. Keep a separate immutable limit when users edit.
Object.values(ROCKET_PRESETS).forEach(preset => preset.stages.forEach(stage => {
  stage.maxProp = stage.prop;
}));
let selectedRocketKey = "falcon9";

let stageCount = 0; // number of currently rendered stages, assigned by renderStages()

// ─────────────────────────────────────────────
// Dynamic stage cards
// ─────────────────────────────────────────────
function stageCardHTML(i, s) {
  s = s || { dry: 20000, prop: 100000, thrust: 1000000, isp: 300, cd: 0.3, area: 10.52, propellant: "rp1lox", maxProp: null };
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
          <input type="number" id="s${i}-prop" value="${s.prop}" min="0" ${s.maxProp ? `max="${s.maxProp}"` : ""}>
          <small>${s.maxProp ? `Real capacity max: ${s.maxProp.toLocaleString("en-US")} kg` : "Custom stage: no real capacity limit"}</small>
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
  renderFuelAssessment();
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
  renderFuelAssessment();
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
    maxProp   : Number(document.getElementById(`s${i}-prop`).max) || null,
  };
}

// ─────────────────────────────────────────────
// Rocket presets selection
// ─────────────────────────────────────────────
function selectRocketPreset(btn, key) {
  document.querySelectorAll(".rocket-preset-btn").forEach(b => b.classList.remove("active"));
  btn.classList.add("active");

  selectedRocketKey = key;
  if (key === "custom") { renderFuelAssessment(); return; }

  const preset = ROCKET_PRESETS[key];
  document.getElementById("vehicle-name").value = preset.name;
  document.getElementById("payload-mass").value = preset.payload;
  renderStages(preset.stages);
  renderFuelAssessment();
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

// Pre-flight estimate only: the full numerical trajectory is still the
// authoritative validation. These allowances cover losses the ideal rocket
// equation cannot model (drag, gravity turn and PEG insertion geometry).
const G0 = 9.80665;
const EARTH_ROTATION_SPEED = 465.1;
const ASCENT_LOSS_ALLOWANCE = 1300; // m/s; calibrated to the simulator's PEG ascent model
const OMS_CIRCULARIZATION_RESERVE = 2200; // m/s

function idealDeltaV(stages, payloadKg, propellantScale = 1) {
  let mass = payloadKg + stages.reduce(
    (sum, s) => sum + s.dry + s.prop * propellantScale, 0
  );
  let dv = 0;
  for (const stage of stages) {
    const propellant = stage.prop * propellantScale;
    const massAfterBurn = mass - propellant;
    if (!(mass > massAfterBurn && massAfterBurn > 0 && stage.isp > 0)) return NaN;
    dv += G0 * stage.isp * Math.log(mass / massAfterBurn);
    mass = massAfterBurn - stage.dry;
  }
  return dv;
}

function hohmannDeltaV(fromAltM, toAltM) {
  if (toAltM <= fromAltM) return 0;
  const r1 = Re + fromAltM, r2 = Re + toAltM;
  const dv1 = Math.sqrt(Mu / r1) * (Math.sqrt(2 * r2 / (r1 + r2)) - 1);
  const dv2 = Math.sqrt(Mu / r2) * (1 - Math.sqrt(2 * r1 / (r1 + r2)));
  return Math.abs(dv1) + Math.abs(dv2);
}

function estimatedReentryDeltaV(altM) {
  const r = Re + Math.max(altM, 1), rp = Re;
  const vCircular = Math.sqrt(Mu / r);
  return Math.max(0, vCircular - Math.sqrt(Mu * (2 / r - 1 / ((r + rp) / 2))));
}

function fuelAssessment() {
  const altKm = selectedOrbit.key === "custom"
    ? parseFloat(document.getElementById("custom-alt").value) : selectedOrbit.alt;
  const payloadKg = parseFloat(document.getElementById("payload-mass").value);
  const omsBudget = parseFloat(document.getElementById("oms-dv-budget").value);
  const maneuverDv = document.getElementById("maneuver-enabled").checked
    ? Math.abs(parseFloat(document.getElementById("maneuver-dv").value)) : 0;
  const reentryDv = document.getElementById("reentry-enabled").checked
    ? estimatedReentryDeltaV(altKm * 1000) : 0;
  const stages = Array.from({ length: stageCount }, (_, i) => readStageFromDOM(i));
  const numericStage = s => [s.dry, s.prop, s.thrust, s.cd, s.area]
    .every(value => Number.isFinite(value) && value >= 0) && Number.isFinite(s.isp) && s.isp > 0;
  if (!Number.isFinite(altKm) || altKm <= 0 || !Number.isFinite(payloadKg) || payloadKg < 0 ||
      !Number.isFinite(omsBudget) || !Number.isFinite(maneuverDv) || !Number.isFinite(reentryDv) ||
      stages.some(s => !numericStage(s))) {
    return { valid: false, reason: "Enter valid vehicle and orbit values to calculate fuel." };
  }

  // The backend ascends to a 250-km parking orbit, then uses a Hohmann
  // transfer for high targets. Mirror that mission architecture here.
  const targetM = altKm * 1000;
  const parkingM = Math.min(targetM, 250e3);
  const ascentRequired = Math.sqrt(Mu / (Re + parkingM)) - EARTH_ROTATION_SPEED + ASCENT_LOSS_ALLOWANCE;
  const transferRequired = targetM > 2000e3 && targetM > parkingM * 2
    ? hohmannDeltaV(parkingM, targetM) : 0;
  const omsRequired = OMS_CIRCULARIZATION_RESERVE + transferRequired + maneuverDv + reentryDv;
  const availableDv = idealDeltaV(stages, payloadKg);
  const overCapacity = stages.filter(s => s.maxProp && s.prop > s.maxProp + 1e-6);

  // Determine the minimum common loading factor while preserving the stage
  // split selected by the user, rather than inventing a different vehicle.
  let requiredScale = null;
  if (Number.isFinite(availableDv)) {
    let high = 1;
    while (idealDeltaV(stages, payloadKg, high) < ascentRequired && high < 16) high *= 2;
    if (idealDeltaV(stages, payloadKg, high) >= ascentRequired) {
      let low = 0;
      for (let j = 0; j < 40; j++) {
        const mid = (low + high) / 2;
        if (idealDeltaV(stages, payloadKg, mid) >= ascentRequired) high = mid;
        else low = mid;
      }
      requiredScale = high;
    }
  }
  const ascentOk = Number.isFinite(availableDv) && availableDv >= ascentRequired * 1.02 && !overCapacity.length;
  const omsOk = omsBudget >= omsRequired;
  return { valid: true, stages, ascentRequired, transferRequired, maneuverDv, reentryDv, omsRequired, omsBudget, overCapacity,
    availableDv, requiredScale, sufficient: ascentOk && omsOk };
}

function kg(value) { return Math.round(value).toLocaleString("en-US") + " kg"; }

function renderFuelAssessment() {
  const box = document.getElementById("fuel-estimate");
  if (!box) return null;
  updateVehicleMass();
  const a = fuelAssessment();
  if (!a.valid) {
    box.className = "fuel-estimate warning";
    box.textContent = a.reason;
    return a;
  }
  const stageRows = a.requiredScale === null
    ? "<li>The selected stack cannot provide the estimated ascent Δv.</li>"
    : a.stages.map((s, i) => {
        const needed = s.prop * a.requiredScale;
        const delta = s.prop - needed;
        return `<li>Stage ${i + 1}: ${kg(needed)} needed / ${kg(s.prop)} loaded` +
          (delta >= 0 ? ` (${kg(delta)} reserve)` : ` (${kg(-delta)} short)`) + "</li>";
      }).join("");
  const sufficient = a.sufficient;
  const reentryOutput = document.getElementById("reentry-dv");
  reentryOutput.textContent = `${Math.round(a.reentryDv).toLocaleString("en-US")} m/s (impact trajectory)`;
  const candidates = Object.entries(ROCKET_PRESETS).filter(([key, p]) => key !== selectedRocketKey &&
    idealDeltaV(p.stages, parseFloat(document.getElementById("payload-mass").value)) >= a.ascentRequired * 1.02).map(([, p]) => p.name);
  const recommendation = a.overCapacity.length || !sufficient
    ? `<div>Recommended higher-capacity presets: <strong>${candidates.join(", ") || "none for this payload"}</strong></div>` : "";
  box.className = "fuel-estimate " + (sufficient ? "ok" : "warning");
  box.innerHTML = `
    <div class="fuel-status">${sufficient ? "Fuel budget looks sufficient" : "Insufficient fuel budget — launch blocked"}</div>
    <div>Ascent Δv: <strong>${(a.ascentRequired / 1000).toFixed(2)} km/s required</strong> · ${(a.availableDv / 1000).toFixed(2)} km/s ideal capacity</div>
    <ul class="fuel-stage-list">${stageRows}</ul>
    <div>OMS: <strong>${Math.round(a.omsRequired).toLocaleString("en-US")} m/s required</strong> · ${Math.round(a.omsBudget).toLocaleString("en-US")} m/s configured${a.maneuverDv || a.reentryDv ? " (includes selected burns)" : a.transferRequired ? " (includes transfer)" : ""}</div><button type="button" class="fuel-fill-btn" onclick="applyRequiredOms(${Math.ceil(a.omsRequired / 100) * 100})">Set required OMS Δv</button>${recommendation}`;
  return a;
}

function payloadKgForDisplay(stages) {
  return parseFloat(document.getElementById("payload-mass").value) + stages.reduce((sum, s) => sum + s.dry + s.prop, 0);
}

function updateVehicleMass() {
  const stages = Array.from({ length: stageCount }, (_, i) => readStageFromDOM(i));
  const payload = parseFloat(document.getElementById("payload-mass").value);
  const mass = Number.isFinite(payload) ? payload + stages.reduce((sum, s) => sum + (Number.isFinite(s.dry) ? s.dry : 0) + (Number.isFinite(s.prop) ? s.prop : 0), 0) : 0;
  document.getElementById("vehicle-mass").textContent = `Vehicle mass at liftoff: ${kg(mass)}`;
}

function applyRequiredOms(value) { document.getElementById("oms-dv-budget").value = value; renderFuelAssessment(); }

const ORBIT_LABELS = {
  iss:    "ISS — 400 km LEO",
  sso:    "SSO — 600 km polar",
  meo:    "MEO — 20 000 km",
  geo:    "GEO — 35 786 km",
  custom: "Custom altitude",
};

function toggleManeuverFields() {
  const enabled = document.getElementById("maneuver-enabled").checked;
  document.getElementById("maneuver-fields").style.display = enabled ? "block" : "none";
  renderFuelAssessment();
}

function toggleReentryFields() {
  const enabled = document.getElementById("reentry-enabled").checked;
  document.getElementById("reentry-fields").style.display = enabled ? "block" : "none";
  renderFuelAssessment();
}

function showFuelWarning(assessment) {
  const modal = document.getElementById("fuel-modal");
  const ascent = assessment && Number.isFinite(assessment.availableDv)
    ? `The vehicle provides ${(assessment.availableDv / 1000).toFixed(2)} km/s of ideal Δv, while ${(assessment.ascentRequired / 1000).toFixed(2)} km/s is required.`
    : "Some vehicle values are invalid.";
  const oms = assessment && assessment.valid
    ? ` The OMS budget is ${Math.round(assessment.omsBudget)} m/s; this mission needs ${Math.round(assessment.omsRequired)} m/s.` : "";
  document.getElementById("fuel-modal-message").textContent = `${ascent}${oms} Increase propellant or OMS Δv, then try again.`;
  modal.classList.remove("hidden");
}

function closeFuelWarning() {
  document.getElementById("fuel-modal").classList.add("hidden");
}

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
  renderFuelAssessment();
}

document.getElementById("custom-alt").addEventListener("input", function () {
  const alt = parseFloat(this.value);
  if (alt) document.getElementById("orbit-v").innerHTML =
    `v<sub>circ</sub> ≈ ${V_CIRC(alt)} km/s`;
});

// Recalculate while configuring, including dynamically-added stages.
document.addEventListener("input", event => {
  if (event.target.closest("#panel-config")) { updateVehicleMass(); renderFuelAssessment(); }
});
document.addEventListener("change", event => {
  if (event.target.closest("#panel-config")) renderFuelAssessment();
});
renderFuelAssessment();

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

  const assessment = renderFuelAssessment();
  if (!assessment || !assessment.valid || !assessment.sufficient) {
    showFuelWarning(assessment);
    return;
  }

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
    payload_mass  : document.getElementById("payload-mass").value,
    target_alt    : altKm * 1000,   // metres
    t_vertical    : document.getElementById("t-vertical").value,
    n_orbits      : document.getElementById("n-orbits").value,
    oms_dv_budget : document.getElementById("oms-dv-budget").value,
    second_maneuver: {
      enabled : document.getElementById("maneuver-enabled").checked,
      delta_v : document.getElementById("maneuver-dv").value,
      wait_min: document.getElementById("maneuver-wait").value,
    },
    reentry: {
      enabled : document.getElementById("reentry-enabled").checked,
      delta_v : 0, // calculated authoritatively by the backend from orbital state
      wait_min: document.getElementById("reentry-wait").value,
    },
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
// Earth sphere — procedural land/ocean/ice texture + day/night shading
// ─────────────────────────────────────────────
//
// NOTE on a bug fixed here: an earlier version baked day/night into the
// surfacecolor scalar itself (6 discrete categories through a "stepped"
// colorscale). That broke two ways: (1) Plotly requires a colorscale's
// stops to start at exactly 0 and end at exactly 1 — the stepped-stop
// trick landed the last stop at 0.999999, which is invalid and made
// Plotly silently fall back to its own default colorscale (the
// unexpected orange/cream rendering). (2) Even fixed, Plotly's surface
// trace Gouraud-shades (linearly blends) the *already colorscale-mapped*
// RGB across each face, so "hard" category steps still blend into muddy
// in-between hues wherever neighbouring grid vertices differ.
//
// Fix: keep surfacecolor to a genuinely continuous land/ocean/ice value
// (valid, strictly-increasing colorscale from 0 to 1 — blending here is
// correct and desired, it's what makes coastlines look smooth) and hand
// day/night shading back to Plotly's real lighting model via
// `lightposition`, exactly like the original implementation did.
function landMask(latDeg, lonDeg) {
  // Deterministic pseudo-continents: a handful of overlapping sine lobes.
  // Not real coastlines, but gives a non-uniform, "planet-like" surface
  // instead of a flat ocean-colored ball. Returns a continuous value
  // (not thresholded) so the land/ocean colorscale transition is smooth.
  const lat = latDeg * Math.PI / 180;
  const lon = lonDeg * Math.PI / 180;
  let s = 0;
  s += Math.sin(3 * lon + 0.6) * Math.cos(2 * lat);
  s += Math.sin(2 * lon - 1.9) * Math.cos(3 * lat + 0.4) * 0.8;
  s += Math.sin(5 * lon + 2.2) * Math.cos(1.5 * lat - 0.7) * 0.5;
  s += Math.cos(4 * lon - 0.3) * Math.sin(2.5 * lat + 1.1) * 0.4;
  return s;
}

function smoothstep(edge0, edge1, x) {
  const t = Math.min(1, Math.max(0, (x - edge0) / (edge1 - edge0)));
  return t * t * (3 - 2 * t);
}

// Valid Plotly colorscale: strictly increasing stops, starts at 0, ends
// at 1. Ocean -> coastline -> land -> polar ice, all continuous.
const EARTH_COLORSCALE = [
  [0.00, "rgb(8,40,90)"],
  [0.40, "rgb(15,65,120)"],
  [0.44, "rgb(90,120,60)"],
  [0.70, "rgb(50,110,55)"],
  [0.90, "rgb(70,100,55)"],
  [1.00, "rgb(245,248,250)"],
];

function earthSphere(n = 90) {
  const u = linspace(0, 2 * Math.PI, n);
  const v = linspace(0, Math.PI, n);
  const x = [], y = [], z = [], surfacecolor = [];
  for (let vi of v) {
    const xrow = [], yrow = [], zrow = [], crow = [];
    const latDeg = 90 - vi * 180 / Math.PI;
    for (let ui of u) {
      const xi = Re * Math.cos(ui) * Math.sin(vi);
      const yi = Re * Math.sin(ui) * Math.sin(vi);
      const zi = Re * Math.cos(vi);
      xrow.push(xi); yrow.push(yi); zrow.push(zi);

      const lonDeg = ui * 180 / Math.PI;
      // Land fraction in [0,1]; ~0.35 threshold gives a roughly
      // Earth-like ocean/land ratio, smoothed over a narrow band so
      // coastlines aren't jagged.
      const landRaw  = landMask(latDeg, lonDeg);
      const landFrac = smoothstep(0.25, 0.45, landRaw);
      let scalar = 0.40 + landFrac * 0.30; // 0.40 ocean..0.70 land

      // Blend toward polar ice near the poles.
      const iceFrac = smoothstep(72, 85, Math.abs(latDeg));
      scalar = scalar * (1 - iceFrac) + 1.0 * iceFrac;

      crow.push(scalar);
    }
    x.push(xrow); y.push(yrow); z.push(zrow); surfacecolor.push(crow);
  }

  // Sun far away along SUN_DIR — Plotly's Lambertian shading then does
  // the day/night falloff for us, in sync with the terminator line below.
  const D = 5e8;
  return {
    type: "surface", x, y, z,
    surfacecolor,
    colorscale: EARTH_COLORSCALE,
    cmin: 0, cmax: 1,
    showscale: false, opacity: 1,
    lighting: { ambient: 0.22, diffuse: 0.85, specular: 0.1, roughness: 0.6 },
    lightposition: { x: SUN_DIR[0] * D, y: SUN_DIR[1] * D, z: SUN_DIR[2] * D },
    hoverinfo: "skip", name: "Earth",
  };
}

// ─────────────────────────────────────────────
// Terminator (day/night boundary) — great circle perpendicular to SUN_DIR
// ─────────────────────────────────────────────
function terminatorTrace(r = Re * 1.003, n = 120) {
  // Any two unit vectors orthogonal to SUN_DIR and to each other span the
  // terminator plane.
  const s = SUN_DIR;
  let ref = Math.abs(s[2]) < 0.9 ? [0, 0, 1] : [1, 0, 0];
  const e1 = normalize(cross(s, ref));
  const e2 = normalize(cross(s, e1));
  const x = [], y = [], z = [];
  for (let i = 0; i <= n; i++) {
    const a = 2 * Math.PI * i / n;
    x.push(r * (e1[0] * Math.cos(a) + e2[0] * Math.sin(a)));
    y.push(r * (e1[1] * Math.cos(a) + e2[1] * Math.sin(a)));
    z.push(r * (e1[2] * Math.cos(a) + e2[2] * Math.sin(a)));
  }
  return {
    type: "scatter3d", mode: "lines",
    x, y, z,
    line: { color: "rgba(255,220,120,0.55)", width: 3 },
    name: "Terminator", hoverinfo: "skip",
    visible: layerVisible.terminator,
  };
}

function cross(a, b) {
  return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
}
function normalize(v) {
  const n = Math.hypot(v[0], v[1], v[2]) || 1;
  return [v[0] / n, v[1] / n, v[2] / n];
}

function linspace(a, b, n) {
  const arr = [];
  for (let i = 0; i < n; i++) arr.push(a + (b - a) * i / (n - 1));
  return arr;
}

// ─────────────────────────────────────────────
// Ground track — sub-satellite point projected onto the rotating Earth
// ─────────────────────────────────────────────
// Physics and rendering both use the geocentric convention: X–Y is the
// equatorial plane and Z points north. The current 2D solver therefore
// produces an equatorial ground track (inclination is a future 3D feature).
function groundPoint(X, Y, t) {
  return { lat: 0, lon: Math.atan2(Y, X) * 180 / Math.PI };
}

function latLonToXYZ(latDeg, lonDeg, r) {
  const lat = latDeg * Math.PI / 180, lon = lonDeg * Math.PI / 180;
  return [r * Math.cos(lon) * Math.cos(lat), r * Math.sin(lon) * Math.cos(lat), r * Math.sin(lat)];
}

function groundTrackXYZ(data) {
  const r = Re * 1.004;
  const xs = [], ys = [], zs = [];
  for (let i = 0; i < data.t.length; i++) {
    const { lat, lon } = groundPoint(data.x[i], data.y[i], data.t[i]);
    const [gx, gy, gz] = latLonToXYZ(lat, lon, r);
    xs.push(gx); ys.push(gy); zs.push(gz);
  }
  return { xs, ys, zs };
}

function interp1(tArr, vArr, t) {
  if (t <= tArr[0]) return vArr[0];
  if (t >= tArr[tArr.length - 1]) return vArr[vArr.length - 1];
  let lo = 0, hi = tArr.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (tArr[mid] <= t) lo = mid; else hi = mid;
  }
  const f = (t - tArr[lo]) / (tArr[hi] - tArr[lo] || 1);
  return vArr[lo] + f * (vArr[hi] - vArr[lo]);
}

function stagingMarkerTrace(data) {
  const burnouts = (data.summary && data.summary.stage_burnouts) || [];
  const x = [], y = [], z = [], text = [];
  burnouts.forEach((tb, k) => {
    const xi = interp1(data.t, data.x, tb);
    const yi = interp1(data.t, data.y, tb);
    x.push(xi); y.push(0); z.push(yi);
    text.push(k < burnouts.length - 1 ? `Stage ${k + 1} sep.` : "MECO");
  });
  return {
    type: "scatter3d", mode: "markers+text",
    x, y, z, text,
    textposition: "top center",
    textfont: { color: "#ffb454", size: 10 },
    marker: { color: "#ffb454", size: 5, symbol: "diamond-open" },
    name: "Staging events", hoverinfo: "text",
    visible: layerVisible.staging,
  };
}

// ─────────────────────────────────────────────
// Build Plotly scene
// ─────────────────────────────────────────────
function buildPlot(data) {
  const d = data;
  const traces = [];

  // Earth
  traces.push(earthSphere());

  // Terminator (day/night boundary)
  traces.push(terminatorTrace());
  window._terminatorIdx = traces.length - 1;

  // Staging event markers (stage separation / MECO positions)
  traces.push(stagingMarkerTrace(d));
  window._stagingIdx = traces.length - 1;

  // Ground track (progressive, mirrors the trajectory trace) + current
  // sub-satellite marker
  const gt = groundTrackXYZ(d);
  window._groundTrackData = gt;
  traces.push({
    type: "scatter3d", mode: "lines",
    x: [gt.xs[0]], y: [gt.ys[0]], z: [gt.zs[0]],
    line: { color: "rgba(120,255,180,0.8)", width: 3 },
    name: "Ground track", hoverinfo: "skip",
    visible: layerVisible.groundtrack,
  });
  window._groundTrackIdx = traces.length - 1;
  traces.push({
    type: "scatter3d", mode: "markers",
    x: [gt.xs[0]], y: [gt.ys[0]], z: [gt.zs[0]],
    marker: { color: "#78ffb4", size: 5, symbol: "circle" },
    name: "Sub-satellite point", hoverinfo: "skip",
    visible: layerVisible.groundtrack,
  });
  window._subSatIdx = traces.length - 1;

  // Ghost trajectory
  traces.push({
    type: "scatter3d", mode: "lines",
    x: d.x, y: d.y, z: d.x.map(_ => 0),
    line: { color: "rgba(255,200,100,0.1)", width: 2 },
    hoverinfo: "skip", showlegend: false,
  });

  // Ascent transfer ellipse
  traces.push({
    type: "scatter3d", mode: "lines",
    x: d.ellipse_x, y: d.ellipse_y, z: d.ellipse_x.map(_ => 0),
    line: { color: "magenta", width: 2, dash: "dash" },
    name: "Ascent ellipse", hoverinfo: "skip",
  });

  // Parking orbit
  if (d.needs_hohmann && d.park_orbit_x && d.park_orbit_x.length > 0) {
    traces.push({
      type: "scatter3d", mode: "lines",
      x: d.park_orbit_x, y: d.park_orbit_y, z: d.park_orbit_x.map(_ => 0),
      line: { color: "deepskyblue", width: 2, dash: "dash" },
      name: `Parking orbit (${d.summary.park_alt_km.toFixed(0)} km)`,
      hoverinfo: "skip",
    });
  }

  // Hohmann transfer ellipse
  if (d.needs_hohmann && d.transfer_x && d.transfer_x.length > 0) {
    traces.push({
      type: "scatter3d", mode: "lines",
      x: d.transfer_x, y: d.transfer_y, z: d.transfer_x.map(_ => 0),
      line: { color: "gold", width: 2, dash: "dot" },
      name: `Hohmann transfer ellipse`,
      hoverinfo: "skip",
    });
  }

  // Post-maneuver orbit (second maneuver, if enabled and it produced a trace)
  if (d.maneuver_x && d.maneuver_x.length > 0) {
    traces.push({
      type: "scatter3d", mode: "lines",
      x: d.maneuver_x, y: d.maneuver_y, z: d.maneuver_x.map(_ => 0),
      line: { color: "magenta", width: 2, dash: "dash" },
      name: `Post-maneuver orbit`,
      hoverinfo: "skip",
    });
  }

  // Final target orbit
  traces.push({
    type: "scatter3d", mode: "lines",
    x: d.final_orbit_x, y: d.final_orbit_y, z: d.final_orbit_x.map(_ => 0),
    line: { color: "limegreen", width: 3 },
    name: `Target orbit (${d.summary.target_alt_km.toFixed(0)} km)`,
    hoverinfo: "skip",
  });

  // Δv burn markers — one per burn (circularization, Hohmann injection/
  // circularization, second maneuver, deorbit), styled by whether each is
  // prograde (speeds up, cyan upward triangle) or retrograde (slows down,
  // orange-red downward triangle).
  (d.burn_markers || []).forEach(b => {
    const retro = !!b.retrograde;
    traces.push({
      type: "scatter3d", mode: "markers",
      x: [b.x], y: [b.y], z: [0],
      marker: {
        color: retro ? "#ff5252" : "cyan",
        size: 7,
        symbol: retro ? "cross" : "diamond",
      },
      name: `${b.label}  Δv = ${b.dv >= 0 ? "+" : ""}${b.dv.toFixed(0)} m/s` +
        (retro ? " (retrograde)" : ""),
    });
  });

  // Launch marker
  traces.push({
    type: "scatter3d", mode: "markers",
    x: [d.launch_x], y: [d.launch_y], z: [0],
    marker: { color: "lime", size: 6 },
    name: "Launch",
  });

  // Dynamic trajectory
  traces.push({
    type: "scatter3d", mode: "lines",
    x: [d.x[0]], y: [d.y[0]], z: [0],
    line: { color: "darkorange", width: 4 },
    name: "Trajectory", hoverinfo: "skip",
  });

  // Rocket marker
  traces.push({
    type: "scatter3d", mode: "markers",
    x: [d.x[0]], y: [d.y[0]], z: [0],
    marker: { color: "white", size: 9, symbol: "circle",
              line: { color: "darkorange", width: 2 } },
    name: "Rocket", hoverinfo: "skip",
  });

  window._trajIdx   = traces.length - 2;
  window._rocketIdx = traces.length - 1;

  const orbitX = d.final_orbit_x || d.park_orbit_x || [];
  const orbitY = d.final_orbit_y || d.park_orbit_y || [];
  // Include every orbit trace that might be drawn (target, transfer, and
  // especially the post-maneuver orbit) when sizing the scene — otherwise
  // the axis range gets fixed to whichever is smallest and anything
  // bigger (e.g. a raised orbit after the second maneuver) gets clipped
  // outside the box entirely, which looks like "nothing renders" no
  // matter how far the camera zooms out.
  const allX = [...orbitX, ...(d.transfer_x || []), ...(d.maneuver_x || [])];
  const allY = [...orbitY, ...(d.transfer_y || []), ...(d.maneuver_y || [])];
  const maxR = allX.length > 0
    ? Math.max(...allX.map(Math.abs), ...allY.map(Math.abs)) * 1.3
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
      // X–Y is the equatorial orbital plane; Z is north.
      camera: { eye: { x: 0, y: 0, z: 2.4 }, up: { x: 0, y: 1, z: 0 } },
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
    flex-wrap: wrap; justify-content: center; max-width: 92vw;
    background: rgba(10,14,26,0.88); border: 1px solid rgba(255,255,255,0.12);
    border-radius: 10px; padding: 8px 14px; backdrop-filter: blur(4px);
  `;

  const btnStyle = `
    background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.15);
    color: #e2e8f0; border-radius: 6px; padding: 5px 12px;
    font-size: 12px; font-weight: 600; cursor: pointer; transition: background 0.15s;
  `;

  [["▶ ×1", 1], ["▶ ×5", 5], ["▶ ×20", 20], ["▶ ×50", 50], ["▶ ×100", 100], ["▶ ×150", 150], ["▶ ×200", 200]].forEach(([label, spd]) => {
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
    y: [data.y.slice(0, i + 1)],
    z: [data.x.slice(0, i + 1).map(_ => 0)],
  }, [window._trajIdx]);

  Plotly.restyle("plot3d", {
    x: [[data.x[i]]],
    y: [[data.y[i]]],
    z: [[0]],
  }, [window._rocketIdx]);

  // Ground track + sub-satellite point, kept in sync with the trajectory
  const gt = window._groundTrackData;
  if (gt) {
    Plotly.restyle("plot3d", {
      x: [gt.xs.slice(0, i + 1)],
      y: [gt.ys.slice(0, i + 1)],
      z: [gt.zs.slice(0, i + 1)],
    }, [window._groundTrackIdx]);

    Plotly.restyle("plot3d", {
      x: [[gt.xs[i]]],
      y: [[gt.ys[i]]],
      z: [[gt.zs[i]]],
    }, [window._subSatIdx]);
  }

  updateHUD(data, i);
}

// ─────────────────────────────────────────────
// Layer toggles (Ground track / Terminator / Staging markers)
// ─────────────────────────────────────────────
function toggleLayer(name, visible) {
  layerVisible[name] = visible;
  const idxMap = {
    groundtrack: [window._groundTrackIdx, window._subSatIdx],
    terminator:  [window._terminatorIdx],
    staging:     [window._stagingIdx],
  };
  const idxs = (idxMap[name] || []).filter(i => i !== undefined);
  if (idxs.length) Plotly.restyle("plot3d", { visible }, idxs);
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
    if (t < s.t_apo) {
      phase = "Coast to apoapsis";
    } else if (s.needs_hohmann && s.t_park_end !== null && t < s.t_park_end) {
      phase = "Parking orbit coast";
    } else if (s.needs_hohmann && t < s.t_coast_start) {
      phase = "Hohmann transfer coast";
    } else if (s.t_maneuver !== null && s.t_maneuver !== undefined && t < s.t_maneuver) {
      phase = "Circular orbit";
    } else if (s.t_reentry !== null && s.t_reentry !== undefined && t >= s.t_reentry) {
      phase = "Atmospheric reentry";
    } else if (s.t_maneuver !== null && s.t_maneuver !== undefined) {
      phase = "Post-maneuver orbit";
    } else {
      phase = "Circular orbit";
    }
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

  // ── Propellant remaining (active stage) ──
  const stageIdx = data.active_stage ? data.active_stage[i] : null;
  const frac     = data.prop_frac ? data.prop_frac[i] : null;
  const propEl   = document.getElementById("hud-propellant");
  if (stageIdx === null || stageIdx === undefined || frac === null) {
    // Coasting — no ascent stage burning, but the payload may still have
    // OMS Δv left to spend on upcoming burns (circularization, Hohmann,
    // second maneuver). Show that instead of a blank dash.
    const burns = s.oms_burns || [];
    const spent = burns.filter(b => b.t <= t).reduce((sum, b) => sum + b.dv, 0);
    const remaining = (s.oms_dv_budget || 0) - spent;
    if (s.oms_dv_budget) {
      propEl.textContent = `OMS: ${remaining.toFixed(0)} / ${s.oms_dv_budget.toFixed(0)} m/s left`;
    } else {
      propEl.textContent = "—";
    }
  } else {
    const totalKg     = s.stage_prop_masses_kg ? s.stage_prop_masses_kg[stageIdx] : null;
    const remainingT  = totalKg !== null ? (frac * totalKg / 1000).toFixed(1) : null;
    const totalT      = totalKg !== null ? (totalKg / 1000).toFixed(1) : null;
    propEl.textContent = `Stage ${stageIdx + 1}: ${(frac * 100).toFixed(0)}%` +
      (totalKg !== null ? ` (${remainingT} / ${totalT} t)` : "");
  }

  // ── Time to next event ──
  const events = [];
  const burnoutList = s.stage_burnouts || [];
  burnoutList.forEach((tb, k) => {
    const label = k < burnoutList.length - 1 ? `Stage ${k + 1} separation` : "MECO";
    events.push([tb, label]);
  });
  if (s.t_apo !== null && s.t_apo !== undefined) events.push([s.t_apo, "Circularization burn"]);
  if (s.needs_hohmann) {
    if (s.t_park_end !== null) events.push([s.t_park_end, "Transfer injection burn"]);
    if (s.t_coast_start !== null) events.push([s.t_coast_start, "Circularization at target"]);
  }
  if (s.t_maneuver !== null && s.t_maneuver !== undefined) {
    events.push([s.t_maneuver, "Second maneuver burn"]);
  }
  if (s.t_reentry !== null && s.t_reentry !== undefined) {
    events.push([s.t_reentry, "Deorbit burn"]);
  }
  events.sort((a, b) => a[0] - b[0]);
  const next = events.find(([te]) => te > t);
  const nextEl = document.getElementById("hud-next-event");
  if (next) {
    const dt = next[0] - t;
    const label = dt >= 3600
      ? `${next[1]} in ${(dt / 3600).toFixed(1)} h`
      : dt >= 60
        ? `${next[1]} in ${(dt / 60).toFixed(1)} min`
        : `${next[1]} in ${dt.toFixed(0)} s`;
    nextEl.textContent = label;
  } else {
    nextEl.textContent = "—";
  }
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

  summaryRows.push(
    ["── OMS Δv budget ──",  ""],
    ["Budget",               s.oms_dv_budget.toFixed(0) + " m/s"],
    ["Spent (circ." + (s.needs_hohmann ? "+Hohmann" : "") + ")", s.oms_baseline_cost.toFixed(0) + " m/s"],
  );
  if (s.oms_over_budget) {
    summaryRows.push(["⚠ Over budget", "insufficient for baseline burns"]);
  }
  if (s.t_maneuver !== null && s.t_maneuver !== undefined) {
    summaryRows.push(
      ["── Second maneuver ──", ""],
      ["Δv requested",  s.maneuver_dv_requested.toFixed(0) + " m/s"],
      ["Δv applied",    s.maneuver_dv_applied.toFixed(0) + " m/s"],
    );
    if (s.maneuver_limited) {
      summaryRows.push(["⚠ Capped", "not enough OMS budget left"]);
    }
  }
  if (s.t_reentry !== null && s.t_reentry !== undefined) {
    summaryRows.push(
      ["── Reentry ──", ""],
      ["Deorbit Δv", s.reentry_dv_applied.toFixed(0) + " / " + s.reentry_dv_requested.toFixed(0) + " m/s"],
      ["Outcome", s.reentry_impacted ? "surface reached" : "atmospheric pass not completed"],
    );
    if (s.reentry_limited) summaryRows.push(["⚠ Deorbit capped", "not enough OMS budget left"]);
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