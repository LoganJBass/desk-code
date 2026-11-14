"""journal_fills.py: match SnapTrade fills to desk decisions for Logan's trade journal.
python3 journal_fills.py journal_input.json  -> journal_out.json + printed summary
Read-only bookkeeping. Decision support, not financial advice.

journal_input.json:
{
 "known_refs": ["4fdaceaa", ...],          # Ref column of the journal's Fills table (first 8 chars of the activity id)
 "decisions": [                            # every decision row that has a Match key and isn't Closed / Passed / Superseded
   {"id": "D13", "date": "2026-11-13", "match": ["ABBV 270115C300", "ABBV 270115C320"], "status": "Approved"},
   {"id": "D14", "date": "2026-11-13", "match": ["TMO stock"], "status": "Open"}
 ],
 "activities": [                           # SnapTrade getAccountActivities rows, Individual account, copied field by field
   {"id": "...", "trade_date": "2026-11-12", "type": "SELL", "option_type": "SELL_TO_CLOSE",
    "ticker": "XYZ 261224C00200000", "units": -10, "price": 2.50, "fee": 6.50, "amount": 2493.50}
 ]
}
For a stock row, ticker is the stock symbol (symbol.symbol). For an option row, ticker is option_symbol.ticker.
Cash rows (FCASH, JOURNALED, INTEREST, DIVIDEND, CONTRIBUTION, WITHDRAWAL, FEE, TAX, TRANSFER) are skipped.
"""
import json, re, sys

TRADE_TYPES = {"BUY", "SELL", "OPTIONEXPIRATION", "OPTIONASSIGNMENT", "OPTIONEXERCISE"}
OCC = re.compile(r"^([A-Z.]+)\s+(\d{6})([CP])(\d{8})$")


def key_of(ticker):
    """'ABBV 270115C00300000' -> 'ABBV 270115C300'; 'TMO' -> 'TMO stock'."""
    t = (ticker or "").strip().upper()
    m = OCC.match(t)
    if not m:
        return f"{t} stock" if t else ""
    sym, ymd, right, k = m.groups()
    strike = int(k) / 1000
    s = f"{strike:g}"
    return f"{sym} {ymd}{right}{s}"


def action_of(a):
    ot = (a.get("option_type") or "").upper()
    if ot in {"BUY_TO_OPEN", "SELL_TO_OPEN", "BUY_TO_CLOSE", "SELL_TO_CLOSE"}:
        return ot.replace("_", " ").lower()
    t = a["type"].upper()
    if t == "OPTIONEXPIRATION":
        return "expired"
    if t == "OPTIONASSIGNMENT":
        return "assigned"
    if t == "OPTIONEXERCISE":
        return "exercised"
    return "buy" if t == "BUY" else "sell"


def main(path):
    d = json.load(open(path))
    known = set(d.get("known_refs", []))
    decisions = d.get("decisions", [])
    new_fills, skipped_dupes = [], 0
    for a in sorted(d.get("activities", []), key=lambda x: (x["trade_date"], x["id"])):
        if a["type"].upper() not in TRADE_TYPES:
            continue
        if (a.get("ticker") or "").upper() in {"FCASH", "SPAXX", "FDRXX", "CORE"}:
            continue
        ref = a["id"][:8]
        if ref in known:
            skipped_dupes += 1
            continue
        k = key_of(a.get("ticker"))
        act = action_of(a)
        # match: same contract key, trade date on or after the decision date; earliest open decision wins
        cands = [x for x in decisions if k in x.get("match", []) and a["trade_date"] >= x["date"]]
        # decisions still waiting on a trade come first (Open, Approved, Edited, Filled); held/answered rows are a fallback
        active = {"open", "approved", "edited", "filled"}
        cands.sort(key=lambda x: (x.get("status", "open").lower() not in active, x["date"]))
        matched = cands[0]["id"] if cands else ""
        new_fills.append(dict(ref=ref, trade_date=a["trade_date"], key=k, action=act,
                              qty=abs(a.get("units") or 0), price=a.get("price") or 0,
                              fee=a.get("fee") or 0, amount=round(a.get("amount") or 0, 2),
                              matched=matched or "own trade"))
        known.add(ref)

    # per decision: net position from matched fills (new ones plus any the caller passed as prior_fills)
    prior = d.get("prior_fills", [])          # optional: earlier matched fills [{matched, key, action, qty, amount}]
    per = {}
    for f in prior + new_fills:
        if not f["matched"] or f["matched"] == "own trade":
            continue
        p = per.setdefault(f["matched"], {"legs": {}, "cash": 0.0, "fills": 0})
        sign = -1 if f["action"] in {"sell to open", "sell to close", "sell", "assigned"} else 1
        if f["action"] == "expired":
            sign = 0
        leg = p["legs"].setdefault(f["key"], {"net": 0, "opened": False})
        leg["net"] += sign * f["qty"] if f["action"] != "expired" else 0
        if f["action"] in {"buy to open", "sell to open", "buy"}:
            leg["opened"] = True
        if f["action"] == "expired":
            leg["net"] = 0
            leg["expired"] = True
        p["cash"] += f["amount"]
        p["fills"] += 1
    summary = {}
    for did, p in per.items():
        opened = any(l["opened"] for l in p["legs"].values())
        flat = all(l["net"] == 0 for l in p["legs"].values())
        if opened and flat:
            state = "Closed"          # opened and closed inside the journal: cash is the realized result
        elif opened:
            state = "Filled"          # position open
        else:
            state = "Filled (closing)"  # a close/roll of an older position: result needs the original premium
        summary[did] = dict(state=state, net_cash=round(p["cash"], 2), fills=p["fills"],
                            legs={k: v["net"] for k, v in p["legs"].items()})
    out = dict(new_fills=new_fills, skipped_dupes=skipped_dupes, decisions=summary)
    json.dump(out, open("journal_out.json", "w"), indent=1)
    print(f"new fills {len(new_fills)} (dupes skipped {skipped_dupes})")
    for f in new_fills:
        print(f"  {f['trade_date']} {f['ref']} {f['key']} {f['action']} x{f['qty']:g} @ {f['price']} fee {f['fee']} "
              f"cash {f['amount']:+,.2f} -> {f['matched']}")
    for did, s in summary.items():
        print(f"  {did}: {s['state']} · net cash {s['net_cash']:+,.2f} · legs {s['legs']}")


if __name__ == "__main__":
    main(sys.argv[1])
