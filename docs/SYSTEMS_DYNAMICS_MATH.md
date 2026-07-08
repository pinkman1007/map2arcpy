# The math under the behaviour archetypes

*How map2arcpy grounds the classic systems-thinking archetypes (Limits to
Growth, Fixes that Fail, Shifting the Burden, Tragedy of the Commons,
Escalation, Success to the Successful, Eroding Goals) in numbers — the
`dynamics` module. Companion to ARCHETYPE_STUDY.md, which covers the map-type
archetypes. Those are themes; these are behaviours over time.*

## The core idea

A systems archetype is a **feedback-loop structure**, and every structure
produces a **characteristic trajectory** — a shape the stock traces over
time. Because your data is numbers over time (built-up area per year, carbon
per epoch, PERSIANN rainfall per year), we can do the honest thing: fit the
governing equations to the real series and report which archetype's signature
the numbers match, with the quantitative indicators the structure implies.

The pipeline is: **series → fit candidate models (least squares) → compare
fits → classify behaviour → name the consistent archetype + its equation +
its indicators → attach the identifiability caveat.**

All fitting is closed-form (no numpy, no optimiser): exponential and linear
are ordinary least squares; the logistic is a grid search over the carrying
capacity `K` with a closed-form linear fit on the logit at each `K`.

## The models

**Reinforcing growth** — one dominant reinforcing loop.
`dx/dt = r·x`  ⇒  `x(t) = x₀·eʳᵗ`.
Fit: OLS on `ln x` vs `t`. Indicators: growth rate `r`, doubling time
`ln2 / r`. Signature: accelerating, no plateau.

**Limits to Growth** — a reinforcing loop checked by a balancing loop (a
constraint/carrying capacity `K`).
`dx/dt = r·x·(1 − x/K)`  ⇒  `x(t) = K / (1 + A·e^(−rᵗ))` (logistic S-curve).
Fit: for each candidate `K`, the **logit** `y = ln(x/(K−x)) = −ln A + r·t` is
linear in `t`, so OLS gives `r` and `A` in closed form; grid-search `K` for
the best R². Indicators: carrying capacity `K`, growth rate `r`, inflection
time `t* = ln(A)/r`, **fraction of the limit already reached** `x_last/K`
(the number that says "how close to the ceiling"). Signature: S-curve
flattening toward `K`.

**Overshoot and Collapse** — Limits to Growth with a **delay** in the
limiting signal, or a carrying capacity that the stock itself erodes (the
Tragedy of the Commons). Signature: rise to an interior peak, then a material
decline. Detected structurally (interior maximum + fall-back below 92 % of
peak) rather than by a single closed form, because the delay makes the closed
form messy.

**Fixes that Fail / Shifting the Burden** — a symptomatic fix relieves a
*problem* metric (balancing loop) but a side-effect loop, acting with delay,
returns the problem worse. Signature (for a `kind="problem"` series):
down to an interior trough, then rebound past the baseline.

**Eroding Goals / Decline** — a balancing loop toward a goal whose reference
point itself drifts down, or simple depletion. `dx/dt = −k·(x − G)`, `G`
falling. Signature: sustained monotonic decline; we also report a half-life
if an exponential-decay fit holds.

**Steady trend** — a balancing loop tracking a moving goal, or slow drift.
`x = a + b·t`; reported when the linear fit dominates.

**Two-actor archetypes** (`classify_pair`):
- **Success to the Successful** — two reinforcing loops competing for a
  limited resource; an early lead compounds. Signature: one actor's **share**
  `a/(a+b)` moves decisively from its start (winner-take-all). Using the
  *share*, not the absolute gap, is deliberate — exponential growth widens
  absolute gaps even when neither actor is winning relatively.
- **Escalation** — two balancing loops coupled so each actor's gain threatens
  the other (arms race). Signature: both accelerate at a **matched** rate —
  the share stays roughly constant while both climb.

## How classification decides

Given the series, all applicable models are fit and their R² compared, then a
small decision procedure runs (peak/trough structure first, then S-curve vs
exponential vs linear vs decline). The winning behaviour names its archetype,
reports the fitted indicators, and prints the loop structure and equation from
`ARCHETYPE_MATH`. The full ordering is in `dynamics.classify`.

## The identifiability caveat (why every result says "consistent with")

**Matching a behaviour signature is evidence, not proof of structure.** This
is a real mathematical limitation, not modesty: distinct feedback structures
can produce near-identical curves over a short window (an S-curve early on
looks exponential; overshoot looks like growth until the peak). With ~10
annual points you cannot uniquely invert the trajectory to the mechanism.

So the tool reports a **hypothesis**: "the built-up series is *consistent
with* a Limits-to-Growth signature (logistic R²=0.998, ~95 % of estimated
carrying capacity reached)" — and never "this is Limits to Growth." The
number that matters most, `fraction_of_K_reached`, is itself conditional on
`K` being real, which only more data or domain knowledge can confirm. Treat
every diagnosis as a lens for asking better questions of the system, which is
exactly what systems thinking is for.

## Using it

```bash
# a stock over time -> which archetype?
map2arcpy dynamics "120,165,225,300,385,470,545,600,635,655,665"
#   -> "S-curve approaching a limit" / limits to growth
#      K≈699, r≈0.48, fraction_of_K≈0.95, logistic R²≈0.999

# a problem metric (down-then-up = a fix that failed)
map2arcpy dynamics "100,70,50,65,90,120" --kind problem

# two actors -> success-to-successful vs escalation
map2arcpy dynamics "10,22,40,70,120" --vs "10,12,14,16,18"

# label the epochs
map2arcpy dynamics "..." --times "2015,2016,2017,..."
```

Where do the numbers come from? From your maps. A generated script with the
systems layer detects a temporal series (years in the layer names — your
PERSIANN case) and tells you to compute the per-epoch metric (a zonal sum, a
class area, a mean) in ArcGIS Pro, then feed that short list of numbers to
`map2arcpy dynamics`. The spatial tool produces the numbers; this module reads
their behaviour. Stocks and flows, closed at last: the map is the stock, the
change between maps is the flow, and the trajectory of the stock is the
archetype.

## Scope and honesty (the register for this module)

- Fits are closed-form and robust but simple; no confidence intervals yet
  (R² is reported as the fit-quality signal).
- Logistic `K` search assumes the true `K` is within 4× the observed max —
  fine for a series that is visibly bending over, weak for early growth.
- Overshoot/fix-that-fails are detected by trajectory shape, not a fitted
  delay-differential model — a stronger version would fit the delay.
- Two-actor analysis is share/rate based; it does not fit the coupled ODE.
- Short series (< 4 points) get no logistic fit; < 3 get nothing.
- This is single-variable behaviour classification. It does NOT build a
  full stock-flow simulation of the coupled urban system — that (a runnable
  system-dynamics model behind the maps) is the natural next frontier.
