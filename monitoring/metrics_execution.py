# monitoring/metrics_execution.py
from prometheus_client import Counter, Histogram, Gauge

orders_submitted = Counter("orders_submitted_total", "Orders submitted", ["exchange","symbol","side","strategy"])
orders_filled    = Counter("orders_filled_total", "Orders fully filled", ["exchange","symbol","side","strategy"])
orders_rejected  = Counter("orders_rejected_total", "Orders rejected", ["exchange","symbol","side","strategy","reason"])
risk_halts       = Counter("risk_halts_total", "Orders blocked by risk", ["strategy","reason"])
order_latency    = Histogram("order_latency_seconds", "Submit-to-fill latency", buckets=(0.1,0.25,0.5,1,2,5,10))
open_orders_gauge= Gauge("open_orders", "Open orders", ["exchange"])
def record_order(exchange: str, symbol: str, side: str, strategy: str, filled: bool = False, rejected_reason: str = None):
    labels = {"exchange": exchange, "symbol": symbol, "side": side, "strategy": strategy}
    if filled:
        orders_filled.labels(**labels).inc()
    elif rejected_reason:
        labels["reason"] = rejected_reason
        orders_rejected.labels(**labels).inc()
    else:
        orders_submitted.labels(**labels).inc()