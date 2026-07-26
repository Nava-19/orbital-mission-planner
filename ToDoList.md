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
- [ ] Add mission phase label for Hohmann transfer ellipse coast
- [ ] Add propellant remaining (actual out of total + %) for the active stage
- [ ] Add time to next event (MECO, staging, circularization burn)

---

## Medium Priority

### Orbital mechanics
- [ ] Second delta-V maneuver — raise/lower orbit after insertion
- [ ] Reentry burn — deorbit and reentry trajectory
- [ ] Trans-Lunar Injection (TLI) — burn to lunar transfer orbit
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
- [ ] Save/load mission configurations as JSON files
- [ ] Export mission report as PDF (trajectory plots + summary tables)
- [ ] Multi-mission comparison view
- [ ] Add atmospheric wind model affecting ascent trajectory