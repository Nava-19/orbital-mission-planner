import numpy as np
from scipy.optimize import least_squares
from constants import g0, Mu, Re
from environment import get_gravity

class Stage:
    def __init__(self, dry_mass, prop_mass, thrust, Isp, Cd, A):
        """
        dry_mass  : kg - Structural mass of this stage (no propellant)
        prop_mass : kg - Propellant mass of this stage
        thrust    : N  - Maximum thrust (assumed constant)
        Isp       : s  - Specific impulse
        Cd        :  - - Drag coefficient
        A         : m² - Cross-sectional area
        """
        self.dry_mass  = dry_mass
        self.prop_mass = prop_mass
        self.thrust    = thrust
        self.Isp       = Isp
        self.Cd        = Cd
        self.A         = A
        self.mdot      = thrust / (Isp * g0)  # kg/s - Propellant consumption rate

    @property
    def total_mass(self):
        """Total mass of this stage when full"""
        return self.dry_mass + self.prop_mass

    @property
    def burnout_time(self):
        """Time (s) to exhaust all propellant"""
        return self.prop_mass / self.mdot


class Rocket:
    def __init__(self, stages, payload_mass, guidance):
        """
        stages       : list[Stage] - Ordered list of stages, from bottom to top
        payload_mass : kg          - Payload mass sitting on top of all stages
        """
        self.stages       = stages
        self.payload_mass = payload_mass
        self.guidance = guidance
        self._build_timeline()

    def _build_timeline(self):
        """
        Pre-computes the absolute ignition and cutoff time for each stage,
        accounting for the staging sequence.
        """
        self.timeline = []  # List of (stage, t_ignition, t_cutoff)
        t = 0
        for stage in self.stages:
            t_ignition = t
            t_cutoff   = t + stage.burnout_time
            self.timeline.append((stage, t_ignition, t_cutoff))
            t = t_cutoff
        
        # Finalize guidance now that the full stage timeline is known
        self.guidance._finalize(self.timeline)

    def _get_active_stage(self, t):
        """Returns the currently burning stage and its ignition time, or None if coasting"""
        for stage, t_ign, t_cut in self.timeline:
            if t_ign <= t < t_cut:
                return stage, t_ign
        return None, None

    def get_mass(self, t):
        """
        Returns total vehicle mass at time t.
        Dropped stages are excluded from the mass budget.
        """
        mass = self.payload_mass

        for stage, t_ign, t_cut in self.timeline:
            if t < t_ign:
                mass += stage.total_mass        # Stage not yet ignited, still attached
            elif t < t_cut:
                prop_burned = stage.mdot * (t - t_ign)
                mass += stage.dry_mass + (stage.prop_mass - prop_burned)  # Burning
            # If t >= t_cut, stage has been jettisoned —> not added to mass

        return mass

    def get_thrust(self, t, altitude):
        """Returns thrust of the active stage, 0 if coasting between stages"""
        stage, _ = self._get_active_stage(t)
        return stage.thrust if stage else 0

    def get_pitch_angle(self, t):
        """Delegates pitch angle to the guidance profile"""
        return self.guidance.get_pitch_angle(t)                             # Horizontal

    @property
    def Cd(self):
        """Drag coefficient of the current bottom stage (fairing)"""
        return self.stages[0].Cd

    @property
    def A(self):
        """Cross-sectional area of the current bottom stage"""
        return self.stages[0].A

