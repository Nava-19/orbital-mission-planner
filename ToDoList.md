# Mission Planner — TODO

## High Priority

### Animation
- [x] Fix animation playback — x1/x5/x20/x100 buttons should run continuously,
      not advance a single frame per click
- [x] Implement automatic frame calculation based on the total mission duration (t_full) to ensure smooth trajectories without compromising browser performance.

### Vehicle configuration UI
- [x] Add rocket presets (Falcon 9, Falcon Heavy, Ariane 5, Saturn V, custom)
- [x] Allow adding/removing stages dynamically (not just 2 fixed stages)
- [x] Add propellant type selector (RP-1/LOX, LH2/LOX, solid) with typical Isp values

### HUD
- [x] Fix the 3 new telemetry values not showing (Acceleration, Downrange, Vehicle mass) —
      turned out to already be fixed as a side effect of the automatic
      frame-calculation change (accel_g/downrange/mass are now included in
      the served JSON, which they weren't before that refactor). Confirmed
      working end-to-end.
- [x] Add mission phase label for Hohmann transfer ellipse coast
- [x] Add propellant remaining (actual out of total + %) for the active stage
- [x] Add time to next event (MECO, staging, circularization burn)

---

## Medium Priority

### Orbital mechanics
- [x] Second delta-V maneuver — raise/lower orbit after insertion
- [x] Reentry burn — deorbit and ballistic atmospheric trajectory
- [x] Trans-Lunar Injection (TLI) — burn to lunar transfer orbit.
      Implementation notes:
        - Prograde burn computed automatically (vis-viva) from the current
          orbit to a configurable target apoapsis (defaults to the Moon's
          mean distance, 384,400 km), same OMS Δv budget as everything else.
        - The Moon is now a real second gravitational body (not just a
          drawn target point): added to constants.py (mass, orbital
          radius, period) and orbital.py (get_moon_position — a
          simplified CIRCULAR orbit in the same 2D plane, own-calculation,
          no external library), with its gravity added into
          equations_of_motion/run_coast/run_reentry in solver.py. Verified
          the spacecraft trajectory genuinely deviates from a pure
          Keplerian ellipse because of it (~2,700km off target apoapsis
          in one test case) — this is a real (restricted) three-body
          effect, not just cosmetic.
        - Known simplification: circular, coplanar Moon orbit with an
          arbitrary phase at t=0 (no real calendar epoch/date is modeled
          anywhere in this simulator). The real Moon's orbit is elliptical
          (e≈0.055) and inclined ~5.14° to the ecliptic.
        - TODO (future precision upgrade): swap get_moon_position() for
          the Skyfield library (pip install skyfield), which gives the
          Moon's real position from JPL ephemeris data for an actual
          calendar date/time, instead of the simplified circular formula.
        - Lunar arrival/orbit insertion is still NOT simulated — the Moon's
          gravity affects the coast trajectory correctly, but there's no
          sphere-of-influence patching, no lunar orbit capture logic, and
          the mission just keeps coasting past/around the Moon on
          whatever perturbed path results.
- [ ] Real-time apoapsis/periapsis display in HUD (computed from current state)

### Visualization
- [ ] Improve Earth texture — use real satellite imagery mapped to sphere
- [ ] Add ground track — project trajectory onto Earth surface
- [ ] Add terminator line (day/night boundary) on Earth
- [ ] Show staging events as markers on trajectory

### Guidance
- [x] Implement PEG (Powered Explicit Guidance) — closed-loop guidance
      that adjusts pitch in real time to hit target orbit precisely,
      replacing the previous open-loop linear pitch profile.
      Implementation notes:
        - Simplified relative to textbook PEG: uses linear-ANGLE steering
          (theta(t) = theta0 + rate*t) solved by numerical shooting
          (least-squares) rather than the classical linear-TANGENT law
          with closed-form gravity-loss integrals — far more numerically
          robust across arbitrary, user-defined multi-stage vehicles.
        - Re-solves the steering law every ~20s of real flight from the
          actual (drag-affected) state — this is the closed-loop part.
        - Targets the parking-orbit apoapsis (r = r_park, radial
          velocity = 0) rather than an exact circular insertion, matching
          the existing architecture (a separate circularize() burn at
          apoapsis finishes the job) — this converges far more reliably
          than also requiring exact circular tangential velocity.
        - Known limitation: vehicles with a very short, extremely
          high-thrust first stage followed by a much weaker upper stage
          (e.g. the Ariane 5 preset: ~130s solid boosters then a ~972s,
          low-thrust sustainer) can still converge to a noticeably
          eccentric parking orbit — the 2-parameter steering family and
          shooting solver occasionally settle for a mediocre fit rather
          than an exact one for this kind of extreme stage asymmetry.
          It no longer crashes through the Earth (the original bug), but
          isn't as clean as Falcon 9 / Saturn V. Worth revisiting with a
          richer steering parametrization (e.g. quadratic-in-time, or
          true linear-tangent with closed-form gravity terms) if this
          matters for your use case.

---

## Low Priority / Future

### CFD Integration
- [ ] File upload for 3D rocket geometry (STL, OBJ, or STEP format)
- [ ] Mesh generation pipeline (gmsh or snappyHexMesh for OpenFOAM)
- [ ] SU2 (Stanford) integration — run Euler/RANS simulation on uploaded geometry
      to compute Cd, Cl, pressure distribution at given Mach/altitude conditions
- [ ] OpenFOAM integration as alternative CFD solver
- [ ] Extract aerodynamic coefficients (Cd, Cl, Cm) and feed them back into
      the flight simulator replacing the current fixed Cd=0.3
- [ ] Visualize CFD results (pressure/velocity field) in the web interface

### General
- [ ] Interactive orbital operations: once in the target orbit, hold indefinitely and
      allow the user to pause and choose a generic maneuver, TLI, or reentry. Each
      action must be preflighted against remaining OMS Δv and reserve enough Δv to
      return to Earth orbit and execute a safe reentry.
- [ ] Save/load mission configurations as JSON files
- [ ] Export mission report as PDF (trajectory plots + summary tables)
- [ ] Multi-mission comparison view
- [ ] Add atmospheric wind model affecting ascent trajectory

---

## Course-informed roadmap

Ideas sourced from this year's coursework, roughly in order of relevance /
effort to integrate with the existing architecture.

### From SE (Sistemas Espaciales) — highest relevance
- [ ] J2 perturbation on the coast phase (currently pure 2-body gravity) —
      would produce realistic nodal precession, visible directly in the
      ground track
- [ ] ADCS basics: satellite attitude/orientation once in orbit
      (magnetorquers, gravity-gradient stabilization) — currently the
      vehicle has no attitude state post-insertion, this is new territory
- [ ] Power subsystem budget: solar panel sizing vs. mission power
      consumption, shown as a small mission-summary panel
- [ ] Thermal subsystem (balance equation, passive/active control) —
      more ambitious, fits a "long-duration mission" mode
- [ ] Interplanetary patched-conic approximation — natural stepping stone
      toward the already-planned TLI

### From RL (Radiolocalització) — connects directly to today's ground track
- [ ] Ground-station visibility windows (AOS/LOS, elevation angle) using
      one or more fixed ground stations against the existing ground track
      — low effort given the ground track math already exists
- [ ] Communications link budget (Friis equation): EIRP, antenna gain,
      SNR, Doppler shift during a pass — new HUD panel active only during
      ground-station contact windows

### From SASP (Sistemas Aéreos Sin Piloto) — lower relevance, UAV-focused
- [ ] Export mission telemetry in MAVLink format (industry-standard) —
      pairs with the already-planned PDF mission report export
- [ ] IMU sensor noise model — only relevant if PEG guidance moves from
      perfect-state assumption to simulated sensor imperfection

### From RAIA — low relevance (AR/ML domain, not orbital)
- [ ] Geolocated interactive map — weak overlap with the existing ground
      track, not prioritized