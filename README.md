# NorthStar Inventory Sync Service

A small Flask service that polls a warehouse/POS API on a timer, holds the latest stock numbers in memory, and answers stock queries from that cache — plus a static HTML support tool wired to it as a real client. This is one working demo now, not a backend and a separate mockup: `index.html` calls this service's actual endpoints over HTTP.

## Why cache instead of calling the warehouse API on every lookup

- The warehouse API might be slow, rate limited, or briefly down. A support agent's stock query should not fail just because the warehouse system had a bad moment.
- Polling on a fixed interval puts predictable, bounded load on the warehouse system, no matter how many agents are querying the support tool at once.
- The cache tracks its own freshness, so the service can say plainly "this number is 40 seconds old" or "this feed hasn't synced in a while" instead of quietly serving stale data as if it were current.

## Files

- `app.py` — the sync service itself: poller, cache, and API endpoints.
- `mock_warehouse_api.py` — a stand-in for NorthStar's real warehouse API, used for local testing. It serves a small product list, drifts quantities on each call so you can watch the poller pick up real changes, and accepts a `PATCH` to simulate a specific sale or restock on demand.
- `index.html` — the support-facing frontend. A static page, no build step, that calls this service's real endpoints.
- `requirements.txt` — Python dependencies.

## Running it locally

```bash
pip install -r requirements.txt

# terminal 1: start the mock warehouse API
python mock_warehouse_api.py

# terminal 2: start the sync service, polling every 5 minutes by default
python app.py
```

Then open `index.html` directly in a browser (double-click it, or drag it into a browser window — no server needed for the frontend itself).

By default the sync service polls `http://localhost:6060/inventory` every 300 seconds (5 minutes) and serves its API on port 5050. The frontend's config constants (`SYNC_API_BASE`, `WAREHOUSE_API_BASE`) at the top of its `<script>` block point at `localhost:5050` and `localhost:6060` respectively — change those if you run the services elsewhere.

To test faster during development, shorten the interval:

```bash
POLL_INTERVAL_SECONDS=15 python app.py
```



## Configuration

All configuration is via environment variables, so nothing needs to change in code to point this at NorthStar's real warehouse API later.

| Variable | Default | Purpose |
|---|---|---|
| `WAREHOUSE_API_URL` | `http://localhost:6060/inventory` | The warehouse/POS endpoint to poll. Must return a JSON list of objects, each with at least `sku` and `qty`. |
| `WAREHOUSE_API_KEY` | unset | If set, sent as `Authorization: Bearer <key>` on each poll. |
| `POLL_INTERVAL_SECONDS` | `300` | How often to poll, in seconds. |
| `STALE_AFTER_SECONDS` | `2 x poll interval` | How old the cache can get before it's flagged as stale in API responses. |
| `PORT` | `5050` | Port the sync service listens on. |

## Endpoints

### `GET /api/stock`
Returns every cached SKU with computed status and freshness metadata.

```json
{
  "items": [
    { "sku": "NS-BP-4001", "name": "Trailhead 40L Backpack", "qty": 15, "location": "Nairobi DC - Aisle 3B", "status": "in_stock" }
  ],
  "count": 7,
  "last_synced": "2026-08-23T09:40:23.065884+00:00",
  "seconds_since_sync": 1.7,
  "stale": false
}
```

### `GET /api/stock/<sku>`
Returns a single SKU's cached info. 404 with an `unknown_sku` error if the SKU isn't in the cache.

```json
{
  "sku": "NS-BP-4001",
  "name": "Trailhead 40L Backpack",
  "qty": 15,
  "location": "Nairobi DC - Aisle 3B",
  "status": "in_stock",
  "last_synced": "2026-08-23T09:40:23.065884+00:00",
  "seconds_since_sync": 1.7,
  "stale": false
}
```

`status` is one of `in_stock`, `low_stock`, `out_of_stock`, based on each item's threshold.

### `GET /api/health`
Reports the health of the sync loop itself, separate from any individual item. Useful for an ops dashboard or an alert, not just the support tool.

```json
{
  "status": "healthy",
  "last_synced": "2026-08-23T09:40:23.065884+00:00",
  "last_attempt": "2026-08-23T09:40:23.065884+00:00",
  "seconds_since_sync": 1.7,
  "consecutive_failures": 0,
  "last_error": null,
  "poll_interval_seconds": 300,
  "stale_after_seconds": 600,
  "cached_sku_count": 7
}
```

`status` is one of:
- `never_synced` — service just started, hasn't completed a poll yet
- `healthy` — recent successful sync, within the freshness window
- `stale` — cache is older than `stale_after_seconds`, but no hard failures
- `degraded` — 3 or more consecutive poll failures

