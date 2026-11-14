"""Fixed test cases for desk_math. A change that moves any of these numbers fails here before it reaches an agent.
Run: python3 -m pytest -q tests   (or python3 tests/test_desk_math.py)"""
import os, sys, math
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import desk_math as dm

def close(a, b, tol=1e-6):
    return abs(a - b) <= tol * max(1.0, abs(b))

# ---- golden values (synthetic contracts; computed once with desk_math 1.0.0 and checked against put-call parity) ----
def test_black_scholes_put():
    p, d = dm.bs_put(100, 90, 30 / 365, 0.30)
    assert close(p, 0.400558, 1e-5), p          # checked against an erfc-based formula
    assert close(d, -0.095734, 1e-5), d

def test_put_call_parity():
    S, K, T, v = 250, 240, 45 / 365, 0.42
    c, _ = dm.bs_call(S, K, T, v); p, _ = dm.bs_put(S, K, T, v)
    assert close(c - p, S - K * math.exp(-dm.RATE * T), 1e-9)

def test_implied_vol_roundtrip():
    for right in ("P", "C"):
        for v in (0.15, 0.45, 1.2):
            price = dm.bs(180, 160 if right == "P" else 200, 40 / 365, v, right)[0]
            got = dm.implied_vol(180, 160 if right == "P" else 200, 40 / 365, price, right)
            assert close(got, v, 1e-4), (right, v, got)

def test_implied_vol_no_time_value():
    assert dm.implied_vol(80, 100, 0.1, 19.99, "P") is None      # below intrinsic
    assert dm.delta_from_mid(80, 100, 0.1, 19.99, "P") == (None, None)

def test_stress_beta_floor_and_assumed():
    assert dm.stress_beta(0.6) == 1.0
    assert dm.stress_beta(1.4) == 1.4
    assert dm.stress_beta(None) == 1.3

def test_stress_and_gap():
    # 750P on an 800 stock, beta 1.2: shocked price 800 x (1 - 0.24) = 608 -> 142 x 100 per contract
    assert close(dm.stress_loss(800, 750, 1, 1.2), 14200)
    assert close(dm.stress_loss(800, 750, -12, 1.2), 170400)          # sign of contracts ignored
    assert close(dm.stress_loss(800, 750, 1, 0.5), dm.stress_loss(800, 750, 1, 1.0))   # floor
    assert close(dm.gap_loss(800, 750), 15000)                        # 750 - 600
    assert dm.stress_loss(100, 50, 1, 1.0) == 0                       # far OTM

def test_margin():
    # S 100, K 90, price 1: max(20 - 10, 9) + 1 = 11 -> 1100
    assert close(dm.naked_put_margin(100, 90, 1.0), 1100)
    # shocked (beta 1): S 80, option 10 + 2 = 12; max(16 - 0, 9) + 12 = 28 -> 2800
    assert close(dm.margin_after_shock(100, 90, 1, 1.0), 2800)
    assert close(dm.usable_buying_power(100000, 50000), 100000 - 0.4 * 150000)

def test_put_caps():
    caps = dm.put_caps(800, 750, 400000, beta=1.2)
    assert caps == dict(stress_cap=7, gap_cap=2, name_cap=0), caps

def test_contract_key():
    assert dm.contract_key("ABBV 270115C00300000") == "ABBV 270115C300"
    assert dm.contract_key("FIS 270115P00027500") == "FIS 270115P27.5"
    assert dm.contract_key("tmo") == "TMO stock"
    assert dm.contract_key("") == ""

if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f(); print("ok", k)
