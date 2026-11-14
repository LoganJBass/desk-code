# desk-code

Shared code for Logan's AI trading desk: one copy of the options and risk math (`desk_math.py`) and the agents' calculation scripts (`agents/`), with fixed test cases so a change can't silently move the numbers.

**Public on purpose, so scheduled runs can clone it without signing in. It holds code only:** no holdings, positions, account data or personal numbers. `tools/check_public.py` must pass before every push, run with a deny list of held tickers built at publish time and kept outside this repo.

Decision support only, not financial advice. Nothing here can place, change or cancel an order.

## How an agent uses it

```
git clone --depth 1 https://github.com/LoganJBass/desk-code
python3 desk-code/agents/monitor_calc.py positions.json
```

If the clone fails, try once more, then fall back to the copy in the agent's own doc and say "desk-code unavailable, used the doc copy" in Data notes.

## What's here

| File | Used by | Notes |
|---|---|---|
| `desk_math.py` | everything below | Black-Scholes, implied vol and delta from the mid, stress loss (beta floored at 1.0), gap loss, put notional, naked-put margin now and after the shock, usable buying power, per-name caps, trade-journal contract keys. Constants come from the rulebook (`claude/data/risk-limits.md`, section 1) |
| `agents/monitor_calc.py` | Position Monitor, Refresh desk now | Built on `desk_math`. Fixes the doc copy, which used an engine beta below 1.0 without the rulebook's 1.0 floor |
| `agents/pm_calc.py` | Portfolio Manager | Verbatim from the agent doc; `tests/test_agents.py` checks its math matches `desk_math` |
| `agents/journal_fills.py` | Decision capture (trade journal) | Verbatim from the decision-capture doc |

Not here yet, and why: the Research Analyst, Red Team, Market Scout, Tax Agent, Idea Desk, Portfolio X-ray, Sentiment Watch and Desk health scripts move over next. `risk_engine.py` waits until its sector map, which lists held names, becomes an input instead of code.

## Changing the math

1. Change the rulebook first (Logan's call), then the constant or formula in `desk_math.py`.
2. Update the fixed values in `tests/test_desk_math.py`, with the reason in the commit message.
3. `python3 -m pytest -q tests` (or run each test file with python3), then `python3 tools/check_public.py --deny-file <private list>`, then push.

Version: see `desk_math.VERSION`.
