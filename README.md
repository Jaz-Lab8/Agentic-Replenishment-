The situation
A mid-market omnichannel retailer runs demand planning and replenishment in spreadsheets and a legacy ERP screen. A planner manually pulls sales, eyeballs trends, and places purchase suggestions every week. It’s slow, it’s wrong at the long tail, and the one planner who understands it is a single point of failure. Leadership wants “AI” but cannot articulate what good looks like.

This is an AI-led business operations problem — downstream ops that quietly shape the customer experience (stockouts, over-discounting, late replenishment). Your task is to reimagine the planner’s workflow as an agentic system and build a credible working prototype of it.

What we want you to produce
A reimagined workflow. Show the current human loop, then the agentic version: what the agent senses, decides, drafts, and escalates to a human. Be explicit about where the human stays in the loop and why.

A working agentic prototype. Build a system that ingests sample sales/inventory data and produces replenishment or demand recommendations with reasoning a planner could trust. It should handle at least one realistic edge case (a demand spike, a supplier lead-time change, a long-tail SKU) visibly and well.

A trust & control layer. How does a planner verify, override, or correct the agent? How does the system explain itself? Design and at least partially build this — it is the hard part, not an afterthought.

An honest limitations section. Where would this fail in production at real data volume? What did you mock? What would you never ship as-is?

Constraints & freedom
Area

Constraint

LLM

NA

Data

Synthesize realistic multi-week sales + inventory data (your structure)

Stack

Any framework; deployability and a live URL matter

Agentic

Show genuine sense→decide→act→escalate logic, not a single prompt call


How we score Case 02
Dimension

What strong looks like

AI-native judgment

Agent design fits the real ops loop; AI used where it earns its place

Build depth

Runs end to end on realistic data; handles an edge case visibly

Product thinking

Human-in-the-loop, trust, and override designed deliberately

Articulation

Decisions README and Loom make the reasoning legible and honest

