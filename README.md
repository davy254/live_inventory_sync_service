# NorthStar Retail — Inventory Sync Prototype

A single file prototype showing how a support tool could answer "is this in stock?" using a live inventory feed instead of stale data.

## What this is

NorthStar's support agents need accurate stock answers. Today that answer can drift out of sync with what the warehouse and POS actually show. This prototype demonstrates the interaction pattern that fixes that: one shared feed that both the warehouse and the support tool read from, so an agent's answer reflects the same number the warehouse just saw.

It's a single HTML file with all CSS and JavaScript inline. Open it in any browser, no install or server needed.

## What it does

**Support lookup**
Type a product name or SKU and get an answer card showing stock status (in stock, low stock, out of stock), quantity, warehouse location, and how fresh that number is ("synced 4s ago").

**Live sync simulation**
A background loop mimics real sales and restocks every few seconds, updating quantities automatically. A scrolling ticker at the top shows each event as it happens, similar to a shipping manifest.

**Manual push panel**
Pick a product, set a new quantity, and push it, simulating a POS sale or a warehouse receiving event. The support answer updates immediately, showing the sync loop working end to end.

**Outage simulator**
Toggle "Simulate outage" to see what happens when the feed stalls. The status indicator turns red, the ticker pauses, and the answer card flags the number as possibly stale instead of quietly showing an old figure as if it were current.

## How to use it

1. Open `index.html` in a browser.
2. Watch the ticker and inventory table update on their own as the simulated feed runs.
3. Search a product in the lookup box on the left and read the answer card.
4. Try the manual push panel on the right to force a stock change and see the answer update.
5. Toggle the outage button to see the stale data warning.

## What's simulated vs what's real

Everything currently lives in a JavaScript array in the browser. There is no real backend, no real POS connection, and no real warehouse system involved. This prototype exists to show the pattern and let people click through the experience, not to run in production.

## What production would need

1. A small backend (Flask or Node work well) that receives webhooks from NorthStar's actual POS and warehouse systems whenever stock changes.
2. A shared data store (Postgres or a similar database) that backend writes to. This becomes the single source of truth both systems read from.
3. The support tool's lookup calling that backend's API directly, ideally over a websocket, so answers update without a page refresh.
4. Basic monitoring on the sync connection itself, so a stalled feed gets flagged to the team, not just to whoever happens to be looking at the support tool.

## File

- `index.html` — the full prototype, self contained.
