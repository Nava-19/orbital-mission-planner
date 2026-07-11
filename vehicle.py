import numpy as np
from constants import g0, Mu, Re

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
        
        # Finalize guidance now that burnout time is known
        t_burnout = self.timeline[-1][2]   # Last stage cutoff
        self.guidance._finalize(t_burnout)

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

class GuidanceProfile:
    def __init__(self, t_vertical, target_altitude):
        """
        t_vertical      : s - Vertical ascent duration
        target_altitude : m - Target circular orbit altitude

        All timing parameters are derived automatically from physics.
        t_horizontal is set by Rocket._build_timeline() via _finalize().
        """
        self.t_vertical      = t_vertical
        self.target_altitude = target_altitude
        self.v_target        = np.sqrt(Mu / (Re + target_altitude))
        # Estimate time to clear dense atmosphere based on vertical ascent rate
        # Rocket reaches ~500 m/s vertically after ~40s, average ~250 m/s
        # Time to reach 25km (safe pitchover altitude) ≈ 25000/250 = 100s
        self.t_pitchover_end = t_vertical + (25000 / 250)   # ~120s total
        self.t_horizontal    = None                         # Set by _finalize

    def _finalize(self, t_burnout):
        """
        Called by Rocket._build_timeline() once stage burnout times are known.
        For orbits above 2000 km the rocket targets a LEO parking orbit (~300 km)
        and a Hohmann transfer is computed separately. This keeps the ascent
        guidance physically realistic regardless of target altitude.
        """
        self.t_burnout = t_burnout

        LEO_THRESHOLD = 2000e3   # m - above this, use parking orbit strategy
        if self.target_altitude > LEO_THRESHOLD:
            # Target LEO parking orbit — pitch over faster to maximise tangential v
            self.t_horizontal = t_burnout * 0.75
        elif self.target_altitude > 800e3:
            # Upper LEO / MEO direct — moderate pitch
            self.t_horizontal = t_burnout * 0.80
        else:
            # Standard LEO
            self.t_horizontal = t_burnout * 0.85

    def get_pitch_angle(self, t):
        """
        Three-phase gravity turn derived from target orbit:
          - 0 to t_vertical               : vertical ascent
          - t_vertical to t_pitchover_end : pitch to 45° through dense atmosphere
          - t_pitchover_end to t_horizontal: pitch from 45° to 90° in vacuum
          - t_horizontal+                 : full horizontal burn for orbital insertion
        """
        if t < self.t_vertical:
            return 0.0
        elif t < self.t_pitchover_end:
            return np.radians(45) * (t - self.t_vertical) / (self.t_pitchover_end - self.t_vertical)
        elif t < self.t_horizontal:
            return np.radians(45) + np.radians(45) * (t - self.t_pitchover_end) / (self.t_horizontal - self.t_pitchover_end)
        else:
            return np.radians(90)