### `POST /api/sync-now`
Triggers an immediate poll instead of waiting for the next scheduled one. Useful for demos, or for confirming a fix without waiting out the interval. Not meant to be called by the support tool on every lookup — that would defeat the purpose of caching. Returns HTTP 502 if the poll fails. The frontend calls this right after pushing a simulated stock change, so the demo doesn't require waiting out a real 5 minute interval to see the result.

### `POST /api/admin/pause-sync` / `POST /api/admin/resume-sync`
Genuinely stops and restarts the poller thread, without touching the existing cache. This exists so the "simulate outage" behavior in the frontend is real — it pauses the actual backend, not just a visual state in the browser. `resume-sync` also triggers an immediate poll so recovery is visible right away rather than waiting for the next cycle. These endpoints are for demos and testing the stale-data path; a production deployment would likely restrict them or drop them entirely, since pausing sync is an operational action, not something the support tool itself should expose.

### `PATCH /inventory/<sku>` (on the mock warehouse, not the sync service)
Sets a SKU's quantity directly, simulating a POS sale or a warehouse receiving event. Body: `{"qty": 42}`. This only exists on `mock_warehouse_api.py` — NorthStar's real warehouse system would have its own way of registering these events, and the sync service would simply poll and pick them up like any other change. The frontend's "Push update" button calls this directly for demo purposes only; in production, a support tool would never write to the warehouse API itself.

## What happens during a warehouse API outage

When the warehouse API is unreachable:

1. The poller logs the failure and increments `consecutive_failures`.
2. The existing cache is left untouched — stock numbers already in memory keep being served.
3. `seconds_since_sync` keeps climbing, and once it passes `STALE_AFTER_SECONDS`, `stale` flips to `true` on every response.
4. Once the warehouse API comes back, the next successful poll (scheduled or manual) clears the failure count and resets freshness.

This means a support agent never sees a hard error just because the warehouse system hiccuped — they see slightly older data, honestly labeled as such, which is a more useful failure mode for a live support conversation.

## How the frontend uses these endpoints

`northstar-inventory-sync.html` is a genuine client of this service, not a simulation:

- On load, and every 4 seconds after, it calls `GET /api/stock` to refresh the table, the ticker, and the search suggestions.
- Every 2 seconds it calls `GET /api/health` to update the connection status badge and decide whether to show a stale-data warning.
- Selecting a product in search calls `GET /api/stock/<sku>` directly, exercising the single-item lookup path rather than just filtering the already-fetched list.
- "Push update" calls `PATCH` on the mock warehouse, then `POST /api/sync-now` on the sync service, then re-fetches `/api/stock` — the same three-step loop a real POS event would trigger, just compressed into one button for demo purposes.
- "Simulate outage" calls the real `pause-sync` / `resume-sync` admin endpoints. If the sync service isn't running at all, the frontend shows a connection banner explaining that, rather than failing silently or falling back to fake data.

This was verified with an automated browser-simulation test that loaded the actual HTML file and drove it against the actual running Flask services — not a hand-written trace of what should happen. That test caught the port 6000 issue mentioned above before it could reach a real demo.

## Moving from the mock warehouse to NorthStar's real system

1. Confirm the shape of NorthStar's actual inventory endpoint. If it doesn't return a flat JSON list of `{sku, qty, ...}` objects, add a small transform step in `poll_warehouse_once()` to reshape their response into that format.
2. Set `WAREHOUSE_API_URL` (and `WAREHOUSE_API_KEY` if their API requires auth) to point at the real system.
3. Confirm their API can handle being polled every 5 minutes without issue. If they have strict rate limits, `POLL_INTERVAL_SECONDS` can be widened.
4. Run both services behind a process manager (systemd, supervisord, or a platform like Render) instead of running `python app.py` directly, so the service restarts automatically if it crashes.
5. Lock down the CORS header in `app.py` (`Access-Control-Allow-Origin`) to the support tool's actual domain instead of `*`, once that domain is known.

## What this doesn't do yet

- No persistent storage. If the process restarts, the cache is empty until the next poll completes. For a 5 minute poll interval this is a short gap, but a production version might want to write the cache to a small database on each successful poll so a restart doesn't leave a blank window.
- No retry backoff. A failed poll waits out the full interval before trying again rather than retrying sooner. Worth adding if the warehouse API has brief, frequent blips.
- No authentication on the sync service's own endpoints, or on the frontend's calls to it. Anyone who can reach the service can query stock, and anyone who can reach the mock warehouse can push a fake stock change. Fine for an internal support tool behind a private network and for this demo; would need an API key or internal auth before wider exposure.
- CORS is wide open (`Access-Control-Allow-Origin: *`) on both services, so the static HTML file can call them from any origin during development. Before this goes anywhere near production, that should be locked to the support tool's actual domain.
- The admin pause/resume endpoints have no access control. They're deliberately present for demoing and testing the stale-data path, but they're not something you'd want reachable from outside a trusted network.
