# SPDX-License-Identifier: MIT
"""Pure-Python stroke math. No Qt, no Krita: unit-testable anywhere.

A sample is a tuple (t_seconds, x_px, y_px, pressure_0_1).
Positions are global screen pixels, so on a display tablet (Kamvas) a screen mm
is a pen-on-glass mm, and on an Intuos it is the mapped equivalent.
"""
import math

SPEED_WINDOW_S = 0.02  # speeds are measured over >= 20 ms to kill event jitter


def _mean(v):
    return sum(v) / len(v) if v else 0.0


def _std(v):
    if len(v) < 2:
        return 0.0
    m = _mean(v)
    return math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1))


def _cv(v):
    m = _mean(v)
    return _std(v) / m if m > 1e-9 else 0.0


def _pearson(a, b):
    if len(a) < 3:
        return 0.0
    ma, mb = _mean(a), _mean(b)
    sa = math.sqrt(sum((x - ma) ** 2 for x in a))
    sb = math.sqrt(sum((y - mb) ** 2 for y in b))
    if sa < 1e-9 or sb < 1e-9:
        return 0.0
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (sa * sb)


def arclengths(samples):
    s = [0.0]
    for i in range(1, len(samples)):
        _, x0, y0, _ = samples[i - 1]
        _, x1, y1, _ = samples[i]
        s.append(s[-1] + math.hypot(x1 - x0, y1 - y0))
    return s


def speeds(samples, s=None):
    """Per-sample speed in px/s, windowed forward over SPEED_WINDOW_S."""
    n = len(samples)
    if n < 2:
        return [0.0] * n
    s = s or arclengths(samples)
    out, j = [], 0
    for i in range(n):
        j = max(j, i + 1)
        while j < n - 1 and samples[j][0] - samples[i][0] < SPEED_WINDOW_S:
            j += 1
        jj = min(j, n - 1)
        dt = samples[jj][0] - samples[i][0]
        if dt <= 1e-6 and i > 0:
            out.append(out[-1])
            continue
        out.append((s[jj] - s[i]) / dt if dt > 1e-6 else 0.0)
    return out


def _slice_by_frac(values, fracs, lo, hi):
    picked = [v for v, f in zip(values, fracs) if lo <= f <= hi]
    return picked or values


