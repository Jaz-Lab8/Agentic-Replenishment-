# Replenishment Copilot — Agentic Demand Planning Prototype

## 1. The reimagined workflow

**Today (human loop):**
Planner opens spreadsheet → pulls last week's sales from ERP screen → eyeballs
a trend line per SKU → manually calculates "does this look low?" → keys a
purchase suggestion into the legacy ERP → repeats for hundreds of SKUs →
long-tail SKUs get skipped because there's no time → tribal knowledge lives
in one planner's head.

**Agentic version — Sense → Decide → Draft → Escalate:**

| Stage | What the agent does | What a human never has to do again |
|---|---|---|
| **Sense** | Pulls weekly sales + inventory per SKU, detects stockouts (censored demand), lead-time changes, and velocity breaks (spike/decline/seasonal) | Manually scanning every SKU's trend line every week |
| **Decide** | Corrects demand estimates for stockout censoring, computes lead-time-aware reorder point + safety stock, respects MOQ, scores confidence | Doing the reorder-point math by hand, especially under a lead-time change |
| **Draft** | Turns the number into a plain-language PO recommendation with a full reasoning trace attached | Reconstructing "why" after the fact from memory |
| **Escalate / Act** | Auto-approves only small, high-confidence, low-risk orders. Everything else — spikes, long-tail SKUs, lead-time changes, high dollar value — is queued for a human with the reasons up front | Deciding *from scratch* which SKUs even deserve attention this week |

**Where the human stays in the loop, and why:**
- **Long-tail SKUs** (thin, noisy history) — the agent can be confidently wrong here, so it always escalates rather than auto-committing cash to slow-moving inventory.
- **Demand spikes** — the agent flags "is this a fluke or the new normal?" but a planner usually has context (a TikTok mention, a competitor stockout) the data doesn't carry.
- **Supplier lead-time changes** — these are business-relationship facts, not statistical patterns; a human should confirm before committing budget against unconfirmed new terms.
- **High dollar-value orders** — anything above a cost ceiling always gets a sign-off, regardless of confidence, because the blast radius of being wrong is bigger.
- **Auto-approvals are reversible** — even "auto-approved" orders sit in a visible tab a planner can pull back into review. Nothing is silently irreversible.

This preserves the planner's judgment exactly where judgment earns its keep, and removes it exactly where it was previously just tedious arithmetic.

## 2. The prototype

- `generate_data.py` — synthesizes 20 weeks of sales + inventory history across 8 SKUs spanning fast movers, medium movers, a seasonal item, and two long-tail SKUs. It deliberately injects:
  - **Demand spike**: Running Shoe (SKU-1002) gets a 2.8x demand jump in the last 3 weeks (viral moment).
  - **Supplier lead-time change**: Yoga Mat (SKU-1005) lead time jumps from 28→56 days in the final week (supplier delay notice).
  - **Stockouts that censor true demand**: several SKUs run out of stock mid-week, which would understate naive averages if not corrected.
  - **Long-tail noise**: Ceramic Mug and Enamel Pin Set have thin, volatile weekly demand (~2-6 units/week).
- `agent_engine.py` — the actual sense/decide/draft/act pipeline (see code — each stage is a separate, inspectable function, not one LLM prompt).
- `app.py` — Streamlit cockpit implementing the trust & control layer (below).

Run it: `streamlit run app.py` (needs `pip install streamlit pandas numpy`).

## 3. Trust & control layer

- **Reasoning trace, not a black box**: every recommendation carries the literal chain of facts and formulas that produced it (e.g. "stocked out 2/4 recent weeks → correcting forecast from 45/wk to 63/wk → reorder point covers 4.3 weeks lead time + safety stock → gap rounded to MOQ"). This is deterministic, arithmetic reasoning — legible and checkable by a planner with a calculator, not "trust the model."
- **Confidence scoring surfaced up front** (🟢high/🟡medium/🔴low), driven by explicit triggers: long-tail thinness, lead-time change, spike ambiguity, stockout censoring.
- **Three planner actions on every escalated item**: approve as-is, approve with a quantity override (with a note — this is the seed of a feedback dataset for tuning thresholds later), or reject outright.
- **Auto-approvals are visible and reversible**, not invisible. A planner can audit or pull back any auto-approved order.
- **Append-only audit log** (`audit_log.jsonl`) — every planner decision is timestamped and stored, so "why did we order 500 units of X" is answerable months later without relying on anyone's memory — directly solving the single-point-of-failure problem in the brief.
- **Underlying data is one click away** — the audit tab lets a planner drop into the raw weekly sales/inventory history behind any SKU, so the agent's claims are always checkable against ground truth.

## 4. Honest limitations

- **Forecasting is a heuristic, not a real forecasting model.** The demand correction (censoring factor) and safety-stock formula (√lead-time rule) are reasonable textbook approximations, not a fitted model (no ARIMA/Prophet/ML here). At real volume you'd want a proper probabilistic forecast per SKU, ideally with exogenous regressors (promotions, weather, marketing spend) — this prototype has none of that.
- **Seasonality detection is a crude heuristic** (category-level lookback ratio), not decomposed seasonality. It would misfire on categories with multiple overlapping seasonal patterns.
- **No supplier/PO system integration** — "auto-approve" here means "logged in this app," not "actually cut a PO in the ERP." Wiring that up means idempotency, partial-receipt handling, and rollback logic that doesn't exist yet.
- **Single-echelon, single-location.** Real mid-market retailers have multiple DCs/stores with transfer options; this treats each SKU as one inventory pool. Multi-location allocation is a materially harder problem (transshipment, store-level stockout risk) and isn't attempted.
- **8 SKUs, 20 weeks — not real volume.** At tens of thousands of SKUs, the per-SKU Python loop here would need to become a batch/vectorized job, and the review queue UI would need triage/sorting/bulk-approve, not a flat list.
- **No concurrent-user or write-conflict handling.** Two planners reviewing the same SKU simultaneously would clobber each other; this is a single-session prototype.
- **What I mocked**: all sales/inventory/lead-time data is synthetic (see `generate_data.py`), including the injected edge cases. The MOQ/cost/price figures are illustrative, not sourced from a real supplier catalog.
- **What I would never ship as-is**: the fixed dollar/unit auto-approve ceiling (arbitrary constants), the absence of any confirmation loop with the actual supplier/ERP before "approving" an order, and the lack of any test coverage or monitoring on the forecasting logic. In production, auto-approval thresholds should be tunable per category by a category manager, not hardcoded, and every forecast should be back-tested against actuals continuously with drift alerts.
