"""
app.py — NorthStar Inventory Sync Service

What this does, in one sentence: polls a warehouse API on a timer, holds the
latest stock numbers in memory, and answers stock queries from that cache
instead of hitting the warehouse API on every request.

Why cache instead of calling the warehouse API live on every lookup:
- The warehouse API may be slow, rate limited, or occasionally down. A support
  agent's "is this in stock" query should not fail just because the warehouse
  system had a bad moment.
- Polling on a fixed interval gives predictable, bounded load on the
  warehouse's system regardless of how many support agents are querying.
- The cache carries a "how fresh is this" timestamp, so the support tool can
  be honest about staleness instead of silently serving old numbers as if
  they were current.

Run with:
    python app.py

Configuration (environment variables, all optional):
    WAREHOUSE_API_URL       Default: http://localhost:6060/inventory
    WAREHOUSE_API_KEY       Sent as a Bearer token if set. Default: unset.
    POLL_INTERVAL_SECONDS   Default: 300 (5 minutes)
    STALE_AFTER_SECONDS     Default: 2x poll interval
    PORT                    Default: 5050
"""

import os
import time
import logging
import threading
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify, request

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

WAREHOUSE_API_URL = os.environ.get("WAREHOUSE_API_URL", "http://localhost:6060/inventory")
WAREHOUSE_API_KEY = os.environ.get("WAREHOUSE_API_KEY")  # optional
POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", 300))  # 5 minutes
STALE_AFTER_SECONDS = int(os.environ.get("STALE_AFTER_SECONDS", POLL_INTERVAL_SECONDS * 2))
PORT = int(os.environ.get("PORT", 5050))
REQUEST_TIMEOUT_SECONDS = 10

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("inventory-sync")

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
# A single dict protected by a lock. The poller thread writes to it on a
# timer; request handlers only ever read from it. Writes replace the whole
# "items" mapping atomically so a reader never sees a half-updated cache.

_cache_lock = threading.Lock()
_cache = {
    "items": {},           # sku -> {name, qty, threshold, location}
    "last_synced": None,   # datetime of last successful poll, or None if never succeeded
    "last_attempt": None,  # datetime of the most recent poll attempt, success or not
    "last_error": None,    # string description of the last failure, or None
    "consecutive_failures": 0,
}

# Separate lock/flag for pausing the poller. This exists so a demo or a test
# can genuinely stop polling (simulating the warehouse being unreachable, or
# an ops decision to pause sync) rather than faking the effect in the UI.
# Real production code wouldn't need this — it exists for demonstrating and
# testing the stale-data behavior on demand.
_pause_lock = threading.Lock()
_sync_paused = False


def _is_paused():
    with _pause_lock:
        return _sync_paused


def _set_paused(value):
    global _sync_paused
    with _pause_lock:
        _sync_paused = value


def _now():
    return datetime.now(timezone.utc)


