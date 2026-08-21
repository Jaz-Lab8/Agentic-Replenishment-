
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

np.random.seed(42)

SKUS = [
    {"sku": "SKU-1001", "name": "Classic Cotton Tee - Navy", "category": "Apparel", "velocity": "fast", "lead_time_days": 14, "moq": 200, "cost": 6.5, "price": 19.99},
    {"sku": "SKU-1002", "name": "Running Shoe - Men 9", "category": "Footwear", "velocity": "fast", "lead_time_days": 30, "moq": 100, "cost": 22.0, "price": 79.99},
    {"sku": "SKU-1003", "name": "Wool Beanie - Charcoal", "category": "Accessories", "velocity": "medium", "lead_time_days": 21, "moq": 150, "cost": 4.0, "price": 14.99},
    {"sku": "SKU-1004", "name": "Ceramic Mug - Sage Green", "category": "Home", "velocity": "long_tail", "lead_time_days": 45, "moq": 50, "cost": 3.2, "price": 12.99},
    {"sku": "SKU-1005", "name": "Yoga Mat - Purple", "category": "Fitness", "velocity": "medium", "lead_time_days": 28, "moq": 80, "cost": 9.0, "price": 34.99},
    {"sku": "SKU-1006", "name": "Kids Rain Boots - Size 10", "category": "Footwear", "velocity": "seasonal", "lead_time_days": 35, "moq": 100, "cost": 8.5, "price": 29.99},
    {"sku": "SKU-1007", "name": "Enamel Pin Set - Travel", "category": "Accessories", "velocity": "long_tail", "lead_time_days": 40, "moq": 60, "cost": 2.1, "price": 9.99},
    {"sku": "SKU-1008", "name": "Insulated Water Bottle - 32oz", "category": "Fitness", "velocity": "fast", "lead_time_days": 20, "moq": 150, "cost": 6.0, "price": 24.99},
]

WEEKS = 20  # 20 weeks of history
START = datetime(2026, 3, 30)

def base_demand(v):
    return {"fast": 180, "medium": 60, "long_tail": 6, "seasonal": 40}[v]

rows = []
for sku in SKUS:
    b = base_demand(sku["velocity"])
    on_hand = int(b * np.random.uniform(2, 4))
    for w in range(WEEKS):
        week_start = START + timedelta(weeks=w)
        trend = 1 + 0.01 * w if sku["velocity"] != "long_tail" else 1.0
        noise = np.random.normal(1, 0.15 if sku["velocity"] != "long_tail" else 0.6)
        seasonal_mult = 1.0
        if sku["velocity"] == "seasonal" and w >= 14:  # rain boots spike late in window (autumn)
            seasonal_mult = 3.2

        # INJECTED EDGE CASE 1: demand spike for a fast mover in week 17 (e.g. viral/social spike)
        spike_mult = 1.0
        if sku["sku"] == "SKU-1002" and w in (17, 18, 19):
            spike_mult = 2.8

        units_sold = max(0, int(b * trend * noise * seasonal_mult * spike_mult))

        # INJECTED EDGE CASE 2: supplier lead-time change communicated mid-window for SKU-1005
        lead_time_override = None
        if sku["sku"] == "SKU-1005" and w == 19:
            lead_time_override = 56  # supplier delay notice: 28 -> 56 days

        stockout_flag = False
        sell_through = units_sold
        if on_hand < units_sold:
            stockout_flag = True
            sell_through = on_hand  # can't sell what you don't have -> demand is CENSORED
        on_hand = max(0, on_hand - sell_through)

        # weekly inbound replenishment trickle (simplified, except long tail which reorders rarely)
        inbound = 0
        if w > 0 and w % 6 == 0 and sku["velocity"] != "long_tail":
            inbound = int(b * 3)
        on_hand += inbound

        rows.append({
            "week_start": week_start.strftime("%Y-%m-%d"),
            "sku": sku["sku"],
            "product_name": sku["name"],
            "category": sku["category"],
            "units_sold": units_sold,
            "sell_through_units": sell_through,
            "stockout_flag": stockout_flag,
            "on_hand_end_of_week": on_hand,
            "lead_time_days": lead_time_override if lead_time_override else sku["lead_time_days"],
            "moq": sku["moq"],
            "unit_cost": sku["cost"],
            "unit_price": sku["price"],
        })

df = pd.DataFrame(rows)
df.to_csv("sales_inventory_history.csv", index=False)
print(df.tail(10).to_string())
print("\nRows:", len(df), "SKUs:", df.sku.nunique(), "Weeks:", df.week_start.nunique())
