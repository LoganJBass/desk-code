# monitor_calc.py  — python3 agents/monitor_calc.py positions.json   (Position Monitor, Logan's AI trading desk)
# positions.json: {"date":"YYYY-MM-DD","acct_value":x,"buying_power":x,
#   "options":[{"sym","type":"P|C","K","exp","units","mark","cost","iv"(optional),"delta"(optional)}],
#   "underlying":{"SYM":price}, "beta":{"SYM":b}}
# Library version: same output as the doc copy, with the stress beta floored at 1.0 (rulebook section 1).
# The doc copy used an engine beta below 1.0 as-is, which understated stress loss for low-beta names.
import json, os, sys, datetime as dt
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import desk_math as dm


def run(d):
    today = dt.date.fromisoformat(d["date"]); A = d["acct_value"]
    out = []; stress = 0; m_now = 0; m_shock = 0; notional = 0
    for o in d["options"]:
        S = d["underlying"][o["sym"]]; days = (dt.date.fromisoformat(o["exp"]) - today).days; T = max(days, 1) / 365
        src = "cboe" if o.get("iv") else "implied"
        v = o.get("iv") or dm.implied_vol(S, o["K"], T, o["mark"], o["type"])
        if v is None:                       # no time value left: delta is ~0 (OTM) or ~1 (ITM)
            itm = (S < o["K"]) if o["type"] == "P" else (S > o["K"])
            v = 0.0; delta = (-1.0 if o["type"] == "P" else 1.0) if itm else 0.0
        else:
            delta = o.get("delta") if o.get("delta") is not None else dm.bs(S, o["K"], T, v, o["type"])[1]
        short = o["units"] < 0; n = abs(o["units"])
        pnl = (o["cost"] - o["mark"]) * 100 * n * (1 if short else -1)
        r = dict(o, S=S, dte=days, iv=round(v, 3), delta=round(delta, 3), greeks=src, pnl=round(pnl),
                 pct_max=round((o["cost"] - o["mark"]) / o["cost"], 3) if short else None,
                 cushion=round((S - o["K"]) / S if o["type"] == "P" else (o["K"] - S) / S, 3))
        if short and o["type"] == "P":
            b_in = d.get("beta", {}).get(o["sym"])
            r["beta_used"] = dm.stress_beta(b_in); r["beta_assumed"] = b_in is None
            r["notional"] = dm.put_notional(o["K"], n); r["notional_pct"] = round(r["notional"] / A, 3); notional += r["notional"]
            r["stress_loss"] = round(dm.stress_loss(S, o["K"], n, b_in)); stress += r["stress_loss"]
            m_now += dm.naked_put_margin(S, o["K"], o["mark"], n); m_shock += dm.margin_after_shock(S, o["K"], n, b_in)
        out.append(r)
    return dict(options=out, put_notional=notional, put_notional_x_acct=round(notional / A, 2),
                stress_loss=stress, stress_pct=round(stress / A, 3), margin_now=round(m_now), margin_after_shock=round(m_shock),
                buying_power=d["buying_power"], lib=dm.VERSION)


if __name__ == "__main__":
    print(json.dumps(run(json.load(open(sys.argv[1]))), indent=1))