def stroke_metrics(samples, px_per_mm=3.78, screen_diag_px=None):
    """Everything a lesson or the Dojo wants to know about one stroke."""
    if len(samples) < 3:
        return None
    s = arclengths(samples)
    length = s[-1]
    duration = max(samples[-1][0] - samples[0][0], 1e-6)
    if length < 1.0:
        return None
    fr = [v / length for v in s]
    ps = [p for (_, _, _, p) in samples]
    vs = speeds(samples, s)

    core_v = _slice_by_frac(vs, fr, 0.1, 0.9)
    core_p = _slice_by_frac(ps, fr, 0.1, 0.9)
    p_start = _mean(_slice_by_frac(ps, fr, 0.0, 0.15))
    p_mid = _mean(_slice_by_frac(ps, fr, 0.35, 0.65))
    p_end = _mean(_slice_by_frac(ps, fr, 0.85, 1.0))

    # smoothed peak position along the stroke
    k = max(1, len(ps) // 20)
    sm = [_mean(ps[max(0, i - k): i + k + 1]) for i in range(len(ps))]
    peak_i = max(range(len(sm)), key=lambda i: sm[i])

    x0, y0 = samples[0][1], samples[0][2]
    x1, y1 = samples[-1][1], samples[-1][2]
    chord = math.hypot(x1 - x0, y1 - y0)
    # screen y points down; flip so 45 degrees means up-right like math class
    direction = math.degrees(math.atan2(-(y1 - y0), x1 - x0)) % 360.0
    xs = [smp[1] for smp in samples]
    ys = [smp[2] for smp in samples]
    w, h = max(xs) - min(xs), max(ys) - min(ys)

    m = {
        "n": len(samples),
        "length_px": length,
        "length_mm": length / px_per_mm,
        "duration_s": duration,
        "speed_mm_s": (length / duration) / px_per_mm,
        "speed_cv": _cv(core_v),
        "speed_max_mm_s": (max(vs) if vs else 0.0) / px_per_mm,
        "p_min": min(ps),
        "p_max": max(ps),
        "p_mean": _mean(ps),
        "p_cv": _cv(core_p),
        "p_start": p_start,
        "p_mid": p_mid,
        "p_end": p_end,
        "p_peak_frac": fr[peak_i],
        "ramp_r": _pearson(fr, ps),
        "straightness": chord / length,
        "direction_deg": direction,
        "orientation_deg": direction % 180.0,
        "extent_w_px": w,
        "extent_h_px": h,
        "extent_frac": (math.hypot(w, h) / screen_diag_px) if screen_diag_px else 0.0,
    }
    return m


def series(samples):
    """(t_rel, pressure, speed_px_s) lists for drawing the seismograph."""
    if not samples:
        return [], [], []
    t0 = samples[0][0]
    return ([smp[0] - t0 for smp in samples], [smp[3] for smp in samples], speeds(samples))


def orientation_spread_deg(orients):
    """Circular std of line orientations (0..180) in degrees."""
    if len(orients) < 2:
        return 0.0
    c = _mean([math.cos(math.radians(2 * o)) for o in orients])
    s = _mean([math.sin(math.radians(2 * o)) for o in orients])
    r = min(1.0, max(1e-9, math.hypot(c, s)))
    return math.degrees(math.sqrt(-2.0 * math.log(r))) / 2.0


# ---------------------------------------------------------------- criteria

def _span(m, calib):
    lo = calib.get("light", 0.05) if calib else 0.05
    hi = calib.get("heavy", 0.95) if calib else 0.95
    rng = max(hi - lo, 0.1)
    return (m["p_max"] - m["p_min"]) / rng


def judge(m, crit, calib=None, source="tablet"):
    """Return (ok, coach_line). First failing criterion gets the coaching."""
    if m is None:
        return False, "Keep the pen down a little longer."
    if crit.get("source") == "tablet" and source != "tablet":
        return False, ("That came in as a mouse, not a pen. Peek at Settings > Configure Krita > "
                       "Tablet Settings and try the other tablet input API.")
    c = crit.get
    if c("min_length_mm") and m["length_mm"] < c("min_length_mm"):
        return False, "Longer! %.0f mm, aim for %.0f mm or more." % (m["length_mm"], c("min_length_mm"))
    if c("min_extent_frac") and m["extent_frac"] < c("min_extent_frac"):
        return False, ("Bigger! That covered %d%% of the screen. Swing from the elbow and shoulder, "
                       "aim for %d%%." % (100 * m["extent_frac"], 100 * c("min_extent_frac")))
    if c("max_mean_pressure") is not None and m["p_mean"] > c("max_mean_pressure"):
        return False, "Lighter! Average pressure was %d%%. Feather it." % (100 * m["p_mean"])
    if c("min_mean_pressure") is not None and m["p_mean"] < c("min_mean_pressure"):
        return False, "Lean in! Average pressure was only %d%%." % (100 * m["p_mean"])
    if c("pressure_span_min") and _span(m, calib) < c("pressure_span_min"):
        return False, ("Use more of your range: you swept %d%% of it, go for %d%%."
                       % (100 * _span(m, calib), 100 * c("pressure_span_min")))
    if c("ramp_min") and m["ramp_r"] < c("ramp_min"):
        if m["ramp_r"] < -0.3:
            return False, "Backwards! That one got lighter. Start soft, finish heavy."
        return False, "Start lighter, end heavier. Crescendo, not a wobble."
    if c("taper"):
        swell = m["p_mid"] > 1e-6 and max(m["p_start"], m["p_end"]) <= 0.65 * m["p_mid"]
        centered = 0.2 <= m["p_peak_frac"] <= 0.8
        if not (swell and centered):
            return False, "Thin, THICK, thin. Land soft, swell in the middle, lift off soft."
    if c("pressure_cv_max") and m["p_cv"] > c("pressure_cv_max"):
        return False, "Steady on the dimmer: pressure wobbled %d%%. Aim under %d%%." % (
            100 * m["p_cv"], 100 * c("pressure_cv_max"))
    if c("speed_mm_s_max") and m["speed_mm_s"] > c("speed_mm_s_max"):
        return False, "Slower. You flew at %.0f mm/s, glide under %.0f." % (m["speed_mm_s"], c("speed_mm_s_max"))
    if c("speed_mm_s_min") and m["speed_mm_s"] < c("speed_mm_s_min"):
        return False, "Faster! %.0f mm/s. Flick it past %.0f." % (m["speed_mm_s"], c("speed_mm_s_min"))
    if c("speed_cv_max") and m["speed_cv"] > c("speed_cv_max"):
        return False, "Even speed, no braking mid-stroke (wobble %d%%)." % (100 * m["speed_cv"])
    if c("straightness_min") and m["straightness"] < c("straightness_min"):
        return False, "Straighter. Ghost it in the air first, then commit from the shoulder."
    if c("orientation_deg") is not None:
        d = abs(((m["orientation_deg"] - c("orientation_deg") + 90) % 180) - 90)
        if d > c("orientation_tol", 12):
            return False, "Angle check: that was %.0f degrees, the lane wants %.0f." % (
                m["orientation_deg"], c("orientation_deg"))
    return True, ""


# ---------------------------------------------------------------- dojo scores

def _clamp(v):
    return max(0.0, min(100.0, v))


def drill_score(drill, m, recent=None):
    """0..100 for one stroke (or the recent set, for set drills). None = no score."""
    if m is None:
        return None
    if drill == "even":
        return _clamp(100 * (1 - m["p_cv"] / 0.35)) if m["length_mm"] >= 40 else 0.0
    if drill == "swell":
        if m["p_mid"] <= 1e-6:
            return 0.0
        lift = (m["p_mid"] - max(m["p_start"], m["p_end"])) / m["p_mid"]
        center = 1 - min(1.0, abs(m["p_peak_frac"] - 0.5) / 0.5)
        return _clamp(100 * (0.7 * min(1.0, lift / 0.6) + 0.3 * center))
    if drill == "steady":
        return _clamp(100 * (1 - m["speed_cv"] / 0.8)) if m["length_mm"] >= 40 else 0.0
    if drill == "flick":
        straight = max(0.0, (m["straightness"] - 0.85) / 0.15)
        return _clamp(100 * straight * min(1.0, m["speed_mm_s"] / 200.0))
    if drill == "hatch":
        recent = recent or [m]
        if len(recent) < 3:
            return None
        spread = orientation_spread_deg([r["orientation_deg"] for r in recent])
        pace = _cv([r["speed_mm_s"] for r in recent])
        return _clamp(100 * (1 - spread / 20.0) * (1 - min(1.0, pace / 0.5)))
    return None
