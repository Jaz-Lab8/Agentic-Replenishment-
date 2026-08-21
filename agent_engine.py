
"""
Agentic Replenishment System — Core Engine
============================================
Implements a genuine sense -> decide -> draft -> act/escalate loop.
No single-prompt-call shortcut: each stage is a discrete, inspectable function
with its own inputs/outputs, so a planner (or an auditor) can see exactly
which facts led to which recommendation.

This is deliberately NOT a black box. Every recommendation carries a
structured "reasoning trace" object that the trust layer renders back to
the planner.
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# STAGE 1: SENSE
# Pull raw signals into a normalized per-SKU state. This is where an edge
# case first becomes *visible* to the system (stockout censoring a demand
# signal, a lead-time change, a sudden velocity break).
# ---------------------------------------------------------------------------

@dataclass
class SkuSignal:
    sku: str
    product_name: str
    category: str
    weeks: pd.DataFrame              # last N weeks of history for this SKU
    on_hand: int
    lead_time_days: int
    lead_time_changed: bool
    moq: int
    unit_cost: float
    unit_price: float
    recent_stockout_weeks: int        # weeks in last 4 where demand was censored
    demand_last_4wk_avg: float        # naive average (may be censored)
    demand_prior_avg: float           # average from weeks 5-12 back, for comparison
    velocity_break_ratio: float       # last4 / prior, >1 = accelerating
    trend_flag: str                   # "spike" | "decline" | "seasonal_rise" | "stable"


def sense(history: pd.DataFrame, sku: str) -> SkuSignal:
    h = history[history.sku == sku].sort_values("week_start").reset_index(drop=True)
    last4 = h.tail(4)
    prior8 = h.iloc[-12:-4] if len(h) >= 12 else h.iloc[:max(0, len(h)-4)]

    on_hand = int(h.iloc[-1]["on_hand_end_of_week"])
    lead_time = int(h.iloc[-1]["lead_time_days"])
    prior_lead_time = int(h.iloc[-2]["lead_time_days"]) if len(h) > 1 else lead_time
    lead_time_changed = lead_time != prior_lead_time

    recent_stockout_weeks = int(last4["stockout_flag"].sum())
    # demand_last_4wk_avg uses sell_through, corrected upward if censored (see decide stage)
    demand_last_4wk_avg = last4["sell_through_units"].mean()
    demand_prior_avg = prior8["sell_through_units"].mean() if len(prior8) else demand_last_4wk_avg

    velocity_break_ratio = (demand_last_4wk_avg / demand_prior_avg) if demand_prior_avg > 0 else 1.0

    trend_flag = "stable"
    if velocity_break_ratio >= 1.6:
        trend_flag = "spike"
    elif velocity_break_ratio <= 0.5:
        trend_flag = "decline"
    # seasonal detection: category-level uptick pattern (simplified heuristic)
    if h.iloc[-1]["category"] in ("Footwear",) and h["units_sold"].tail(4).mean() > h["units_sold"].head(10).mean() * 2:
        trend_flag = "seasonal_rise"

    return SkuSignal(
        sku=sku,
        product_name=h.iloc[-1]["product_name"],
        category=h.iloc[-1]["category"],
        weeks=h,
        on_hand=on_hand,
        lead_time_days=lead_time,
        lead_time_changed=lead_time_changed,
        moq=int(h.iloc[-1]["moq"]),
        unit_cost=float(h.iloc[-1]["unit_cost"]),
        unit_price=float(h.iloc[-1]["unit_price"]),
        recent_stockout_weeks=recent_stockout_weeks,
        demand_last_4wk_avg=demand_last_4wk_avg,
        demand_prior_avg=demand_prior_avg,
        velocity_break_ratio=velocity_break_ratio,
        trend_flag=trend_flag,
    )


# ---------------------------------------------------------------------------
# STAGE 2: DECIDE
# Turn the sensed signal into a quantitative recommendation. Includes
# demand-censoring correction (the classic "stockout hides true demand" trap)
# and lead-time-aware safety stock.
# ---------------------------------------------------------------------------

@dataclass
class Decision:
    sku: str
    recommended_order_qty: int
    demand_forecast_weekly: float
    safety_stock: float
    reorder_point: float
    confidence: str            # "high" | "medium" | "low"
    action: str                # "auto_approve" | "escalate" | "no_action"
    escalation_reasons: list = field(default_factory=list)
    reasoning_trace: list = field(default_factory=list)   # human-readable steps


AUTO_APPROVE_CEILING_UNITS = 300      # orders below this $-impact-free line can auto-approve
AUTO_APPROVE_MAX_COST = 1500.0        # $ cap for auto-approval
LONG_TAIL_STOCKOUT_RISK_WEEKS = 8     # long-tail: only reorder if truly needed, escalate more readily


def decide(signal: SkuSignal) -> Decision:
    trace = []
    trace.append(f"Sensed trend_flag='{signal.trend_flag}' (last4wk avg={signal.demand_last_4wk_avg:.1f} vs prior avg={signal.demand_prior_avg:.1f}, ratio={signal.velocity_break_ratio:.2f})")

    # --- Demand censoring correction ---
    demand_forecast = signal.demand_last_4wk_avg
    if signal.recent_stockout_weeks > 0:
        # if we were out of stock, observed sell-through UNDERSTATES true demand.
        # Correct upward using velocity_break_ratio-adjusted prior average as a floor,
        # and inflate by a censoring factor proportional to stockout weeks.
        censor_factor = 1 + (signal.recent_stockout_weeks / 4) * 0.6
        corrected = max(signal.demand_last_4wk_avg * censor_factor, signal.demand_prior_avg)
        trace.append(
            f"Stockout detected in {signal.recent_stockout_weeks}/4 recent weeks -> observed sales "
            f"understate true demand. Correcting forecast from {demand_forecast:.1f}/wk to {corrected:.1f}/wk "
            f"(censoring factor {censor_factor:.2f}x, floored at prior avg)."
        )
        demand_forecast = corrected

    if signal.trend_flag == "spike":
        trace.append(
            f"Velocity break ratio {signal.velocity_break_ratio:.2f}x flags a DEMAND SPIKE, not just noise. "
            f"Treating recent window as the new baseline rather than smoothing it away."
        )
    elif signal.trend_flag == "seasonal_rise":
        trace.append("Category pattern matches known seasonal ramp (footwear entering cold-weather season).")

    # --- Lead-time-aware safety stock ---
    lt_weeks = signal.lead_time_days / 7.0
    # simple safety stock: cover lead time + buffer, buffer scales with demand volatility
    volatility = signal.weeks["sell_through_units"].tail(8).std()
    volatility = 0.0 if pd.isna(volatility) else volatility
    safety_stock = 1.65 * volatility * (lt_weeks ** 0.5)   # ~95% service level, sqrt(LT) rule
    reorder_point = demand_forecast * lt_weeks + safety_stock

    if signal.lead_time_changed:
        trace.append(
            f"Lead time changed to {signal.lead_time_days} days (was different last week). "
            f"Reorder point recalculated against the NEW lead time -> covers {lt_weeks:.1f} weeks of demand + safety stock."
        )

    gap = reorder_point - signal.on_hand
    raw_order_qty = max(0, gap)

    # respect MOQ
    order_qty = int(np.ceil(raw_order_qty / signal.moq) * signal.moq) if raw_order_qty > 0 else 0

    trace.append(
        f"On hand={signal.on_hand}, reorder point={reorder_point:.0f} "
        f"(demand {demand_forecast:.1f}/wk x {lt_weeks:.1f}wk lead time + safety stock {safety_stock:.0f}). "
        f"Gap={raw_order_qty:.0f} -> rounded to MOQ {signal.moq} = {order_qty} units."
    )

    # --- Confidence & escalation logic ---
    reasons = []
    confidence = "high"

    if signal.category == "" or signal.demand_prior_avg < 10 and signal.velocity_break_ratio == 1.0 and signal.recent_stockout_weeks == 0:
        pass  # placeholder, long-tail handled below

    is_long_tail = signal.demand_prior_avg < 10
    if is_long_tail:
        confidence = "low"
        reasons.append(
            f"Long-tail SKU (avg demand {signal.demand_prior_avg:.1f}/wk) — forecast is noisy on thin history; "
            f"a wrong call here risks tying up cash in dead stock or missing a genuine reorder."
        )

    if signal.lead_time_changed:
        confidence = "low"
        reasons.append("Supplier lead time just changed — recommendation is based on unconfirmed new terms.")

    if signal.trend_flag == "spike":
        confidence = "medium" if confidence == "high" else confidence
        reasons.append(
            f"Demand spike ({signal.velocity_break_ratio:.1f}x baseline) — could be a one-off or the new normal; "
            f"planner judgment needed on whether to chase it."
        )

    if signal.recent_stockout_weeks >= 2:
        reasons.append(f"Stocked out {signal.recent_stockout_weeks} of last 4 weeks — true demand estimate is corrected, not observed.")
        confidence = "medium" if confidence == "high" else confidence

    order_cost = order_qty * signal.unit_cost

    if order_qty == 0:
        action = "no_action"
    elif reasons:
        action = "escalate"
    elif order_cost <= AUTO_APPROVE_MAX_COST and order_qty <= AUTO_APPROVE_CEILING_UNITS:
        action = "auto_approve"
    else:
        action = "escalate"
        reasons.append(f"Order value ${order_cost:,.0f} exceeds auto-approve ceiling (${AUTO_APPROVE_MAX_COST:,.0f}) — needs sign-off.")

    return Decision(
        sku=signal.sku,
        recommended_order_qty=order_qty,
        demand_forecast_weekly=round(demand_forecast, 1),
        safety_stock=round(safety_stock, 1),
        reorder_point=round(reorder_point, 1),
        confidence=confidence,
        action=action,
        escalation_reasons=reasons,
        reasoning_trace=trace,
    )


# ---------------------------------------------------------------------------
# STAGE 3: DRAFT
# Turn the decision into a planner-facing artifact: a PO draft (or a "no
# action" note) with plain-language reasoning, ready for review.
# ---------------------------------------------------------------------------

@dataclass
class PODraft:
    sku: str
    product_name: str
    recommended_qty: int
    unit_cost: float
    total_cost: float
    action: str
    confidence: str
    headline: str
    reasoning_trace: list
    escalation_reasons: list
    status: str = "pending_review"   # pending_review | approved | overridden | rejected
    planner_note: Optional[str] = None
    final_qty: Optional[int] = None


def draft(signal: SkuSignal, decision: Decision) -> PODraft:
    if decision.action == "no_action":
        headline = f"No reorder needed for {signal.product_name} — on-hand covers forecasted demand through lead time."
    else:
        headline = (
            f"Recommend ordering {decision.recommended_order_qty} units of {signal.product_name} "
            f"(~${decision.recommended_order_qty * signal.unit_cost:,.0f}), lead time {signal.lead_time_days}d."
        )
    return PODraft(
        sku=signal.sku,
        product_name=signal.product_name,
        recommended_qty=decision.recommended_order_qty,
        unit_cost=signal.unit_cost,
        total_cost=round(decision.recommended_order_qty * signal.unit_cost, 2),
        action=decision.action,
        confidence=decision.confidence,
        headline=headline,
        reasoning_trace=decision.reasoning_trace,
        escalation_reasons=decision.escalation_reasons,
        final_qty=decision.recommended_order_qty,
    )


# ---------------------------------------------------------------------------
# STAGE 4: ACT / ESCALATE
# auto_approve -> logged as an approved PO, still fully visible/reversible.
# escalate -> queued for planner review with reasons surfaced up front.
# no_action -> logged, not shown unless planner wants to audit.
# ---------------------------------------------------------------------------

def act_or_escalate(po: PODraft) -> PODraft:
    if po.action == "auto_approve":
        po.status = "approved"
    elif po.action == "escalate":
        po.status = "pending_review"
    else:
        po.status = "no_action"
    return po


def run_pipeline(history: pd.DataFrame) -> list:
    """Run sense -> decide -> draft -> act for every SKU. Returns list of PODraft."""
    results = []
    for sku in sorted(history.sku.unique()):
        signal = sense(history, sku)
        decision = decide(signal)
        po = draft(signal, decision)
        po = act_or_escalate(po)
        results.append(po)
    return results
