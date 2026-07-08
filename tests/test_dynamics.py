"""System-dynamics behaviour classifier (v0.12.0) — the math foundation."""
import math

from map2arcpy import dynamics
from map2arcpy.cli import main


def test_ols_recovers_a_line():
    slope, intercept, r2 = dynamics.ols([0, 1, 2, 3], [1, 3, 5, 7])
    assert abs(slope - 2) < 1e-9 and abs(intercept - 1) < 1e-9 and r2 > 0.999


def test_exponential_fit_and_doubling_time():
    t = list(range(8))
    x = [100 * math.exp(0.3 * ti) for ti in t]
    f = dynamics.fit_exponential(t, x)
    assert abs(f["r"] - 0.3) < 1e-6
    assert abs(f["doubling_time"] - math.log(2) / 0.3) < 1e-6
    assert f["r2"] > 0.999


def test_logistic_fit_recovers_carrying_capacity():
    K, r, A = 1000.0, 0.6, 50.0
    t = list(range(20))
    x = [K / (1 + A * math.exp(-r * ti)) for ti in t]
    f = dynamics.fit_logistic(t, x)
    assert f is not None
    assert abs(f["K"] - K) / K < 0.05                # within 5%
    assert f["r2"] > 0.99


def test_classify_limits_to_growth():
    K, r, A = 1000.0, 0.7, 40.0
    x = [K / (1 + A * math.exp(-r * ti)) for ti in range(18)]
    res = dynamics.classify(x)
    assert res["behaviour"] == "S-curve approaching a limit"
    assert "limits to growth" in res["archetypes"]
    assert res["indicators"]["fraction_of_K_reached"] > 0.9
    assert "logistic" in res["math"].lower() or "K)" in res["math"]


def test_classify_reinforcing_growth():
    x = [100 * math.exp(0.25 * ti) for ti in range(8)]     # no plateau yet
    res = dynamics.classify(x)
    assert res["behaviour"] == "accelerating (near-exponential) growth"
    assert "reinforcing growth" in res["archetypes"]
    assert "doubling_time" in res["indicators"]


def test_classify_overshoot_and_collapse():
    x = [10, 40, 90, 150, 180, 160, 110, 60, 30]           # peak then fall
    res = dynamics.classify(x)
    assert res["behaviour"] == "overshoot then decline"
    assert "overshoot and collapse" in res["archetypes"]


def test_classify_fix_that_fails_problem_metric():
    # a problem that dips after a "fix" then rebounds worse
    x = [100, 70, 50, 65, 90, 120]
    res = dynamics.classify(x, kind="problem")
    assert res["behaviour"] == "improved then worsened past baseline"
    assert "recovery / rebound" in res["archetypes"]


def test_classify_decline():
    x = [500, 430, 380, 330, 290, 250]
    res = dynamics.classify(x)
    assert res["behaviour"] == "sustained decline"
    assert "decline / erosion" in res["archetypes"]


def test_caveat_always_present():
    res = dynamics.classify([1, 2, 4, 8, 16])
    assert "not proof" in res["caveat"].lower() or "not structural" in res["caveat"].lower()


def test_pair_success_to_successful():
    a = [10, 22, 40, 70, 120, 200]
    b = [10, 12, 14, 16, 18, 20]
    res = dynamics.classify_pair(a, b, ("winner", "loser"))
    assert res["archetype"] == "success to the successful"


def test_pair_escalation():
    a = [10 * math.exp(0.3 * i) for i in range(6)]
    b = [11 * math.exp(0.29 * i) for i in range(6)]
    res = dynamics.classify_pair(a, b)
    assert res["archetype"] == "escalation"


def test_insufficient_data():
    assert dynamics.classify([1, 2])["behaviour"] == "insufficient data"


def test_cli_dynamics_stock(capsys):
    import json
    rc = main(["dynamics", "40,90,150,180,160,110,60"])
    assert rc == 0
    res = json.loads(capsys.readouterr().out)
    assert res["behaviour"] == "overshoot then decline"


def test_cli_dynamics_pair(capsys):
    import json
    rc = main(["dynamics", "10,22,40,70,120", "--vs", "10,12,14,16,18"])
    assert rc == 0
    res = json.loads(capsys.readouterr().out)
    assert res["archetype"] == "success to the successful"
