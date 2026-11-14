"""Agent scripts against desk_math, on synthetic positions only (never real holdings: this repo is public).
1. Conformance: functions an agent script still defines for itself (copied from its doc) must agree with desk_math.
2. monitor_calc: fixed case, including the beta floor.
3. journal_fills: matching, de-duplication and round-trip results.
Run: python3 -m pytest -q tests   (or python3 tests/test_agents.py)"""
import ast, json, math, os, subprocess, sys, tempfile, datetime as dt
from statistics import NormalDist
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
import desk_math as dm

def load_functions(path, names, extra_globals):
    """Pull only the named top-level defs out of a script (scripts run work at import time, so no import)."""
    tree = ast.parse(open(path).read())
    mod = ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names], type_ignores=[])
    g = dict(math=math, dt=dt, N=NormalDist().cdf, R=dm.RATE, **extra_globals)
    exec(compile(mod, path, "exec"), g)
    return g

CASES = [(800, 750, 1.2, 28.65), (100, 90, 0.6, 1.10), (55, 60, 1.0, 6.20), (300, 240, 2.1, 0.85)]

def test_pm_calc_conforms():
    g = load_functions(os.path.join(ROOT, "agents", "pm_calc.py"), {"bs", "stress1", "gap1", "marg1", "marg_shock1"},
                       dict(SHOCK=dm.SHOCK, GAP=dm.GAP))
    for S, K, beta, mark in CASES:
        assert math.isclose(g["stress1"](S, K, beta), dm.stress_loss(S, K, 1, beta)), (S, K, beta)
        assert math.isclose(g["gap1"](S, K), dm.gap_loss(S, K))
        assert math.isclose(g["marg1"](S, K, mark), dm.naked_put_margin(S, K, mark))
        assert math.isclose(g["marg_shock1"](S, K, beta), dm.margin_after_shock(S, K, 1, beta))
        p1, d1 = g["bs"](S, K, 0.1, 0.4); p2, d2 = dm.bs_put(S, K, 0.1, 0.4)
        assert math.isclose(p1, p2) and math.isclose(d1, d2)

def run_script(script, payload, *extra):
    with tempfile.TemporaryDirectory() as tmp:
        f = os.path.join(tmp, "in.json"); json.dump(payload, open(f, "w"))
        r = subprocess.run([sys.executable, os.path.join(ROOT, "agents", script), f, *extra], cwd=tmp,
                           capture_output=True, text=True, check=True)
        out_file = os.path.join(tmp, "journal_out.json")
        return r.stdout, (json.load(open(out_file)) if os.path.exists(out_file) else None)

def test_monitor_calc_fixed_case():
    payload = {"date": "2026-01-05", "acct_value": 500000, "buying_power": 100000,
               "options": [{"sym": "AAA", "type": "P", "K": 90, "exp": "2026-02-06", "units": -5, "mark": 1.0, "cost": 2.0},
                           {"sym": "BBB", "type": "C", "K": 60, "exp": "2026-02-06", "units": -1, "mark": 0.5, "cost": 1.0}],
               "underlying": {"AAA": 100, "BBB": 55}, "beta": {"AAA": 0.6}}
    out = json.loads(run_script("monitor_calc.py", payload)[0])
    put = out["options"][0]
    assert put["beta_used"] == 1.0 and put["beta_assumed"] is False          # 0.6 floored to 1.0 (rulebook)
    assert out["stress_loss"] == round(dm.stress_loss(100, 90, 5, 1.0)) == 5000
    assert put["notional_pct"] == 0.09 and out["stress_pct"] == 0.01
    assert out["margin_now"] == round(dm.naked_put_margin(100, 90, 1.0, 5))
    assert -0.2 < put["delta"] < 0 and put["pct_max"] == 0.5
    assert "stress_loss" not in out["options"][1]                            # calls don't add put stress

def test_journal_fills_synthetic():
    base = {"known_refs": [],
            "decisions": [{"id": "D1", "date": "2026-01-05", "match": ["AAA 260206P90"], "status": "Held"},
                          {"id": "D2", "date": "2026-01-06", "match": ["AAA 260206P90"], "status": "Open"},
                          {"id": "D3", "date": "2026-01-06", "match": ["BBB 260320C50", "BBB 260320C60"], "status": "Approved"}],
            "activities": [
                {"id": "aaaa0001-x", "trade_date": "2026-01-05", "type": "SELL", "option_type": "SELL_TO_OPEN", "ticker": "AAA 260206P00090000", "units": -2, "price": 3.0, "fee": 1, "amount": 599},
                {"id": "aaaa0002-x", "trade_date": "2026-01-07", "type": "BUY", "option_type": "BUY_TO_CLOSE", "ticker": "AAA 260206P00090000", "units": 5, "price": 0.8, "fee": 3, "amount": -403},
                {"id": "bbbb0001-x", "trade_date": "2026-01-07", "type": "BUY", "option_type": "BUY_TO_OPEN", "ticker": "BBB 260320C00050000", "units": 2, "price": 6.0, "fee": 1, "amount": -1201},
                {"id": "bbbb0002-x", "trade_date": "2026-01-07", "type": "SELL", "option_type": "SELL_TO_OPEN", "ticker": "BBB 260320C00060000", "units": -2, "price": 2.0, "fee": 1, "amount": 399},
                {"id": "bbbb0003-x", "trade_date": "2026-02-02", "type": "SELL", "option_type": "SELL_TO_CLOSE", "ticker": "BBB 260320C00050000", "units": -2, "price": 9.0, "fee": 1, "amount": 1799},
                {"id": "bbbb0004-x", "trade_date": "2026-02-02", "type": "BUY", "option_type": "BUY_TO_CLOSE", "ticker": "BBB 260320C00060000", "units": 2, "price": 3.0, "fee": 1, "amount": -601},
                {"id": "cccc0001-x", "trade_date": "2026-01-08", "type": "BUY", "option_type": "", "ticker": "CCC", "units": 10, "price": 50, "fee": 0, "amount": -500},
                {"id": "dddd0001-x", "trade_date": "2026-01-08", "type": "JOURNALED", "option_type": "", "ticker": "", "units": 0, "price": 0, "fee": 0, "amount": 10}]}
    _, out = run_script("journal_fills.py", base)
    by_ref = {f["ref"]: f["matched"] for f in out["new_fills"]}
    assert by_ref["aaaa0001"] == "D1"            # before D2 existed: falls back to the held decision
    assert by_ref["aaaa0002"] == "D2"            # the open "close it" decision wins over the held one
    assert by_ref["cccc0001"] == "own trade"
    assert "dddd0001" not in by_ref              # cash/journal rows skipped
    assert out["decisions"]["D3"]["state"] == "Closed" and math.isclose(out["decisions"]["D3"]["net_cash"], 396)
    assert out["decisions"]["D2"]["state"] == "Filled (closing)"
    base["known_refs"] = list(by_ref)            # second run: everything already recorded
    _, again = run_script("journal_fills.py", base)
    assert again["new_fills"] == [] and again["skipped_dupes"] == len(by_ref)

if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f(); print("ok", k)
