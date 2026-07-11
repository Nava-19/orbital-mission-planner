# Mission Planner — TODO

## High Priority

### Animation
- [x] Fix animation playback — x1/x5/x20/x100 buttons should run continuously,
      not advance a single frame per click
- [ ] Implement automatic frame calculation based on the total mission duration (t_full) to ensure smooth trajectories without compromising browser performance.

### Vehicle configuration UI
- [ ] Add rocket presets (Falcon 9, Falcon Heavy, Ariane 5, Saturn V, custom)
- [ ] Allow adding/removing stages dynamically (not just 2 fixed stages)
- [ ] Add propellant type selector (RP-1/LOX, LH2/LOX, solid) with typical Isp values

### HUD
- [ ] Fix the 3 new telemetry values not showing (Acceleration, Downrange, Vehicle mass)
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
- [ ] Implement PEG (Powered Explicit Guidance) — closed-loop guidance
      that adjusts pitch in real time to hit target orbit precisely,
      replacing the current open-loop linear pitch profile

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