class PEGGuidance:
    """
    Closed-loop Powered Explicit Guidance (PEG) for the 2D ascent model.

    Unlike the old open-loop GuidanceProfile — a pitch ramp with hand-tuned
    timing constants calibrated against one or two reference vehicles — PEG
    derives the steering law from physics, and keeps correcting it in flight:

      1. From the CURRENT real state, it predicts forward with a fast,
         simplified model (vacuum, point-mass gravity — no drag) what a
         candidate linear pitch law  theta(tau) = theta0 + rate*tau  would
         achieve after burning for `tgo` more seconds.
      2. It searches (theta0, rate, tgo) so that predicted end state hits
         the parking-orbit target exactly: radius = r_park, radial
         velocity = 0, tangential velocity = circular velocity at r_park.
      3. It RE-SOLVES this every REPLAN_INTERVAL seconds of real flight,
         using the real (drag-affected) state each time — this is what
         makes it closed-loop: whatever the simplified internal predictor
         gets wrong (atmospheric drag, staging discreteness) is corrected
         at the next replan using the vehicle's actual position/velocity.
      4. Engine cutoff is commanded the moment the REAL trajectory actually
         reaches the target — not on a fixed schedule and not necessarily
         when propellant runs out. An overpowered vehicle (e.g. Saturn V
         aimed at a modest LEO parking orbit) cuts off with propellant to
         spare instead of being forced to keep burning.

    Note on scope: real PEG (as flown on Saturn/Shuttle) uses linear-TANGENT
    steering (tan(angle) = A + B*t) together with closed-form gravity-loss
    integrals, which are only well-behaved for near-flat, short-arc ascents.
    This implementation uses linear-ANGLE steering solved by numerical
    shooting (least-squares) instead, which is far more numerically robust
    across arbitrary, user-defined multi-stage vehicles and orbit targets —
    it keeps PEG's essential idea (predict → solve → replan → cut off on
    target) without inheriting the classic formulation's fragility outside
    its original design envelope.
    """

    REPLAN_INTERVAL = 20.0   # s - how often the steering law is re-solved
    MIN_TGO         = 20.0   # s - never plan a burn segment shorter than this
    MAX_RATE        = 0.05   # rad/s - bound on how fast pitch may change

    def __init__(self, t_vertical, target_altitude, parking_altitude=None):
        """
        t_vertical       : s - initial vertical ascent (tower/pad clearance)
        target_altitude  : m - final desired orbit altitude
        parking_altitude : m - LEO parking orbit PEG targets on ascent.
                                Defaults to a standard ~250 km low parking
                                orbit (or the target itself if that's lower),
                                same practice real launch vehicles follow:
                                park low, then do a separate transfer burn
                                for anything higher (handled elsewhere, in
                                orbital.py's Hohmann transfer logic).
        """
        self.t_vertical      = t_vertical
        self.target_altitude = target_altitude
        self.parking_altitude = (
            parking_altitude if parking_altitude is not None
            else min(target_altitude, 250e3)
        )
        self.r_park      = Re + self.parking_altitude
        self.v_circ_park = np.sqrt(Mu / self.r_park)

        # PEG only takes over once the vehicle has cleared the dense lower
        # atmosphere. Before that — same as real launch vehicles (Saturn V
        # and Shuttle both flew an open-loop "tilt program" through max-Q,
        # only engaging closed-loop PEG afterwards) — a small, fixed pitch
        # "kick" is used. t_peg_start itself is set in _finalize(), once
        # the actual stage-1 burn duration is known (see rationale there).
        self.t_peg_start  = t_vertical + 100.0   # placeholder, refined in _finalize
        self.kick_angle   = np.radians(20)

        # Current steering law (refined by replan() as flight progresses).
        # theta=0 is vertical/radial thrust, theta=pi/2 is fully tangential
        # (same convention as the rest of the codebase) — so flight starts
        # close to vertical and the angle INCREASES over time.
        self.theta0    = np.radians(15)
        self.rate      = 0.01
        self.tgo       = None
        self.t_plan_ref = None     # absolute time the current law was solved at

        self.t_burnout_nominal = None   # informational only, see _finalize()
        self.cutoff_time       = None   # set once should_cutoff() fires
        self._replan_count     = 0      # bounds multi-start retry cost over the flight

    def _finalize(self, timeline):
        """
        Called by Rocket._build_timeline() once the full stage timeline is
        known.

        t_peg_start is set here rather than at construction time: it must
        give PEG meaningful control authority over the first stage's burn,
        not just whatever's left after a fixed generic "kick" window. A
        short, very high-thrust first stage (e.g. solid boosters, burning
        out in ~130 s) would otherwise be almost entirely spent before
        closed-loop guidance ever engages, wasting its steering potential —
        this was observed to leave some vehicles unable to reach their
        target parking orbit precisely. Capping the kick window at half of
        the first stage's own burn duration guarantees PEG always gets at
        least the back half of it to work with.
        """
        self.t_burnout_nominal = timeline[-1][2]
        stage1_cutoff = timeline[0][2]
        self.t_peg_start = min(
            self.t_vertical + 100.0,
            self.t_vertical + 0.5 * (stage1_cutoff - self.t_vertical),
        )

    # ────────────────────────────────────────────────────────────
    # Steering law evaluation
    # ────────────────────────────────────────────────────────────
    def get_pitch_angle(self, t):
        if t < self.t_vertical:
            return 0.0
        if t < self.t_peg_start:
            # Open-loop kick through the dense atmosphere, same rationale
            # real launch vehicles use before engaging closed-loop guidance.
            frac = (t - self.t_vertical) / (self.t_peg_start - self.t_vertical)
            return float(self.kick_angle * frac)
        if self.t_plan_ref is None:
            return self.kick_angle    # PEG hasn't solved yet — hold the kick angle
        tau   = t - self.t_plan_ref
        theta = self.theta0 + self.rate * tau
        return float(np.clip(theta, 0.0, np.pi / 2))

    # ────────────────────────────────────────────────────────────
    # Engine cutoff
    # ────────────────────────────────────────────────────────────
    def should_cutoff(self, t, state, rocket):
        """
        True once the REAL trajectory has reached the parking-orbit apoapsis
        (radius = r_park, radial velocity = 0) — i.e. MECO happens exactly
        at the apex of the ascent ellipse, same as the existing downstream
        architecture expects (a separate circularize() burn at apoapsis
        raises the periapsis afterward — PEG doesn't need to hit exact
        circular velocity here, only get the apoapsis right).
        """
        if self.cutoff_time is not None:
            return t >= self.cutoff_time
        if t < self.t_peg_start or t >= self.t_burnout_nominal:
            return False

        x, y, vx, vy = state
        r  = np.hypot(x, y)
        vr = (x * vx + y * vy) / r

        reached_altitude = r >= self.r_park
        near_zero_vr      = abs(vr) < 15.0     # m/s tolerance

        if reached_altitude and near_zero_vr:
            self.cutoff_time = t
            return True
        return False

    # ────────────────────────────────────────────────────────────
    # Closed-loop replanning
    # ────────────────────────────────────────────────────────────
    def replan(self, t, state, rocket):
        """
        Re-solve the steering law (theta0, rate) from the real state, using
        ALL remaining propellant as the burn horizon and targeting the
        parking-orbit APOAPSIS exactly (r = r_park, radial velocity = 0) —
        the same 2 conditions the pre-PEG architecture already relied on
        (MECO produces an ellipse whose apoapsis becomes the parking orbit
        after a separate circularize() burn). This 2-condition target with
        2 free steering parameters is well-posed and converges essentially
        exactly; earlier attempts at also pinning down tangential velocity
        (full circular insertion) or leaving tgo free needed more energy /
        time than some vehicles have available and would not converge.
        """
        if t < self.t_peg_start:
            return

        x, y, vx, vy = state
        r0  = np.hypot(x, y)
        vr0 = (x * vx + y * vy) / r0
        vt0 = (x * vy - y * vx) / r0

        tgo = self._remaining_propellant_time(t, rocket)
        if tgo < self.MIN_TGO:
            return   # essentially out of fuel — fly out the last known law

        def residuals(params):
            theta0, rate = params
            r_f, vr_f, _ = self._predict(t, r0, vr0, vt0, theta0, rate, tgo, rocket)
            return [
                (r_f - self.r_park) / self.r_park,
                vr_f / self.v_circ_park,
            ]

        # Warm-start from the last solution first (cheap — a single solve).
        candidates = [(self.theta0, self.rate)] if self.tgo is not None else []
        best_sol = None
        for theta0_guess, rate_guess in candidates:
            try:
                sol = least_squares(
                    residuals,
                    x0=[theta0_guess, rate_guess],
                    bounds=([0.0, -self.MAX_RATE], [np.pi / 2, self.MAX_RATE]),
                    xtol=1e-10, ftol=1e-10, max_nfev=200,
                )
                if best_sol is None or sol.cost < best_sol.cost:
                    best_sol = sol
            except Exception:
                continue

        # Fall back to a multi-start search — spanning the plausible pitch
        # range — whenever there's no warm start yet (first replan of the
        # flight) OR the warm-started solve still leaves a large residual.
        # A persistently poor fit despite warm-starting has been observed
        # for vehicles with very asymmetric stage profiles (e.g. Ariane 5's
        # short, huge-thrust first stage followed by a long, much weaker
        # upper stage): the 2-parameter shooting problem can settle into a
        # bad local minimum that warm-starting alone never escapes.
        # Multi-start only on the FIRST replan of the flight: this is the
        # only point where the initial guess is a generic seed rather than
        # a warm start from an already-good previous solution, and where a
        # bad local minimum trap has been observed for vehicles with very
        # asymmetric stage profiles. Subsequent replans warm-start from the
        # last good solution and converge in a single cheap solve — always
        # retrying on a merely "high" cost turned out to occasionally
        # derail an otherwise good, converging trajectory (a temporarily
        # elevated residual right after a replan, before the next one
        # corrects it, is expected and not itself a sign of a bad fit).
        if best_sol is None:
            for theta0_seed in np.radians([10, 30, 50, 70]):
                try:
                    sol = least_squares(
                        residuals,
                        x0=[theta0_seed, 0.0],
                        bounds=([0.0, -self.MAX_RATE], [np.pi / 2, self.MAX_RATE]),
                        xtol=1e-10, ftol=1e-10, max_nfev=200,
                    )
                    if best_sol is None or sol.cost < best_sol.cost:
                        best_sol = sol
                    if best_sol.cost < 1e-6:
                        break
                except Exception:
                    continue

        if best_sol is not None:
            self.theta0, self.rate = best_sol.x
            self.tgo        = tgo
            self.t_plan_ref = t
        # else: keep flying the previous law if every attempt failed

    def _remaining_propellant_time(self, t, rocket):
        """Total remaining burn time across the current + future stages."""
        total = 0.0
        for stage, t_ign, t_cut in rocket.timeline:
            if t < t_ign:
                total += (t_cut - t_ign)
            elif t < t_cut:
                total += (t_cut - t)
        return total

    def _predict(self, t_now, r0, vr0, vt0, theta0, rate, tgo, rocket):
        """
        Fast internal forward propagation (vacuum, point-mass gravity) used
        ONLY to solve the steering law. This is NOT the trajectory that
        gets drawn/animated — that comes from the real integrator in
        solver.py, which does include atmospheric drag.

        Uses a fixed-step RK4 instead of scipy's adaptive solve_ivp: this
        function is called many times per replan (least_squares evaluates
        it repeatedly for its Jacobian), and solve_ivp's per-call overhead
        dominates at that scale for such a tiny (4-variable) ODE system.
        """
        m0 = rocket.get_mass(t_now)
        n_steps = 40                      # fixed resolution regardless of tgo
        h = tgo / n_steps

        def deriv(tau, s):
            r, vr, vt, m = s
            theta  = theta0 + rate * tau
            theta  = 0.0 if theta < 0.0 else (np.pi / 2 if theta > np.pi / 2 else theta)
            t_abs  = t_now + tau
            thrust = rocket.get_thrust(t_abs, r - Re)
            stage, _ = rocket._get_active_stage(t_abs)
            mdot   = stage.mdot if stage else 0.0
            g      = get_gravity(r - Re)
            m_safe = m if m > 1e-3 else 1e-3
            dvr = -g + vt * vt / r + (thrust / m_safe) * np.cos(theta)
            dvt = -vr * vt / r     + (thrust / m_safe) * np.sin(theta)
            return np.array([vr, dvr, dvt, -mdot])

        s = np.array([r0, vr0, vt0, m0], dtype=float)
        tau = 0.0
        for _ in range(n_steps):
            k1 = deriv(tau, s)
            k2 = deriv(tau + h/2, s + h/2*k1)
            k3 = deriv(tau + h/2, s + h/2*k2)
            k4 = deriv(tau + h,   s + h*k3)
            s  = s + (h/6.0) * (k1 + 2*k2 + 2*k3 + k4)
            tau += h

        r_f, vr_f, vt_f, _ = s
        return r_f, vr_f, vt_f