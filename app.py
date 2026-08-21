
"""
Agentic Replenishment Planner — Trust & Control UI
====================================================
Streamlit app: the planner's cockpit. Every recommendation is shown with
its full reasoning trace, confidence, and escalation reasons. Planner can
approve, override quantity, or reject — and every action is logged to an
audit trail (append-only) so the system is explainable AFTER the fact too.
"""

import streamlit as st
import pandas as pd
import json
import os
from datetime import datetime
from agent_engine import run_pipeline, sense, decide, draft, act_or_escalate

st.set_page_config(page_title="Replenishment Copilot", layout="wide")

AUDIT_LOG = "audit_log.jsonl"

def log_action(sku, action, detail):
    entry = {"ts": datetime.now().isoformat(timespec="seconds"), "sku": sku, "action": action, "detail": detail}
    with open(AUDIT_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")

@st.cache_data
def load_history():
    return pd.read_csv("sales_inventory_history.csv")

history = load_history()

if "decisions" not in st.session_state:
    st.session_state.decisions = {po.sku: po for po in run_pipeline(history)}
if "overrides" not in st.session_state:
    st.session_state.overrides = {}

st.title("📦 Replenishment Copilot — Agent Review Queue")
st.caption(
    "Sense → Decide → Draft → Escalate. Every number below is traceable. "
    "The agent auto-approves only small, low-risk, high-confidence orders — "
    "everything else lands here for you."
)

decisions = st.session_state.decisions

col1, col2, col3, col4 = st.columns(4)
n_auto = sum(1 for p in decisions.values() if p.action == "auto_approve")
n_escalate = sum(1 for p in decisions.values() if p.action == "escalate")
n_none = sum(1 for p in decisions.values() if p.action == "no_action")
total_escalated_value = sum(p.total_cost for p in decisions.values() if p.action == "escalate")
col1.metric("Auto-approved", n_auto)
col2.metric("Needs your review", n_escalate)
col3.metric("No action needed", n_none)
col4.metric("$ pending your approval", f"${total_escalated_value:,.0f}")

st.divider()

tab_review, tab_auto, tab_audit = st.tabs(["🔎 Needs Review", "✅ Auto-Approved", "📜 Audit Trail"])

with tab_review:
    review_items = [p for p in decisions.values() if p.action == "escalate"]
    if not review_items:
        st.success("Nothing needs your review right now.")
    for po in review_items:
        with st.container(border=True):
            badge = {"low": "🔴", "medium": "🟡", "high": "🟢"}[po.confidence]
            st.subheader(f"{badge} {po.product_name}  ·  {po.sku}")
            st.write(po.headline)

            with st.expander("Why is the agent recommending this? (reasoning trace)"):
                for step in po.reasoning_trace:
                    st.markdown(f"- {step}")
                st.markdown("**Why this needs your sign-off, not auto-approval:**")
                for r in po.escalation_reasons:
                    st.markdown(f"- ⚠️ {r}")

            c1, c2, c3 = st.columns([1, 1, 2])
            with c1:
                qty = st.number_input(
                    "Order quantity", min_value=0, value=int(po.recommended_qty),
                    step=int(po.moq if hasattr(po, "moq") else 10),
                    key=f"qty_{po.sku}"
                )
            with c2:
                st.metric("Est. cost", f"${qty * po.unit_cost:,.0f}")
            with c3:
                note = st.text_input("Note (optional)", key=f"note_{po.sku}", placeholder="e.g. confirmed with supplier, approve as-is")

            b1, b2, b3 = st.columns(3)
            if b1.button("✅ Approve as recommended", key=f"approve_{po.sku}"):
                po.status = "approved"
                po.final_qty = po.recommended_qty
                log_action(po.sku, "approved", {"qty": po.recommended_qty, "note": note})
                st.success(f"Approved {po.recommended_qty} units of {po.sku}")
            if b2.button("✏️ Approve with override", key=f"override_{po.sku}"):
                po.status = "overridden"
                po.final_qty = qty
                po.planner_note = note
                log_action(po.sku, "overridden", {"original_qty": po.recommended_qty, "new_qty": qty, "note": note})
                st.info(f"Overrode to {qty} units for {po.sku}. Logged for retraining review.")
            if b3.button("❌ Reject", key=f"reject_{po.sku}"):
                po.status = "rejected"
                po.final_qty = 0
                po.planner_note = note
                log_action(po.sku, "rejected", {"original_qty": po.recommended_qty, "note": note})
                st.warning(f"Rejected recommendation for {po.sku}.")

with tab_auto:
    auto_items = [p for p in decisions.values() if p.action == "auto_approve"]
    if not auto_items:
        st.info("No orders were auto-approved this cycle.")
    for po in auto_items:
        with st.container(border=True):
            st.subheader(f"🟢 {po.product_name} · {po.sku} — auto-approved")
            st.write(po.headline)
            with st.expander("Reasoning (why the agent trusted itself here)"):
                for step in po.reasoning_trace:
                    st.markdown(f"- {step}")
                st.caption("Auto-approved because: high confidence, no active escalation triggers, and order value under the auto-approve ceiling.")
            if st.button("Undo auto-approval / pull back for review", key=f"pullback_{po.sku}"):
                po.action = "escalate"
                po.status = "pending_review"
                po.escalation_reasons.append("Manually pulled back from auto-approval by planner.")
                log_action(po.sku, "pulled_back", {"qty": po.recommended_qty})
                st.rerun()

with tab_audit:
    st.write("Append-only log of every planner action taken against agent recommendations.")
    if os.path.exists(AUDIT_LOG):
        with open(AUDIT_LOG) as f:
            lines = [json.loads(l) for l in f.readlines()]
        if lines:
            st.dataframe(pd.DataFrame(lines), use_container_width=True)
        else:
            st.caption("No actions logged yet.")
    else:
        st.caption("No actions logged yet.")

    st.divider()
    st.subheader("Underlying sales/inventory history (what the agent sensed)")
    sku_filter = st.selectbox("Filter by SKU", ["All"] + sorted(history.sku.unique().tolist()))
    if sku_filter == "All":
        st.dataframe(history, use_container_width=True, height=300)
    else:
        st.dataframe(history[history.sku == sku_filter], use_container_width=True, height=300)