def poll_warehouse_once():
    """
    Fetch the current stock list from the warehouse API and, on success,
    replace the cache. On failure, the existing cache is left untouched —
    a temporarily unreachable warehouse API should degrade the freshness
    of the data, not delete it.
    """
    headers = {}
    if WAREHOUSE_API_KEY:
        headers["Authorization"] = f"Bearer {WAREHOUSE_API_KEY}"

    attempt_time = _now()

    try:
        response = requests.get(WAREHOUSE_API_URL, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()

        if not isinstance(payload, list):
            raise ValueError("Expected a JSON list of stock records")

        new_items = {}
        for record in payload:
            sku = record["sku"]
            new_items[sku] = {
                "name": record.get("name", sku),
                "qty": int(record["qty"]),
                "threshold": int(record.get("threshold", 5)),
                "location": record.get("location", "unknown"),
            }

        with _cache_lock:
            _cache["items"] = new_items
            _cache["last_synced"] = attempt_time
            _cache["last_attempt"] = attempt_time
            _cache["last_error"] = None
            _cache["consecutive_failures"] = 0

        log.info("Poll succeeded: %d SKUs synced from %s", len(new_items), WAREHOUSE_API_URL)
        return True

    except Exception as exc:
        with _cache_lock:
            _cache["last_attempt"] = attempt_time
            _cache["last_error"] = str(exc)
            _cache["consecutive_failures"] += 1
            failures = _cache["consecutive_failures"]

        log.error("Poll failed (%d consecutive failure(s)): %s", failures, exc)
        return False


def poller_loop():
    """
    Background loop: poll immediately on startup so the cache is warm before
    the first request arrives, then poll again every POLL_INTERVAL_SECONDS.
    """
    log.info(
        "Starting poller. Target=%s interval=%ds",
        WAREHOUSE_API_URL, POLL_INTERVAL_SECONDS,
    )
    while True:
        if _is_paused():
            log.info("Poll skipped: sync is paused")
        else:
            poll_warehouse_once()
        time.sleep(POLL_INTERVAL_SECONDS)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _status_for(qty, threshold):
    if qty <= 0:
        return "out_of_stock"
    if qty <= threshold:
        return "low_stock"
    return "in_stock"


def _seconds_since(dt):
    if dt is None:
        return None
    return round((_now() - dt).total_seconds(), 1)


def _snapshot():
    """Take a consistent, read-only snapshot of the cache under the lock."""
    with _cache_lock:
        return {
            "items": dict(_cache["items"]),
            "last_synced": _cache["last_synced"],
            "last_attempt": _cache["last_attempt"],
            "last_error": _cache["last_error"],
            "consecutive_failures": _cache["consecutive_failures"],
        }


def _is_stale(last_synced):
    age = _seconds_since(last_synced)
    if age is None:
        return True
    return age > STALE_AFTER_SECONDS


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.after_request
def add_cors_headers(response):
    # Allows the support tool's frontend (a separate static page/origin) to
    # call this API directly from the browser. Locking this down to a
    # specific origin is a production hardening step, noted in the README.
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


@app.route("/api/stock", methods=["GET"])
def list_stock():
    """Return every cached SKU with computed status and freshness metadata."""
    snap = _snapshot()
    stale = _is_stale(snap["last_synced"])

    items = []
    for sku, record in snap["items"].items():
        items.append({
            "sku": sku,
            "name": record["name"],
            "qty": record["qty"],
            "location": record["location"],
            "status": _status_for(record["qty"], record["threshold"]),
        })

    return jsonify({
        "items": items,
        "count": len(items),
        "last_synced": snap["last_synced"].isoformat() if snap["last_synced"] else None,
        "seconds_since_sync": _seconds_since(snap["last_synced"]),
        "stale": stale,
    })


@app.route("/api/stock/<sku>", methods=["GET"])
def get_stock(sku):
    """Return a single SKU's cached stock info, or 404 if unknown."""
    snap = _snapshot()
    record = snap["items"].get(sku)

    if record is None:
        return jsonify({
            "error": "unknown_sku",
            "message": f"No cached record for SKU '{sku}'. It may not exist, "
                       f"or the cache may not have synced yet.",
        }), 404

    stale = _is_stale(snap["last_synced"])
    return jsonify({
        "sku": sku,
        "name": record["name"],
        "qty": record["qty"],
        "location": record["location"],
        "status": _status_for(record["qty"], record["threshold"]),
        "last_synced": snap["last_synced"].isoformat() if snap["last_synced"] else None,
        "seconds_since_sync": _seconds_since(snap["last_synced"]),
        "stale": stale,
    })


@app.route("/api/health", methods=["GET"])
def health():
    """
    Reports the sync loop's own health, not the individual stock data.
    A support tool or an ops dashboard can poll this to know whether the
    numbers it's showing agents are trustworthy right now.
    """
    snap = _snapshot()
    stale = _is_stale(snap["last_synced"])

    paused = _is_paused()

    if paused:
        status = "paused"
    elif snap["last_synced"] is None:
        status = "never_synced"
    elif snap["consecutive_failures"] >= 3:
        status = "degraded"
    elif stale:
        status = "stale"
    else:
        status = "healthy"

    return jsonify({
        "status": status,
        "paused": paused,
        "last_synced": snap["last_synced"].isoformat() if snap["last_synced"] else None,
        "last_attempt": snap["last_attempt"].isoformat() if snap["last_attempt"] else None,
        "seconds_since_sync": _seconds_since(snap["last_synced"]),
        "consecutive_failures": snap["consecutive_failures"],
        "last_error": snap["last_error"],
        "poll_interval_seconds": POLL_INTERVAL_SECONDS,
        "stale_after_seconds": STALE_AFTER_SECONDS,
        "cached_sku_count": len(snap["items"]),
    })


@app.route("/api/sync-now", methods=["POST"])
def sync_now():
    """
    Triggers an immediate poll instead of waiting for the next scheduled one.
    Useful for demos, and for an ops team confirming a fix before the next
    5 minute window rolls around. Not something the support tool itself
    should call on every query — that would defeat the point of caching.
    """
    success = poll_warehouse_once()
    snap = _snapshot()
    return jsonify({
        "triggered": True,
        "success": success,
        "last_synced": snap["last_synced"].isoformat() if snap["last_synced"] else None,
        "last_error": snap["last_error"],
    }), (200 if success else 502)


@app.route("/api/admin/pause-sync", methods=["POST"])
def pause_sync():
    """
    Stops the poller from making further calls to the warehouse API, without
    touching the existing cache. Intended for demos and testing the stale
    data path — this is what "the warehouse feed goes down" looks like from
    the support tool's point of view.
    """
    _set_paused(True)
    log.warning("Sync paused via admin endpoint")
    return jsonify({"paused": True})


@app.route("/api/admin/resume-sync", methods=["POST"])
def resume_sync():
    """Resumes polling and immediately triggers a poll so recovery is visible right away."""
    _set_paused(False)
    log.info("Sync resumed via admin endpoint")
    success = poll_warehouse_once()
    return jsonify({"paused": False, "immediate_sync_success": success})


if __name__ == "__main__":
    poller_thread = threading.Thread(target=poller_loop, daemon=True)
    poller_thread.start()
    app.run(port=PORT, debug=False)
