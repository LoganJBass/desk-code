"""pm_calc.py: Portfolio Manager numbers for Logan's AI trading desk.
python3 pm_calc.py pm_input.json  -> pm_out.json + printed summary
Budgets (stress, margin), a repair menu for every short put that breaks a cap, and a ranking of new put ideas
by premium per dollar of stress budget used. Read-only. Decision support, not financial advice."""
import json, sys, math, datetime as dt
from statistics import NormalDist
N = NormalDist().cdf; R = 0.04
STRESS_CAP, GAP_CAP, NAME_CAP, MARGIN_RESERVE, SHOCK, GAP = 0.25, 0.10, 0.10, 0.40, 0.20, 0.25

d = json.load(open(sys.argv[1])); TODAY = dt.date.fromisoformat(d["date"]); A = d["acct_value"]; BP = d["buying_power"]
EARN = {k: dt.date.fromisoformat(v) for k, v in d.get("earnings", {}).items()}

def bs(S, K, T, s):
    T = max(T, 1e-4); d1 = (math.log(S / K) + (R + s * s / 2) * T) / (s * math.sqrt(T)); d2 = d1 - s * math.sqrt(T)
    return K * math.exp(-R * T) * N(-d2) - S * N(-d1), N(d1) - 1
def delta(S, K, exp, mid):
    T = (dt.date.fromisoformat(exp) - TODAY).days / 365; lo, hi = 0.01, 5
    for _ in range(200):
        m = (lo + hi) / 2; lo, hi = (lo, m) if bs(S, K, T, m)[0] > mid else (m, hi)
    return round(bs(S, K, T, m)[1], 3), round(m, 3)
def stress1(S, K, beta):  # per contract, 20% market drop x max(beta, 1)
    return 100 * max(0, K - S * (1 - max(beta, 1.0) * SHOCK))
def gap1(S, K): return 100 * max(0, K - S * (1 - GAP))
def marg1(S, K, p): return 100 * (max(0.2 * S - max(0, S - K), 0.1 * K) + p)   # Fidelity-style naked put estimate
def marg_shock1(S, K, beta):
    Sp = S * (1 - max(beta, 1.0) * SHOCK); return marg1(Sp, K, max(0, K - Sp) + 2)
def spans_earn(sym, exp): e = EARN.get(sym); return bool(e and TODAY <= e <= dt.date.fromisoformat(exp))

puts = d["puts"]
for p in puts:
    n = abs(p["units"]); p["n"] = n
    p["delta"], p["iv"] = delta(p["S"], p["K"], p["exp"], p["mark"])
    p["stress"] = n * stress1(p["S"], p["K"], p["beta"]); p["gap"] = n * gap1(p["S"], p["K"])
    p["margin"] = n * marg1(p["S"], p["K"], p["mark"]); p["margin_shock"] = n * marg_shock1(p["S"], p["K"], p["beta"])
    p["notional_pct"] = p["K"] * 100 * n / A; p["pnl"] = (p["cost"] - p["mark"]) * 100 * n
    p["pct_max"] = (p["cost"] - p["mark"]) / p["cost"]
tot_stress = sum(p["stress"] for p in puts); tot_margin = sum(p["margin"] for p in puts)
tot_mshock = sum(p["margin_shock"] for p in puts)
budget = dict(stress_now_pct=tot_stress / A, stress_room=STRESS_CAP * A - tot_stress,
              margin_now=tot_margin, margin_after_shock=tot_mshock, buying_power=BP,
              usable_bp=BP - MARGIN_RESERVE * (BP + tot_margin))  # keep 40% of total margin capacity unused

