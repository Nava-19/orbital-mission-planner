# Technical Reference — Orbital Mission Planner

> **Version 1.0 — September 2026**
>
> This document collects, in one place, every equation, physical model,
> reference frame, unit convention, integration method, and deliberate
> simplification used by the simulator. Its purpose is to make the project
> auditable as an engineering artefact — not just "code that runs" — and to
> provide a single source of truth for anyone reviewing, extending, or
> validating the simulation.

---

## Table of contents

1. [Coordinate system and reference frame](#1-coordinate-system-and-reference-frame)
2. [Units and constants](#2-units-and-constants)
3. [Gravitational model](#3-gravitational-model)
4. [Atmospheric model](#4-atmospheric-model)
5. [Aerodynamic drag](#5-aerodynamic-drag)
6. [Vehicle model and propulsion](#6-vehicle-model-and-propulsion)
7. [Equations of motion](#7-equations-of-motion)
8. [Numerical integration](#8-numerical-integration)
9. [Ascent guidance — Powered Explicit Guidance (PEG)](#9-ascent-guidance--powered-explicit-guidance-peg)
10. [Orbital elements computation](#10-orbital-elements-computation)
11. [Hohmann transfer](#11-hohmann-transfer)
12. [Circularization burn](#12-circularization-burn)
13. [Lunar model and three-body dynamics](#13-lunar-model-and-three-body-dynamics)
14. [Reentry model](#14-reentry-model)
15. [OMS Δv budget model](#15-oms-v-budget-model)
16. [Validation summary](#16-validation-summary)
17. [Known limitations and deliberate simplifications](#17-known-limitations-and-deliberate-simplifications)
18. [References](#18-references)

---

## 1. Coordinate system and reference frame

The entire simulation operates in a **two-dimensional, Earth-Centered
Inertial (ECI)** plane.

| Property | Value |
|---|---|
| Origin | Centre of the Earth |
| Axes | Fixed inertial frame; +x initially aligned with the launch site on the equator |
| Dimensions | 2D (x, y). No orbital inclination or out-of-plane dynamics |
| State vector | **[x, y, vx, vy]** — position and velocity in metres and m/s |

**Launch initial conditions** (from `solver.py`):

$$\mathbf{r}_0 = \begin{bmatrix} R_E \\ 0 \end{bmatrix}, \quad \mathbf{v}_0 = \begin{bmatrix} 0 \\ v_{\mathrm{rot}} \end{bmatrix}$$

where $v_{\mathrm{rot}} = \omega_E \cdot R_E \approx 465 \;\mathrm{m/s}$ is Earth's equatorial surface rotation velocity, giving the vehicle the correct initial inertial velocity at the equator.

**Local frame decomposition** used during flight:

$$\hat{r} = \frac{\mathbf{r}}{|\mathbf{r}|}, \quad \hat{t} = \frac{1}{|\mathbf{r}|}\begin{bmatrix} -y \\ x \end{bmatrix}$$

where $\hat{r}$ is radial (outward) and $\hat{t}$ is tangential (prograde).

---

## 2. Units and constants

All computation uses **SI base units** (metres, kilograms, seconds). Angular
quantities are in radians unless explicitly noted as degrees in output.

| Symbol | Value | Description | Source |
|---|---|---|---|
| $M_E$     | 5.9722 × 10²⁴ kg       | Earth's nominal mass (informational) | IAU |
| $G$       | 6.67430 × 10⁻¹¹ N·m²/kg² | Universal gravitational constant | CODATA |
| $R_E$     | 6.371 × 10⁶ m          | Earth's mean radius | WGS-84 (rounded) |
| $g_0$     | 9.80665 m/s²            | Standard gravity (ISA defined) | ISO 2533 |
| $\mu$     | 3.986004418 × 10¹⁴ m³/s² | Earth's standard gravitational parameter (single source of truth) | EGM-96 |
| $\omega_E$| 7.2921150 × 10⁻⁵ rad/s | Earth's angular velocity | IERS |
| $v_{\mathrm{esc}}$ | 11 186 m/s     | Earth's escape velocity | Derived |
| $P_{sl}$  | 101 325 Pa              | ISA sea-level pressure | ISO 2533 |
| $T_{sl}$  | 288.15 K                | ISA sea-level temperature | ISO 2533 |
| $L_{mb}$  | 0.0065 K/m              | Tropospheric lapse rate | ISO 2533 |
| $R_{air}$ | 287.05 J/(kg·K)         | Specific gas constant (dry air) | — |
| $H_{tr}$  | 11 000 m                | Tropopause altitude | ISO 2533 |
| $\mu_{Moon}$ | 4.902800066 × 10¹² m³/s² | Moon's standard gravitational parameter (fixed reference) | Reference constant |
| $r_{Moon}$| 384 400 × 10³ m         | Moon's mean orbital radius | IAU |
| $T_{Moon}$| 27.321661 × 86400 s     | Moon's sidereal orbital period | IAU |

---

## 3. Gravitational model

### 3.1 Earth gravity

A **spherically-symmetric, point-mass** model (monopole). No $J_2$ or
higher-order gravitational harmonics.

The gravitational acceleration is defined directly from Earth's standard
gravitational parameter $\mu$:

$$g(h) = \frac{\mu}{(R_E + h)^2}$$

In vector form (as applied to the state vector):

$$\mathbf{a}_g = -g(h) \cdot \hat{r} = -\frac{\mu}{r^2} \hat{r}$$

where $r = |\mathbf{r}| = \sqrt{x^2 + y^2}$ and $h = r - R_E$.

> **Note on unified gravitational parameter:** Earth's gravitational acceleration
> in the numerical integrator (`environment.get_gravity`) and all analytical orbital
> calculations (`orbital.py`, Hohmann transfers, circularization, Keplerian elements,
> and PEG guidance) use the exact same single source of truth:
> $\mu = 3.986004418 \times 10^{14} \;\mathrm{m}^3/\mathrm{s}^2$ (EGM-96).
> The previous dual definition where dynamics used an indirect $G \cdot M_E$
> has been eliminated to ensure strict physical consistency between numerical
> propagation and analytical orbit models.

### 3.2 Moon gravity

The Moon's gravitational acceleration on the spacecraft is included in every
phase of the simulation (ascent, coast, and reentry), making this a
**restricted three-body** simulation (Earth + Moon + massless spacecraft):

$$\mathbf{a}_{Moon} = \frac{\mu_{Moon}}{|\mathbf{r}_{Moon} - \mathbf{r}|^3}(\mathbf{r}_{Moon} - \mathbf{r})$$

A safety guard sets acceleration to zero if the spacecraft-Moon distance falls
below 1.0 m (degenerate case).

> **Note on lunar gravitational parameter and model simplifications:**
> The lunar gravitational parameter is defined directly as a fixed reference
> constant: $\mu_{Moon} = 4.902800066 \times 10^{12} \;\mathrm{m}^3/\mathrm{s}^2$,
> rather than being reconstructed from $G \cdot M_{Moon}$.
> The lunar model in the simulator remains an idealized engineering approximation:
> - **Point-mass gravity:** Only the direct Newtonian acceleration toward the Moon
>   is computed; the indirect non-inertial acceleration of the Earth is omitted.
> - **Circular analytical orbit:** The Moon moves on an idealized circular,
>   coplanar orbit ($r_{Moon} = 384\,400 \;\mathrm{km}$, $i=0^\circ$, $e=0$).
> - **No real ephemeris:** Positions are evaluated analytically from elapsed
>   time and phase offset, without high-fidelity ephemeris kernels (e.g. JPL DE series).
>
> Moon gravity is negligible during the ascent phase (drowned out by
> Earth's gravity by several orders of magnitude), but is the dominant
> gravitational body during trans-lunar coast and lunar orbit phases. It is
> included everywhere for physical consistency.

---

## 4. Atmospheric model

A two-regime model providing continuous air density from sea level to 1 000 km.

### 4.1 Troposphere and lower stratosphere (0–20 km)

Physically derived from the **International Standard Atmosphere (ISA)** using
the polytropic (temperature lapse rate) model:

**Troposphere** ($h < 11\,000$ m):

$$T(h) = T_{sl} - L_{mb} \cdot h$$

$$P(h) = P_{sl} \left(\frac{T(h)}{T_{sl}}\right)^{5.2561}$$

$$\rho(h) = \frac{P(h)}{R_{air} \cdot T(h)}$$

The exponent 5.2561 equals $g_0 / (L_{mb} \cdot R_{air})$, derived from the
hydrostatic equation.

**Lower stratosphere** ($11\,000 \leq h < 20\,000$ m):

Temperature is constant at the tropopause value. Pressure decays exponentially:

$$P(h) = P_{tr} \cdot \exp\left(-1.577 \times 10^{-4} (h - H_{tr})\right)$$

$$\rho(h) = \frac{P(h)}{R_{air} \cdot T_{tr}}$$

### 4.2 Upper atmosphere (20–1 000 km)

Based on the **standard reference exponential atmosphere table** from Vallado
(*Fundamentals of Astrodynamics and Applications*), which provides reference
density values at 27 altitude nodes from 25 km to 1 000 km.

Instead of using a piecewise-exponential with each row's scale height (which
produces discontinuous jumps in the local density gradient at row boundaries),
the implementation fits a **PCHIP (Piecewise Cubic Hermite Interpolating
Polynomial)** through $\ln(\rho)$ vs. altitude:

$$\rho(h) = \exp\!\bigl[\mathrm{PCHIP}\bigl(\{h_i\},\,\{\ln \rho_i\}\bigr)(h)\bigr]$$

This:
- Passes **exactly** through every published reference node (zero error at the
  tabulated altitudes).
- Keeps the density gradient ($d\ln\rho / dh$) **continuous** between nodes —
  no artificial kinks.
- Is **monotonic** by construction (PCHIP property), matching the physical
  reality that density decreases with altitude.

Above 1 000 km, altitude is clamped to the last table entry (3.019 × 10⁻¹⁵ kg/m³).

---

## 5. Aerodynamic drag

$$\mathbf{a}_{\mathrm{drag}} = -\frac{1}{2} \frac{\rho \cdot |\mathbf{v}_{rel}|^2 \cdot C_d \cdot A}{m} \cdot \hat{v}_{rel}$$

where:

| Symbol | Description |
|---|---|
| $\rho$ | Air density at current altitude (§4) |
| $\mathbf{v}_{rel}$ | Velocity relative to the co-rotating atmosphere |
| $C_d$ | Drag coefficient (user-supplied, per stage) |
| $A$ | Cross-sectional reference area (user-supplied, per stage, m²) |
| $m$ | Instantaneous vehicle mass |

**Relative velocity** accounts for Earth's atmosphere co-rotating with the planet:

$$\mathbf{v}_{atm} = \omega_E \cdot r \cdot \hat{t}$$

$$\mathbf{v}_{rel} = \mathbf{v} - \mathbf{v}_{atm}$$

This is important during the early ascent phase when the vehicle's velocity is
comparable to the surface rotation velocity.

> **Limitation:** $C_d$ is constant for each stage (no Mach-dependent variation,
> no transonic drag rise). A planned CFD companion project would generate
> altitude/Mach-dependent coefficients from actual vehicle geometries.

---

## 6. Vehicle model and propulsion

### 6.1 Stage model

Each stage is defined by six parameters:

| Parameter | Symbol | Unit | Description |
|---|---|---|---|
| Dry mass | $m_{dry}$ | kg | Structural mass excluding propellant |
| Propellant mass | $m_{prop}$ | kg | Total propellant mass |
| Thrust | $T$ | N | Maximum thrust (constant during burn) |
| Specific impulse | $I_{sp}$ | s | Engine efficiency |
| Drag coefficient | $C_d$ | — | Aerodynamic drag coefficient |
| Reference area | $A$ | m² | Cross-sectional area for drag |

### 6.2 Mass flow rate

Derived from the **rocket equation** (Tsiolkovsky):

$$\dot{m} = \frac{T}{I_{sp} \cdot g_0}$$

### 6.3 Stage burnout time

$$t_{burn} = \frac{m_{prop}}{\dot{m}}$$

### 6.4 Instantaneous mass

During each stage's burn ($t_{ign} \leq t < t_{cut}$):

$$m(t) = m_{payload} + \sum_{i \;\text{attached}} m_i(t)$$

where for the currently burning stage:

$$m_i(t) = m_{dry,i} + m_{prop,i} - \dot{m}_i (t - t_{ign,i})$$

Jettisoned stages ($t \geq t_{cut}$) contribute zero mass. Stages not yet
ignited ($t < t_{ign}$) contribute their full mass.

### 6.5 Thrust vector

$$\mathbf{a}_{thrust} = \frac{T}{m(t)} \left[\cos(\theta) \cdot \hat{r} + \sin(\theta) \cdot \hat{t}\right]$$

where $\theta$ is the pitch angle from the local vertical ($\theta = 0$:
vertical/radial, $\theta = \pi/2$: fully tangential/prograde). The pitch angle
is determined by the guidance system (§9).

---

## 7. Equations of motion

The full state derivative during powered ascent (`solver.equations_of_motion`):

$$\frac{d}{dt}\begin{bmatrix} x \\ y \\ v_x \\ v_y \end{bmatrix} = \begin{bmatrix} v_x \\ v_y \\ a_x \\ a_y \end{bmatrix}$$

where the total acceleration is:

$$\mathbf{a} = \mathbf{a}_{gravity} + \mathbf{a}_{thrust} + \mathbf{a}_{drag} + \mathbf{a}_{Moon}$$

Expanded:
- $\mathbf{a}_{gravity} = -\frac{\mu}{r^2}\hat{r}$ — Earth's point-mass gravity (§3.1)
- $\mathbf{a}_{thrust} = \frac{T}{m}[\cos\theta\;\hat{r} + \sin\theta\;\hat{t}]$ — rocket thrust (§6.5)
- $\mathbf{a}_{drag} = -\frac{1}{2}\frac{\rho \, v_{rel}^2 \, C_d \, A}{m}\hat{v}_{rel}$ — atmospheric drag (§5)
- $\mathbf{a}_{Moon}$ — Moon's gravitational perturbation (§3.2)

During **unpowered coast** (`solver.run_coast`):
$$\mathbf{a} = \mathbf{a}_{gravity} + \mathbf{a}_{Moon}$$

During **ballistic reentry** (`solver.run_reentry`):
$$\mathbf{a} = \mathbf{a}_{gravity} + \mathbf{a}_{drag} + \mathbf{a}_{Moon}$$

with $C_d = 1.2$ and $A$ = 25% of the last stage's area (simplified ballistic
body), plus a terminal surface-impact event ($r = R_E$, detected with a root-
finding event function).

---

## 8. Numerical integration

### 8.1 Primary integrator (trajectory propagation)

**SciPy's `solve_ivp`** with the **RK45 method** (Dormand-Prince embedded
4(5)th-order Runge-Kutta with adaptive step size control):

| Parameter | Value | Context |
|---|---|---|
| Method | `RK45` | Adaptive 4th/5th-order pair |
| `max_step` | 0.5 s | Powered ascent (`run_simulation`) |
| `max_step` | 10.0 s | Unpowered coast (`run_coast`) |
| `max_step` | 60.0 s | Ballistic reentry (`run_reentry`) |
| Tolerances | SciPy defaults: `rtol=1e-3`, `atol=1e-6` | — |

The `max_step` ceiling controls the coarsest the integrator is allowed to be;
RK45's own adaptive error control typically uses much smaller steps when the
dynamics are stiff (e.g., during the drag-dominated final descent in reentry).

**Staging events** are handled by breaking the integration at each stage cutoff
time and restarting with the updated vehicle mass.

**PEG replanning** (§9) restarts the integrator every 20 s of flight time to
update the guidance law from the actual state.

### 8.2 PEG internal predictor

A **fixed-step, 4th-order Runge-Kutta (RK4)** propagator with 40 steps per
prediction (in `vehicle.py`), used exclusively inside the PEG steering law
solver as a fast, lightweight forward model:

- **Vacuum, point-mass gravity** — no drag, no Moon
- Equations in radial/tangential polar coordinates:

$$\dot{r} = v_r$$
$$\dot{v}_r = -g(r) + \frac{v_t^2}{r} + \frac{T}{m}\cos\theta$$
$$\dot{v}_t = -\frac{v_r v_t}{r} + \frac{T}{m}\sin\theta$$
$$\dot{m} = -\dot{m}_{stage}$$

This is called many times per replan (the least-squares solver evaluates it
repeatedly for Jacobian estimation), so computational cost matters. The fixed-
step RK4 avoids `solve_ivp`'s per-call overhead for this tiny 4-variable ODE.

> **Key distinction:** This simplified propagator is used ONLY to solve the
> guidance law (what pitch program to fly). The actual trajectory shown to the
> user is always integrated with the full physics model (§7) including drag,
> Moon gravity, and adaptive step size.

### 8.3 Measured integration accuracy

The test suite (`test_solver.py`) verifies that unpowered coasts conserve:
- **Specific orbital energy**: to within $10^{-4}$ relative error over 3 600 s
- **Specific angular momentum**: to within $10^{-4}$ relative error over 5 000 s

These are properties of the exact solution (Keplerian orbit), so any deviation
measures pure numerical integration error.

---

## 9. Ascent guidance — Powered Explicit Guidance (PEG)

### 9.1 Overview

PEG is a **closed-loop** ascent guidance algorithm: it repeatedly re-derives
the optimal steering from the spacecraft's actual (drag-affected, staging-
affected) state, rather than following a fixed, pre-programmed pitch schedule.

The implementation in this simulator follows PEG's essential architecture —
**predict → solve → replan → cut off on target** — but uses a different
mathematical formulation than the classical Saturn V / Space Shuttle PEG:

| Aspect | Classical PEG | This implementation |
|---|---|---|
| Steering law | Linear-tangent: $\tan\theta = A + Bt$ | Linear-angle: $\theta = \theta_0 + \dot{\theta} \cdot \tau$ |
| Gravity losses | Closed-form integrals | Numerical RK4 propagation |
| Solution method | Analytical iteration | Numerical shooting (least-squares) |
| Robustness | Tuned for specific vehicle classes | Converges for arbitrary multi-stage vehicles |

### 9.2 Flight phases

**Phase 1 — Vertical ascent** ($t < t_{vertical}$):

$$\theta(t) = 0 \quad (\text{thrust purely radial, away from Earth})$$

Duration is user-configurable (default: 20 s, clamped to [5, 30] s), modelling
the initial tower/pad clearance.

**Phase 2 — Open-loop kick** ($t_{vertical} \leq t < t_{PEG}$):

$$\theta(t) = \theta_{kick} \cdot \frac{t - t_{vertical}}{t_{PEG} - t_{vertical}}$$

A linear pitch ramp from vertical to $\theta_{kick} = 20°$, mimicking the
real-vehicle practice of flying an open-loop "tilt program" through the dense
atmosphere (max dynamic pressure region) before engaging closed-loop guidance.

$t_{PEG}$ is set to:

$$t_{PEG} = \min\bigl(t_{vertical} + 100,\; t_{vertical} + 0.5\cdot(t_{cut,1} - t_{vertical})\bigr)$$

This guarantees PEG gets at least the second half of the first stage's burn,
even for vehicles with very short first stages (e.g. solid boosters).

**Phase 3 — Closed-loop PEG** ($t \geq t_{PEG}$):

$$\theta(t) = \theta_0 + \dot{\theta} \cdot (t - t_{ref})$$

where $(\theta_0, \dot{\theta})$ are re-solved every 20 s (the **replan interval**).

### 9.3 Steering law solver

At each replan, the simulator finds $(\theta_0, \dot{\theta})$ that steer the
vehicle from its current real state to the parking-orbit target by solving:

$$\min_{\theta_0, \dot{\theta}} \left\| \begin{bmatrix} (r_f - r_{park}) / r_{park} \\ v_{r,f} / v_{circ,park} \end{bmatrix} \right\|^2$$

where $(r_f, v_{r,f})$ are predicted using the fast RK4 propagator (§8.2)
over the remaining propellant burn time $t_{go}$.

**Target conditions** (2 constraints, 2 free parameters — well-posed):
1. $r_f = R_E + h_{park}$ — altitude matches parking orbit
2. $v_{r,f} = 0$ — zero radial velocity (apoapsis)

> **Design decision:** The tangential velocity is NOT constrained. PEG
> targets the parking-orbit **apoapsis** rather than exact circular
> insertion. A separate circularization burn (§12) at apoapsis completes the
> orbit. This 2-constraint formulation converges far more reliably than a
> 3-constraint (include tangential velocity) system, which required more
> energy/time than some vehicles have available.

**Solver:** `scipy.optimize.least_squares` with bounds
$\theta_0 \in [0, \pi/2]$, $\dot{\theta} \in [-0.05, 0.05]$ rad/s.

**Convergence strategy:**
- **Warm start:** re-uses the previous solution as the initial guess (single
  solve, typically converges immediately).
- **Multi-start fallback:** on the first replan (no warm start available),
  tries initial guesses at $\theta_0 \in \{10°, 30°, 50°, 70°\}$ and keeps
  the best solution.

### 9.4 Engine cutoff

PEG commands MECO (Main Engine Cutoff) when the **real** trajectory satisfies:

$$r \geq r_{park} \quad \text{AND} \quad |v_r| < 15 \;\text{m/s}$$

This means cutoff happens at the actual orbital apex, regardless of remaining
propellant. An overpowered vehicle (e.g. Saturn V aimed at a modest LEO)
will cut off with propellant to spare.

---

## 10. Orbital elements computation

Computed from the 2D Cartesian state vector ($x, y, v_x, v_y$) using standard
formulas (`orbital.compute_orbital_elements`):

**Specific orbital energy:**
$$\varepsilon = \frac{v^2}{2} - \frac{\mu}{r}$$

**Semi-major axis** (from the vis-viva relation):
$$a = -\frac{\mu}{2\varepsilon}$$

**Specific angular momentum** (scalar in 2D):
$$h = x \cdot v_y - y \cdot v_x$$

**Eccentricity:**
$$e = \sqrt{\max\!\left(0,\; 1 + \frac{2\varepsilon h^2}{\mu^2}\right)}$$

**Apoapsis and periapsis radii:**
$$r_a = a(1+e), \quad r_p = a(1-e)$$

**Orbital period:**
$$T = 2\pi\sqrt{\frac{a^3}{\mu}}$$

**Velocities at apsides** (from angular momentum conservation):
$$v_a = \frac{h}{r_a}, \quad v_p = \frac{h}{r_p}$$

**Eccentricity vector** (points toward periapsis):
$$\mathbf{e} = \frac{1}{\mu}\left[\left(v^2 - \frac{\mu}{r}\right)\mathbf{r} - (\mathbf{r} \cdot \mathbf{v})\mathbf{v}\right]$$

**Argument of periapsis:**
$$\omega = \arctan\!\left(\frac{e_y}{e_x}\right)$$

**True anomaly** ($\nu$): angle from eccentricity vector to position vector,
computed via $\cos\nu$ with the sign disambiguated by the 2D cross product
$\mathbf{e} \times \mathbf{r}$.

**Orbit propagation** (for display): the polar orbit equation

$$r(\nu) = \frac{h^2/\mu}{1 + e\cos\nu}$$

is evaluated at $N$ uniformly spaced true anomaly values, converted from
perifocal to inertial coordinates via rotation by $\omega$:

$$\begin{bmatrix} x_{inertial} \\ y_{inertial}\end{bmatrix} = \begin{bmatrix} \cos\omega & -\sin\omega \\ \sin\omega & \cos\omega \end{bmatrix} \begin{bmatrix} r\cos\nu \\ r\sin\nu \end{bmatrix}$$

---

## 11. Hohmann transfer

Classical two-impulse coplanar transfer between circular orbits
(`orbital.hohmann_transfer`).

Given a parking orbit at altitude $h_1$ and a target orbit at altitude $h_2$:

$$r_1 = R_E + h_1, \quad r_2 = R_E + h_2$$

**Circular velocities:**
$$v_1 = \sqrt{\frac{\mu}{r_1}}, \quad v_2 = \sqrt{\frac{\mu}{r_2}}$$

**Transfer ellipse parameters:**
$$a_{tr} = \frac{r_1 + r_2}{2}, \quad e_{tr} = \frac{r_2 - r_1}{r_2 + r_1}$$

**Velocities on the transfer ellipse** (from vis-viva):
$$v_{peri} = \sqrt{\mu\left(\frac{2}{r_1} - \frac{1}{a_{tr}}\right)}, \quad v_{apo} = \sqrt{\mu\left(\frac{2}{r_2} - \frac{1}{a_{tr}}\right)}$$

**Delta-V burns:**
$$\Delta v_1 = v_{peri} - v_1 \quad \text{(prograde, at perigee)}$$
$$\Delta v_2 = v_2 - v_{apo} \quad \text{(prograde, at apogee)}$$

**Transfer coast time** (half the transfer ellipse period):
$$T_{transfer} = \pi\sqrt{\frac{a_{tr}^3}{\mu}}$$

**Validation:** LEO (300 km) → GEO (35 786 km) total Δv = ≈ 3 935 m/s,
matching published textbook values (Curtis, *Orbital Mechanics for Engineering
Students*) to within 2%.

---

## 12. Circularization burn

After MECO, the vehicle coasts to the apoapsis of its ascent ellipse and
applies a prograde burn to raise periapsis to match apoapsis
(`orbital.circularize`).

**Coast time to apoapsis:** computed via Kepler's equation — current true
anomaly → eccentric anomaly → mean anomaly → time difference:

$$E = 2\arctan\!\left(\sqrt{\frac{1-e}{1+e}} \tan\frac{\nu}{2}\right)$$
$$M = E - e\sin E$$

Coast time: $\Delta t = (M_{apo} - M_{now}) / n$, where $n = 2\pi/T$ is the
mean motion and $M_{apo} = \pi$.

**Apoapsis snap:** If the vehicle is already within ~45° of true anomaly from
the apoapsis (i.e. PEG delivered it very close to the target), the coast time
is snapped to zero and the circularization burn uses the real current
position/velocity rather than the theoretical exact-apoapsis point.

**Circularization Δv:**

$$\Delta v_{circ} = v_{circ} - v_a = \sqrt{\frac{\mu}{r_a}} - \frac{h}{r_a}$$

---

## 13. Lunar model and three-body dynamics

### 13.1 Moon orbit model

The Moon is modelled as a **circular, coplanar orbit** in the same 2D plane as
the rest of the simulation:

$$x_{Moon}(t) = r_{Moon}\cos\theta(t), \quad y_{Moon}(t) = r_{Moon}\sin\theta(t)$$

$$\theta(t) = \frac{2\pi t}{T_{Moon}} + \phi_0$$

where $\phi_0$ is a phase offset that is computed per-mission for TLI scenarios
to ensure the Moon is at the transfer ellipse's apoapsis when the spacecraft
arrives.

The Moon's velocity follows from differentiating the position:

$$v_{Moon} = \frac{2\pi r_{Moon}}{T_{Moon}} \approx 1\,023 \;\mathrm{m/s}$$

### 13.2 Trans-Lunar Injection (TLI)

A prograde burn from the parking orbit, sized by the vis-viva equation to
achieve a transfer apoapsis at the Moon's mean orbital radius:

$$a_{transfer} = \frac{r_{current} + r_{target}}{2}$$

$$v_{transfer} = \sqrt{\mu\left(\frac{2}{r_{current}} - \frac{1}{a_{transfer}}\right)}$$

$$\Delta v_{TLI} = v_{transfer} - v_{circ}$$

### 13.3 Lunar Orbit Insertion (LOI)

A **vector-based** capture burn — not just a magnitude scaling. The burn
redirects the spacecraft's velocity (relative to the Moon) to a purely
tangential direction at the closest-approach distance:

$$v_{circ,Moon} = \sqrt{\frac{\mu_{Moon}}{r_{rel}}}$$

The burn vector is computed to match the incoming angular momentum sign
(prograde or retrograde relative to the Moon), ensuring a physically consistent
capture direction.

### 13.4 Trans-Earth Injection (TEI)

The departure burn is found by a **two-parameter numerical search** (grid scan
+ `least_squares` refinement) over:
1. Departure timing (within one lunar orbit after the configured stay)
2. Burn magnitude (1× to 3× the Moon's escape velocity)

The objective targets a **shallow atmospheric entry angle** (≈ -6° at 122 km
altitude, matching the Apollo entry corridor) rather than just any periapsis
depth. Each candidate is evaluated with a **real coast** (full Earth+Moon
gravity), not a simplified analytic estimate — because the departure point is
deep inside the Moon's sphere of influence where the Moon's gravity dominates.

### 13.5 Simplifications in the lunar model

| Aspect | This model | Reality |
|---|---|---|
| Moon orbit shape | Circular | Elliptical ($e \approx 0.055$) |
| Moon orbit plane | Coplanar with equator | Inclined ~5.14° to ecliptic |
| Moon position | Analytical formula | Real ephemeris (JPL/Skyfield) |
| Epoch | Arbitrary $t=0$, synced per mission | Calendar date/time |
| Three-body dynamics | Restricted (spacecraft massless) | Full N-body |

---

## 14. Reentry model

### 14.1 Deorbit sequence

The deorbit sequence implements a physically realistic multi-burn approach:

1. **Descent burn** (if starting above ~1.5× parking orbit radius): a
   retrograde burn to drop periapsis to parking-orbit altitude, using vis-viva
   to compute the required speed reduction.

2. **Circularization** at parking altitude: a second retrograde burn to reduce
   speed from the descent ellipse's periapsis speed to local circular speed.
   The velocity is snapped to a purely tangential direction (eliminating
   residual radial velocity from finite integration timesteps).

3. **Deorbit burn**: targets a periapsis at Earth's surface ($r_p = R_E$):

$$v_{deorbit} = \sqrt{\mu\left(\frac{2}{r} - \frac{1}{a_{deorbit}}\right)}, \quad a_{deorbit} = \frac{r + R_E}{2}$$

$$\Delta v_{deorbit} = v_{current} - v_{deorbit}$$

### 14.2 Ballistic descent

After the deorbit burn, the trajectory is propagated with:
- Earth's gravity (point-mass)
- Atmospheric drag (same model as ascent, co-rotating atmosphere)
- Moon's gravity
- **No thrust, no lift**

This is a **point-mass ballistic reentry**: no aerodynamic lift, heating model,
or parachute deployment. The drag coefficient is set to $C_d = 1.2$ with a
reference area of 25% of the last stage's area.

**Surface impact** is detected by a root-finding event function:

$$f(t) = \sqrt{x^2 + y^2} - R_E = 0, \quad \frac{df}{dt} < 0 \;\text{(descending)}$$

---

## 15. OMS Δv budget model

All post-MECO burns draw from a single, user-configurable **OMS (Orbital
Maneuvering System) Δv budget** (default: 2 500 m/s). This models the
payload/upper stage's total maneuvering capacity, independent of the launch
vehicle.

Burns are charged in order:
1. Circularization
2. Hohmann transfer injection (Δv₁)
3. Hohmann circularization at target (Δv₂)
4. Optional second maneuver
5. TLI burn
6. LOI burn
7. TEI burn
8. Descent to parking orbit (reentry)
9. Circularization at parking orbit (reentry)
10. Final deorbit burn

Each burn is **clipped** to whatever budget remains. If a burn would exceed the
remaining budget, only the affordable fraction is applied. The actual Δv spent
(vs. requested) is reported honestly in the mission summary.

---

## 16. Validation summary

| Quantity | Simulator result | Reference value | Source | Tolerance |
|---|---|---|---|---|
| Atmospheric density (every Vallado node, 20–1 000 km) | Exact match | Vallado table values | Vallado, *Fund. of Astrodyn.* | < 0.1% |
| Sea-level density | 1.225 kg/m³ | 1.225 kg/m³ | ISA standard | < 0.1% |
| Gravity at sea level | ≈ 9.822 m/s² | 9.80665 m/s² (defined) | ISO 2533 | < 0.2% (expected: $GM/R²$ ≠ $g_0$) |
| Circular orbit eccentricity | 0.0 ± 10⁻⁹ | 0.0 | Kepler | Machine precision |
| Circular orbit period | Matches $2\pi\sqrt{a^3/\mu}$ | Kepler's 3rd law | — | < 10⁻⁶ |
| Hohmann LEO→GEO total Δv | ≈ 3 935 m/s | 3 935 m/s | Curtis textbook | < 2% |
| Specific orbital energy conservation (coast) | Drift < 10⁻⁴ | Zero (exact solution) | — | 10⁻⁴ rel |
| Specific angular momentum conservation (coast) | Drift < 10⁻⁴ | Zero (exact solution) | — | 10⁻⁴ rel |
| Falcon 9 max dynamic pressure | ≈ 33 kPa | 30–40 kPa | Public flight data | Within range |
| TLI Δv (LEO → Moon distance) | ≈ 3.08 km/s | 3.1–3.2 km/s | Historical TLI burns | < 5% |
| LOI Δv | 0.7–1.0 km/s | ≈ 1.0 km/s (Apollo) | Apollo mission reports | Consistent |
| Reentry flight path angle at 122 km | ≈ -6° to -8° | ≈ -6.5° (Apollo) | Apollo mission reports | Consistent |
| Reentry surface impact detection | Triggers within 1 km of $R_E$ | $r = R_E$ | — | 1 km |

All automated tests (27 tests in `tests/`) run in CI on every push via GitHub
Actions.

---

## 17. Known limitations and deliberate simplifications

### Physics model

| Limitation | Impact | Rationale |
|---|---|---|
| **2D single-plane dynamics** | No orbital inclination, no out-of-plane maneuvers, no launch azimuth effects | Keeps the physics tractable for a single-developer educational project; the core orbital mechanics (vis-viva, Hohmann, PEG targeting) work identically in the orbital plane |
| **No J₂ perturbation** | No nodal precession, no orbit precession effects | Would add realism to long-duration coasts but is not needed for the single-orbit-scale scenarios currently simulated |
| **No solar radiation pressure** | Negligible for LEO/GEO time scales simulated | Relevant only for high-area/mass satellites over long durations |
| **No third-body perturbations beyond the Moon** | Sun's gravity ignored | Negligible for Earth-Moon system at the precision level of this simulator |
| **Constant thrust per stage** | No throttle profiles, no engine-out scenarios | Simplifies staging and mass flow; real engines do throttle (e.g. Falcon 9 during max-Q) |
| **Impulsive post-MECO burns** | Hohmann, circularization, LOI, etc. are instantaneous Δv | Acceptable for orbit-scale maneuvers where burn duration ≪ orbital period |
| **Constant $C_d$ per stage** | No Mach-dependent drag, no transonic drag rise | User-supplied; the planned CFD companion project would generate realistic coefficients |
| **No atmospheric wind model** | No wind shear, jet stream, or gusts during ascent | Would add realism to the max-Q region but is secondary to getting the orbital mechanics right |
| **No Earth oblateness for geometry** | Earth is a perfect sphere for both gravity and radius | Consistent with the no-J₂ gravity model |

### Guidance model

| Limitation | Impact |
|---|---|
| Linear-angle steering (not linear-tangent) | More robust across arbitrary vehicles, but not the classical PEG formulation |
| Vehicles with extreme stage asymmetry (e.g. Ariane 5: short solid boosters + long weak upper stage) may converge to a slightly eccentric parking orbit | The 2-parameter shooting solver occasionally settles for a mediocre fit |
| PEG internal predictor ignores drag | Closed-loop replanning corrects this every 20 s from the real state |

### Lunar model

| Limitation | Impact |
|---|---|
| Circular, coplanar Moon orbit | Real Moon has $e \approx 0.055$ and $5.14°$ inclination |
| No real ephemeris / calendar epoch | Phase is synced per-mission, not to actual dates |
| Patched two-body for LOI/TEI sizing | Not a full CR3BP (circular restricted three-body problem) |

### Reentry model

| Limitation | Impact |
|---|---|
| Point-mass ballistic (no lift) | Cannot model lifting reentry (Shuttle, capsule with CG offset) |
| No thermal model | Cannot predict heating or thermal protection requirements |
| No parachute / recovery model | Descent ends at surface impact |

---

## 18. References

1. **Vallado, D. A.** *Fundamentals of Astrodynamics and Applications*, 4th ed.
   Microcosm Press. — Exponential atmosphere reference table, orbital elements
   algorithms.

2. **Curtis, H. D.** *Orbital Mechanics for Engineering Students*, 4th ed.
   Butterworth-Heinemann. — Hohmann transfer Δv reference values, classical
   orbital elements.

3. **Bate, R. R., Mueller, D. D., White, J. E.** *Fundamentals of
   Astrodynamics*. Dover. — Two-body problem, Kepler's equation.

4. **Brand, T. J., Brown, R. T., et al.** "The Iterative Guidance Mode Used in
   the Saturn V / Space Shuttle Programs" — Original PEG concept (linear-
   tangent formulation).

5. **International Standard Atmosphere (ISO 2533:1975)** — Tropospheric lapse
   rate model, sea-level reference conditions.

6. **Apollo Mission Reports (NASA SP-series)** — LOI Δv, reentry flight path
   angle, entry interface altitude references.

7. **SciPy documentation** — `solve_ivp` (RK45 method), `least_squares`
   (trust-region reflective algorithm), `PchipInterpolator`.
