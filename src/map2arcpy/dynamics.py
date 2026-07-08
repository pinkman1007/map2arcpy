"""
System-dynamics behaviour classifier — the math foundation for the classic
systems archetypes (Limits to Growth, Fixes that Fail, Shifting the Burden,
Tragedy of the Commons, Escalation, Success to the Successful, Eroding Goals).

These archetypes are NOT map themes; they are characteristic *behaviours over
time* produced by feedback-loop structures. Each has a governing stock-flow
equation and a signature trajectory. Given a real time series (e.g. built-up
area per year, carbon per epoch, your PERSIANN annual rainfall), we FIT the
candidate models by least squares and report which archetype's signature the
numbers are consistent with, plus the quantitative indicators (growth rate,
carrying capacity, fraction of limit reached, doubling time, inflection).

HONESTY (the identifiability caveat): matching a behaviour signature is
evidence, NOT proof of structure. Different loop structures can produce
similar curves. Every diagnosis says "consistent with", reports the fit R²,
and never claims to have proven the mechanism. This is the intellectually
honest position and matches the rest of the tool.

Pure stdlib (math only) — logistic is fit by a grid search over the carrying
capacity K with a closed-form linear fit on the logit at each K, so no
iterative optimiser or numpy is needed.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple


# ===========================================================================
# least squares primitives
# ===========================================================================
def ols(xs: Sequence[float], ys: Sequence[float]) -> Tuple[float, float, float]:
    """Ordinary least squares y = slope*x + intercept. Returns (slope,
    intercept, r2). r2 is 0 when y has no variance."""
    n = len(xs)
    if n < 2:
        return 0.0, (ys[0] if ys else 0.0), 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0:
        return 0.0, my, 0.0
    slope = sxy / sxx
    intercept = my - slope * mx
    r2 = (sxy * sxy) / (sxx * syy) if syy > 0 else 1.0
    return slope, intercept, max(0.0, min(1.0, r2))


def _r2_of(t: Sequence[float], x: Sequence[float], pred) -> float:
    mx = sum(x) / len(x)
    ss_tot = sum((xi - mx) ** 2 for xi in x)
    ss_res = sum((xi - pred(ti)) ** 2 for ti, xi in zip(t, x))
    if ss_tot == 0:
        return 1.0 if ss_res == 0 else 0.0
    return max(0.0, 1.0 - ss_res / ss_tot)


# ===========================================================================
# model fits
# ===========================================================================
def fit_linear(t: Sequence[float], x: Sequence[float]) -> Dict[str, float]:
    slope, intercept, r2 = ols(t, x)
    return {"model": "linear", "slope": slope, "intercept": intercept, "r2": r2}


def fit_exponential(t: Sequence[float], x: Sequence[float]) -> Optional[Dict[str, float]]:
    """x = x0 * e^(r t), fit by OLS on ln(x). Needs all x > 0."""
    if any(xi <= 0 for xi in x) or len(x) < 3:
        return None
    lnx = [math.log(xi) for xi in x]
    r, b, _ = ols(t, lnx)
    x0 = math.exp(b)
    r2 = _r2_of(t, x, lambda ti: x0 * math.exp(r * ti))
    out = {"model": "exponential", "r": r, "x0": x0, "r2": r2}
    if r > 0:
        out["doubling_time"] = math.log(2) / r
    elif r < 0:
        out["half_life"] = math.log(2) / (-r)
    return out


def fit_logistic(t: Sequence[float], x: Sequence[float],
                 k_steps: int = 240) -> Optional[Dict[str, float]]:
    """Logistic x = K / (1 + A e^(-r t)), the Limits-to-Growth signature.

    For a fixed K the logit  y = ln(x/(K-x)) = -ln A + r t  is linear in t,
    so we grid-search K and take the closed-form linear fit with the best R².
    """
    n = len(x)
    if n < 4:
        return None
    xmax = max(x)
    if xmax <= 0:
        return None
    lo = xmax * 1.001
    hi = xmax * 4.0
    best = None
    for i in range(k_steps + 1):
        K = lo + (hi - lo) * i / k_steps
        pts = [(ti, xi) for ti, xi in zip(t, x) if 0 < xi < K]
        if len(pts) < 3:
            continue
        tt = [p[0] for p in pts]
        yy = [math.log(p[1] / (K - p[1])) for p in pts]
        r, b, _ = ols(tt, yy)
        if r <= 0:
            continue
        A = math.exp(-b)
        r2 = _r2_of(t, x, lambda ti, K=K, A=A, r=r: K / (1 + A * math.exp(-r * ti)))
        if best is None or r2 > best["r2"]:
            t_mid = math.log(A) / r if A > 0 else t[0]
            best = {"model": "logistic", "K": K, "r": r, "A": A,
                    "t_mid": t_mid, "r2": r2,
                    "fraction_of_K": x[-1] / K}
    return best


# ===========================================================================
# trajectory features
# ===========================================================================
def _features(x: Sequence[float]) -> Dict[str, float]:
    n = len(x)
    diffs = [x[i + 1] - x[i] for i in range(n - 1)]
    peak_i = max(range(n), key=lambda i: x[i])
    trough_i = min(range(n), key=lambda i: x[i])
    sign_changes = sum(1 for i in range(len(diffs) - 1)
                       if diffs[i] * diffs[i + 1] < 0)
    return {
        "n": n,
        "first": x[0], "last": x[-1],
        "peak": x[peak_i], "peak_i": peak_i,
        "trough": x[trough_i], "trough_i": trough_i,
        "net_change": x[-1] - x[0],
        "sign_changes": sign_changes,
        "monotonic_up": all(d >= 0 for d in diffs),
        "monotonic_down": all(d <= 0 for d in diffs),
    }


# ===========================================================================
# the classifier
# ===========================================================================
#: archetype -> (loop structure, governing equation) for the report
ARCHETYPE_MATH = {
    "reinforcing growth":
        ("one dominant reinforcing loop", "dx/dt = r x  (x = x0 e^{rt})"),
    "limits to growth":
        ("reinforcing loop checked by a balancing loop (a limit)",
         "dx/dt = r x (1 - x/K)  (logistic S-curve)"),
    "overshoot and collapse":
        ("limits to growth with a DELAY in the limiting signal, or an "
         "erodable carrying capacity (tragedy of the commons)",
         "dx/dt = r x (1 - x/K(t)),  K eroded by x with delay"),
    "steady trend":
        ("balancing loop tracking a moving goal, or a slow linear drift",
         "x = a + b t"),
    "decline / erosion":
        ("balancing loop toward a goal whose reference is itself eroding "
         "(eroding goals), or net outflow / depletion",
         "dx/dt = -k (x - G),  G drifting down"),
    "recovery / rebound":
        ("a fix that relieved a symptom then failed — the problem returns "
         "(fixes that fail / shifting the burden)",
         "problem down then up past baseline as the side-effect loop acts"),
}


def classify(series: Sequence[float],
             times: Optional[Sequence[float]] = None,
             kind: str = "stock") -> Dict:
    """Classify a single time series against the behaviour archetypes.

    kind: "stock" (an accumulation — built-up area, carbon) or "problem"
    (a symptom metric where down-then-up means a fix that failed).

    Returns a dict with: behaviour, candidate archetype(s), the winning model
    fit, indicators, and an honest caveat string.
    """
    x = [float(v) for v in series]
    if len(x) < 3:
        return {"behaviour": "insufficient data",
                "caveat": "need at least 3 time points to say anything; "
                          "4+ for a limits-to-growth (logistic) fit",
                "n": len(x)}
    t = [float(v) for v in (times if times is not None else range(len(x)))]

    feat = _features(x)
    lin = fit_linear(t, x)
    exp = fit_exponential(t, x)
    log = fit_logistic(t, x)

    fits = {"linear": lin}
    if exp:
        fits["exponential"] = exp
    if log:
        fits["logistic"] = log

    behaviour = None
    archetypes: List[str] = []
    indicators: Dict[str, float] = {}

    # peak-then-decline (overshoot) — only if the peak is interior and the
    # fall-back is material
    interior_peak = 0 < feat["peak_i"] < feat["n"] - 1
    fell_back = feat["last"] < feat["peak"] * 0.92
    if interior_peak and fell_back and feat["peak"] > feat["first"]:
        behaviour = "overshoot then decline"
        archetypes = ["overshoot and collapse"]
        indicators = {"peak_at_index": feat["peak_i"], "peak": feat["peak"],
                      "fallen_to_fraction_of_peak": feat["last"] / feat["peak"]}

    # problem metric that dipped then rebounded past baseline
    elif kind == "problem" and 0 < feat["trough_i"] < feat["n"] - 1 \
            and feat["last"] > feat["first"] and feat["trough"] < feat["first"]:
        behaviour = "improved then worsened past baseline"
        archetypes = ["recovery / rebound"]
        indicators = {"trough_at_index": feat["trough_i"],
                      "now_vs_start": feat["last"] / feat["first"] if feat["first"] else 0.0}

    # S-curve approaching a limit
    elif log and log["r2"] >= 0.9 and log["r2"] >= (exp["r2"] if exp else 0) - 0.02 \
            and log["fraction_of_K"] > 0.55:
        behaviour = "S-curve approaching a limit"
        archetypes = ["limits to growth"]
        indicators = {"carrying_capacity_K": log["K"], "growth_rate_r": log["r"],
                      "fraction_of_K_reached": log["fraction_of_K"],
                      "inflection_time": log["t_mid"], "logistic_r2": log["r2"]}

    # accelerating growth, no binding limit visible yet
    elif exp and exp["r"] > 0 and exp["r2"] >= 0.9 and feat["monotonic_up"]:
        behaviour = "accelerating (near-exponential) growth"
        archetypes = ["reinforcing growth"]
        indicators = {"growth_rate_r": exp["r"], "exp_r2": exp["r2"]}
        if "doubling_time" in exp:
            indicators["doubling_time"] = exp["doubling_time"]
        if log and log["fraction_of_K"] > 0.4:
            archetypes.append("limits to growth (watch)")
            indicators["approx_K_if_limited"] = log["K"]

    elif feat["monotonic_down"] or (feat["net_change"] < 0 and feat["sign_changes"] <= 1):
        behaviour = "sustained decline"
        archetypes = ["decline / erosion"]
        indicators = {"slope_per_step": lin["slope"], "linear_r2": lin["r2"]}
        if exp and exp["r"] < 0 and "half_life" in exp:
            indicators["half_life"] = exp["half_life"]

    elif lin["r2"] >= 0.85:
        behaviour = "steady linear trend"
        archetypes = ["steady trend"]
        indicators = {"slope_per_step": lin["slope"], "linear_r2": lin["r2"]}

    else:
        behaviour = "irregular / oscillating"
        archetypes = ["no clean archetype signature"]
        indicators = {"sign_changes": feat["sign_changes"],
                      "linear_r2": lin["r2"]}

    best_model = max(fits.values(), key=lambda f: f.get("r2", 0))

    math_note = None
    if archetypes and archetypes[0] in ARCHETYPE_MATH:
        struct, eqn = ARCHETYPE_MATH[archetypes[0]]
        math_note = f"structure: {struct}; equation: {eqn}"

    return {
        "behaviour": behaviour,
        "archetypes": archetypes,
        "indicators": {k: round(v, 6) if isinstance(v, float) else v
                       for k, v in indicators.items()},
        "best_fit": {k: (round(v, 6) if isinstance(v, float) else v)
                     for k, v in best_model.items()},
        "all_r2": {name: round(f.get("r2", 0), 4) for name, f in fits.items()},
        "math": math_note,
        "caveat": "behavioural consistency, NOT proof of structure — different "
                  "feedback structures can produce similar curves; treat this as "
                  "a hypothesis to test against the mechanism, not a diagnosis",
    }


def classify_pair(series_a: Sequence[float], series_b: Sequence[float],
                  labels: Tuple[str, str] = ("A", "B")) -> Dict:
    """Two coupled series -> the two-actor archetypes.

    Success to the Successful (divergence: one pulls ahead, gap widens) vs
    Escalation (both accelerate together, arms-race).
    """
    a = [float(v) for v in series_a]
    b = [float(v) for v in series_b]
    n = min(len(a), len(b))
    if n < 3:
        return {"behaviour": "insufficient data", "n": n}
    a, b = a[:n], b[:n]
    both_up = a[-1] > a[0] and b[-1] > b[0]
    ta = fit_exponential(list(range(n)), a)
    tb = fit_exponential(list(range(n)), b)
    both_accel = bool(ta and tb and ta["r"] > 0 and tb["r"] > 0)

    # RATIO discipline: success-to-successful diverges in the SHARE one actor
    # holds (ratio moves away from its start); escalation keeps a roughly
    # constant ratio while both accelerate (matched growth, arms race).
    def _share(u, v):
        return u / (u + v) if (u + v) else 0.5
    share0, share1 = _share(a[0], b[0]), _share(a[-1], b[-1])
    # success-to-successful = DIVERGENCE from parity (a lead that compounds),
    # not mere movement. Two actors CONVERGING (gap closing toward 0.5) must
    # NOT be labelled winner-take-all.
    diverged_from_parity = abs(share1 - 0.5) - abs(share0 - 0.5)

    if diverged_from_parity > 0.1:
        arche = "success to the successful"
        behaviour = (f"share diverged from parity "
                     f"({share0:.2f} -> {share1:.2f}); one actor pulling ahead")
        struct = ("two reinforcing loops competing for a limited resource; an "
                  "early lead compounds into winner-take-all")
    elif both_up and both_accel:
        arche, behaviour = "escalation", "both actors accelerating at a matched rate"
        struct = ("two balancing loops coupled so each actor's gain threatens "
                  "the other, driving mutual escalation (arms race)")
    else:
        return {"behaviour": "no clean two-actor signature", "n": n,
                "share_start": round(share0, 4), "share_end": round(share1, 4)}
    return {"behaviour": behaviour, "archetype": arche, "structure": struct,
            "share_start": round(share0, 4), "share_end": round(share1, 4),
            "caveat": "behavioural consistency, not structural proof"}