# ---------- repair menu for puts that break a cap ----------
def caps_for(p, K=None, S=None):
    K = K or p["K"]; S = S or p["S"]          # caps for this put on its own; the book-level stress total is reported separately
    s1, g1 = stress1(S, K, p["beta"]), gap1(S, K)
    return dict(stress_cap=int(STRESS_CAP * A // s1) if s1 else 99,
                gap_cap=int(GAP_CAP * A // g1) if g1 else 99, name_cap=int(NAME_CAP * A // (K * 100)))
repairs = {}
for p in puts:
    c = caps_for(p); nmax = min(c["stress_cap"], c["gap_cap"])   # loss caps; the 10% notional cap is shown beside it
    broken = p["n"] > min(c.values()) or p["delta"] < -0.30
    if not broken: continue
    others = tot_stress - p["stress"]; close_cost = p["mark"] * 100; menu = []
    def row(name, n_keep, K, exp, credit_per, debit_now, extra=""):
        s = n_keep * stress1(p["S"], K, p["beta"]) if K else 0
        menu.append(dict(choice=name, contracts=n_keep, strike=K, exp=exp, cash_now=round(debit_now),
                         realized=round((p["cost"] * 100 * (p["n"] - n_keep)) - close_cost * (p["n"] - n_keep)) if n_keep < p["n"] else 0,
                         book_stress_pct=round((others + s) / A, 3), note=extra))
    row("Hold all", p["n"], p["K"], p["exp"], 0, 0, f"delta {p['delta']}; gap loss {p['gap']/A:.0%} of acct")
    menu.append(dict(choice="Close all", contracts=0, cash_now=round(-close_cost * p["n"]),
                     realized=round(p["pnl"]), book_stress_pct=round(others / A, 3), note=""))
    if nmax < p["n"]: row(f"Reduce to {nmax}", nmax, p["K"], p["exp"], 0, -close_cost * (p["n"] - nmax), f"largest size inside the stress and gap caps; 10% notional cap allows {c['name_cap']}")
    for r in d.get("repair_candidates", {}).get(p["sym"], {}).get("rolls", []):
        dl, _ = delta(p["S"], r["K"], r["exp"], r["mid"]); cr = (r["mid"] - p["mark"]) * 100
        cc = caps_for(p, K=r["K"]); nr = min(cc["stress_cap"], cc["gap_cap"]); flag = " SPANS EARNINGS" if spans_earn(p["sym"], r["exp"]) else ""
        for n_keep in sorted({p["n"], nr}):
            if n_keep == 0: continue
            cash = cr * n_keep - close_cost * (p["n"] - n_keep)
            menu.append(dict(choice=f"Roll {n_keep} to {r['exp']} {r['K']:.0f}P", contracts=n_keep, strike=r["K"], exp=r["exp"],
                             cash_now=round(cash), realized=round(p["pnl"]),
                             book_stress_pct=round((others + n_keep * stress1(p["S"], r["K"], p["beta"])) / A, 3),
                             note=f"new delta {dl}; net {'credit' if cr >= 0 else 'debit'} {abs(cr):.0f}/ct; caps {cc}{flag}"))
    for h in d.get("repair_candidates", {}).get(p["sym"], {}).get("hedges", []):
        w = p["K"] - h["K"]; cost = h["mid"] * 100 * p["n"]
        ml = (w - (p["mark"] - h["mid"])) * 100       # worst-case further loss per spread from today's marks
        s_sp = p["n"] * min(stress1(p["S"], p["K"], p["beta"]) - stress1(p["S"], h["K"], p["beta"]), w * 100)
        menu.append(dict(choice=f"Buy {p['n']} {h['exp']} {h['K']:.0f}P (make it a {p['K']:.0f}/{h['K']:.0f} spread)", contracts=p["n"],
                         cash_now=round(-cost), realized=0, book_stress_pct=round((others + s_sp) / A, 3),
                         note=f"worst case from today {ml*p['n']/A:.0%} of acct; margin becomes the width, {w*100*p['n']/A:.0%} of acct, and no longer grows in a crash"))
    repairs[p["sym"]] = dict(caps=c, max_contracts=nmax, menu=menu)

# ---------- new ideas: rank by premium per $ of stress budget ----------
ideas = []
for i in d.get("ideas", []):
    s1 = stress1(i["S"], i["K"], i["beta"]); m1 = marg1(i["S"], i["K"], i["mid"])
    dte = (dt.date.fromisoformat(i["exp"]) - TODAY).days
    ideas.append(dict(i, stress_per=round(s1), margin_per=round(m1), credit=round(i["mid"] * 100),
                      prem_per_stress=round(i["mid"] * 100 / s1, 4) if s1 else None,
                      rom_ann=round(i["mid"] * 100 / m1 * 365 / dte, 3), name_cap=int(NAME_CAP * A // (i["K"] * 100)),
                      fits_now=bool(budget["stress_room"] >= s1 and budget["usable_bp"] >= m1)))
ideas.sort(key=lambda x: -(x["prem_per_stress"] or 0))
out = dict(date=d["date"], budget=budget, puts=puts, repairs=repairs, ideas=ideas)
json.dump(out, open("pm_out.json", "w"), indent=1, default=str)

print(f"stress {budget['stress_now_pct']:.1%} of acct (cap 25%); room {budget['stress_room']/A:+.1%} | margin now {tot_margin/A:.0%} "
      f"after shock {tot_mshock/A:.0%} of acct | buying power {BP/A:.0%} of acct; usable after 40% reserve {budget['usable_bp']/A:+.0%}")
for p in puts:
    print(f"{p['sym']} {p['K']}P {p['exp']} x{p['n']}: S {p['S']} delta {p['delta']} mark {p['mark']} vs {p['cost']} ({p['pct_max']:+.0%} of max) "
          f"notional {p['notional_pct']:.0%} stress {p['stress']/A:.0%} gap {p['gap']/A:.0%} margin {p['margin']/A:.0%} -> {p['margin_shock']/A:.0%}")
for s, r in repairs.items():
    print(f"\nREPAIR {s}: caps {r['caps']}")
    for m in r["menu"]: print("  ", m)
print("\nIDEAS"); [print("  ", i) for i in ideas]
