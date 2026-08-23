"""
mock_warehouse_api.py

A stand-in for NorthStar's real warehouse/POS API. This exists purely so the
sync service can be built and tested end to end before NorthStar's actual
system is connected. It exposes one endpoint that returns a JSON list of
stock records, and quietly drifts the quantities on each call so you can see
the poller pick up real changes over time.

Run this on port 6060. Point the sync service's WAREHOUSE_API_URL at
http://localhost:6060/inventory
"""

from flask import Flask, jsonify, request
import random
import threading

app = Flask(__name__)


@app.after_request
def add_cors_headers(response):
    # Only needed because the demo frontend calls this mock directly to
    # simulate a POS event. A real warehouse API would never be called from
    # a browser like this — the real event source is the POS/warehouse
    # system's own backend, talking to the sync service's poller.
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, PATCH, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response

# Shared "warehouse" state. In real life this data lives in NorthStar's
# systems; here it just lives in memory so the mock has something to serve.
_lock = threading.Lock()
_inventory = [
    {"sku": "NS-BP-4001", "name": "Trailhead 40L Backpack", "qty": 14, "threshold": 5, "location": "Nairobi DC - Aisle 3B"},
    {"sku": "NS-AP-1187", "name": "Summit Merino Hoodie - Charcoal", "qty": 3, "threshold": 5, "location": "Nairobi DC - Aisle 1A"},
    {"sku": "NS-FT-2290", "name": "Kilifi Trail Running Shoe, M9", "qty": 0, "threshold": 5, "location": "Mombasa DC - Aisle 5C"},
    {"sku": "NS-HW-0552", "name": "Everyday Steel Water Bottle 1L", "qty": 58, "threshold": 10, "location": "Nairobi DC - Aisle 2D"},
    {"sku": "NS-HW-0781", "name": "Rift Valley Camp Chair", "qty": 7, "threshold": 8, "location": "Kisumu DC - Aisle 1C"},
    {"sku": "NS-CP-3315", "name": "Longonot 2-Person Tent", "qty": 2, "threshold": 4, "location": "Nairobi DC - Aisle 4A"},
    {"sku": "NS-AP-1420", "name": "Savanna Wide-Brim Sun Hat", "qty": 22, "threshold": 6, "location": "Mombasa DC - Aisle 1B"},
]


def _drift_stock():
    """Nudge a random item's quantity, simulating sales/receiving between polls."""
    with _lock:
        item = random.choice(_inventory)
        delta = random.choice([-3, -2, -1, 1, 2, 4])
        item["qty"] = max(0, item["qty"] + delta)


@app.route("/inventory", methods=["GET"])
def get_inventory():
    _drift_stock()
    with _lock:
        # Return a deep-enough copy so callers can't mutate our state
        return jsonify([dict(item) for item in _inventory])


@app.route("/inventory/<sku>", methods=["PATCH"])
def update_item(sku):
    """
    Simulates a POS sale or a warehouse receiving event setting a new
    quantity for one SKU. In a real system this write would come from
    NorthStar's own POS/warehouse software, not from the support tool —
    this endpoint exists purely so the demo has a way to trigger a real
    change and watch it flow through the sync service on the next poll.
    """
    data = request.get_json(silent=True) or {}
    qty = data.get("qty")

    if qty is None:
        return jsonify({"error": "missing_qty", "message": "Body must include integer 'qty'"}), 400
    try:
        qty = int(qty)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid_qty", "message": "'qty' must be an integer"}), 400
    if qty < 0:
        return jsonify({"error": "invalid_qty", "message": "'qty' cannot be negative"}), 400

    with _lock:
        item = next((i for i in _inventory if i["sku"] == sku), None)
        if item is None:
            return jsonify({"error": "unknown_sku", "message": f"No SKU '{sku}' in warehouse records"}), 404
        item["qty"] = qty
        result = dict(item)

    return jsonify(result)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(port=6060, debug=False)
