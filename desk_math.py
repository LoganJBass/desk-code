"""desk_math.py: the one copy of the options and risk math for Logan's AI trading desk.

Every convention here follows claude/data/risk-limits.md section 1 (the desk's rulebook). If the rulebook changes,
change it here once and every agent script that imports this module follows. Read-only math; no data, no holdings.
Decision support, not financial advice.

    import desk_math as dm
    dm.bs_put(S, K, T, sigma) -> (price, delta)
    dm.implied_vol(S, K, T, price, "P") -> sigma or None
    dm.stress_loss(S, K, contracts, beta) -> $ loss in a 20% x beta market drop (beta floored at 1.0)
"""
import math
import datetime as dt
from statistics import NormalDist

VERSION = "1.0.0 (rulebook v3, 2026-11-12)"

# ---- rulebook section 1 and 2 constants ----
RATE = 0.04            # risk-free rate for Black-Scholes
ERP = 0.05             # equity risk premium (sizing)
SHOCK = 0.20           # market shock
BETA_FLOOR = 1.0       # stress beta is floored at 1.0
BETA_ASSUMED = 1.3     # when no engine beta exists (label it "assumed"); still floored
GAP = 0.25             # single-name overnight gap
STRESS_CAP = 0.25      # all short puts, share of account value
GAP_CAP = 0.10         # each short put, share of account value
NAME_CAP = 0.10        # single-name put notional, share of account value
MARGIN_RESERVE = 0.40  # keep 40% of margin buying power unused after the shock
SHOCK_OPTION_PAD = 2.0 # option priced at intrinsic + 2 in the shocked-margin estimate

_N = NormalDist().cdf


# ---------------- Black-Scholes (no dividends) ----------------
def bs(S, K, T, sigma, right="P", r=RATE):
    """Price, delta and probability of finishing in the money. right: 'P' or 'C'. T in years."""
    T = max(T, 1e-4)
    d1 = (math.log(S / K) + (r + sigma * sigma / 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if right.upper().startswith("C"):
        return S * _N(d1) - K * math.exp(-r * T) * _N(d2), _N(d1), _N(d2)
    return K * math.exp(-r * T) * _N(-d2) - S * _N(-d1), _N(d1) - 1, _N(-d2)


def bs_put(S, K, T, sigma, r=RATE):
    p, d, _ = bs(S, K, T, sigma, "P", r)
    return p, d


def bs_call(S, K, T, sigma, r=RATE):
    p, d, _ = bs(S, K, T, sigma, "C", r)
    return p, d


def implied_vol(S, K, T, price, right="P", r=RATE, lo=0.01, hi=5.0, iters=200):
    """Bisection IV from an option price. None when the price is at or below intrinsic (no time value)."""
    intrinsic = max(0.0, (S - K) if right.upper().startswith("C") else (K - S))
    if price <= intrinsic + 1e-4:
        return None
    for _ in range(iters):
        m = (lo + hi) / 2
        lo, hi = (lo, m) if bs(S, K, T, m, right, r)[0] > price else (m, hi)
    return (lo + hi) / 2


def delta_from_mid(S, K, T, mid, right="P", r=RATE):
    """(delta, iv) implied from the bid-ask mid, the rulebook's delta convention. (None, None) if no time value."""
    v = implied_vol(S, K, T, mid, right, r)
    if v is None:
        return None, None
    return bs(S, K, T, v, right, r)[1], v


def years_to(expiry, today=None, min_days=0):
    """Year fraction from today (date or ISO string) to expiry (date or ISO string), calendar days / 365."""
    e = dt.date.fromisoformat(expiry) if isinstance(expiry, str) else expiry
    t = today or dt.date.today()
    t = dt.date.fromisoformat(t) if isinstance(t, str) else t
    return max((e - t).days, min_days) / 365


# ---------------- rulebook risk measures (per contract unless noted) ----------------
def stress_beta(beta=None):
    """Beta used in the stress test: engine beta, or 1.3 assumed, floored at 1.0."""
    return max(BETA_ASSUMED if beta is None else beta, BETA_FLOOR)


def shocked_price(S, beta=None):
    return S * (1 - stress_beta(beta) * SHOCK)


def stress_loss(S, K, contracts=1, beta=None):
    """100 x contracts x max(0, K - S x (1 - beta x 20%)), beta floored at 1.0."""
    return 100 * abs(contracts) * max(0.0, K - shocked_price(S, beta))


def gap_loss(S, K, contracts=1):
    """Loss in a 25% single-name gap."""
    return 100 * abs(contracts) * max(0.0, K - S * (1 - GAP))


def put_notional(K, contracts=1):
    return K * 100 * abs(contracts)


def naked_put_margin(S, K, option_price, contracts=1):
    """Fidelity-style estimate: 100 x n x (max(20% x S - OTM amount, 10% x K) + option price). Fidelity's ticket wins."""
    return 100 * abs(contracts) * (max(0.2 * S - max(0.0, S - K), 0.1 * K) + option_price)


def margin_after_shock(S, K, contracts=1, beta=None):
    Sp = shocked_price(S, beta)
    return naked_put_margin(Sp, K, max(0.0, K - Sp) + SHOCK_OPTION_PAD, contracts)


def usable_buying_power(buying_power, current_option_margin):
    """Buying power minus the 40% reserve: BP - 40% x (BP + current option margin)."""
    return buying_power - MARGIN_RESERVE * (buying_power + current_option_margin)


def put_caps(S, K, account_value, beta=None):
    """Largest contract counts a single short put may have under each per-name cap (on its own)."""
    s1, g1 = stress_loss(S, K, 1, beta), gap_loss(S, K, 1)
    return dict(stress_cap=int(STRESS_CAP * account_value // s1) if s1 else None,
                gap_cap=int(GAP_CAP * account_value // g1) if g1 else None,
                name_cap=int(NAME_CAP * account_value // put_notional(K)))


# ---------------- contract keys (trade journal Match column) ----------------
def contract_key(ticker):
    """OCC ticker 'ABBV 270115C00300000' -> 'ABBV 270115C300'; a plain symbol 'TMO' -> 'TMO stock'."""
    import re
    t = (ticker or "").strip().upper()
    m = re.match(r"^([A-Z.]+)\s+(\d{6})([CP])(\d{8})$", t)
    if not m:
        return f"{t} stock" if t else ""
    sym, ymd, right, k = m.groups()
    return f"{sym} {ymd}{right}{int(k) / 1000:g}"
