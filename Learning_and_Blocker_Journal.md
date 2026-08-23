# Learning & Blocker Journal
### Project: NorthStar Retail Co. — Live Inventory Sync Prototype
### Developer: David Ndirangu

This journal records what I consulted, what broke, and how I worked through each blocker without asking anyone for help along the way.
It covers the build of the inventory sync prototype (`index.html`).

---

## 1. Scope and starting point

The brief was to prototype a live inventory sync service so a support tool's "is this in stock?" answers stay accurate. I had basic HTML, JavaScript, and CSS skills going in, and no prior experience simulating a real time feed in the browser. The plan was a single self contained HTML file: a support facing lookup panel, a simulated warehouse and POS feed, a manual override 
to demonstrate the sync propagating, and a way to show what happens when the feed goes stale.

---

## 2. Resources consulted

| Topic | Resource | Why I needed it |
|---|---|---|
| JS `setInterval` / `clearInterval` patterns | MDN Web Docs, Window.setInterval() | To run the simulated feed on a timer without leaking multiple intervals on repeated toggles |
| CSS keyframe animation for a continuously scrolling ticker | MDN Web Docs, CSS `@keyframes` and `animation-play-state` | Needed the ticker to loop seamlessly and pause cleanly during a simulated outage, rather than jumping or restarting |
| Date and time formatting in vanilla JS | MDN Web Docs, `Date` object methods | To build a lightweight "time ago" function without pulling in a library like day.js for a single file prototype |
| CSS selector specificity and cascade order | MDN Web Docs, CSS specificity | The frontend design guidance I was working from specifically warned about type selectors and class selectors cancelling each other out. I referred to this while restructuring the table and panel CSS |
| Debounced vs live search suggestions | General search on autocomplete UX patterns | Deciding whether to filter on every keystroke or debounce it. Went with live filtering since the dataset is only seven items |
| Google Fonts pairing (Barlow Condensed, IBM Plex Sans, IBM Plex Mono) | Google Fonts documentation | Needed a condensed display face for the manifest and masthead feel, a body face for prose, and a monospace face for SKUs and timestamps to read like data rather than copy |
| Accessible focus states | MDN Web Docs, `:focus` styling | Made sure the lookup input had a visible focus ring rather than relying on the browser default, which some browsers suppress |

---

## 2a. Design guidance interpretation

Before writing any CSS, I reviewed the frontend design guidance I was building against. Two decisions came directly from that review rather than from trial and error later:

- I deliberately avoided the near cream background plus terracotta accent combination and the near black background plus single bright accent combination, since both were flagged as default looks that show up regardless of subject. I chose a slate ink and warm paper palette with a mustard amber accent instead, closer to warehouse signage than to either default.
- I picked one signature element up front, the scrolling manifest ticker, and kept the rest of the layout restrained around it, rather than adding animation in multiple places.

This meant fewer redesigns later, since the color and type decisions were fixed before the table and panel components were built.

---

## 3. Error log

### 3.1 Ticker duplicated the wrong way and stuttered on loop
**Error:** The scrolling ticker visibly jumped at the seam where the animation looped back to the start.
**Cause:** I initially rendered the ticker items once and animated `translateX` from `0` to `-100%` of a container that was sized to fit exactly the visible items, so the moment it reset there was a visible blank gap before the next cycle began.
**Resolution:** I rendered the same set of ticker items twice back to back inside the scrolling track, so the second copy is already in position to continue the illusion when the first copy scrolls out. This is a standard marquee trick but I had to work out the math myself for the padding and animation duration to keep the speed consistent regardless of how many products were in the array.

### 3.2 Multiple simulated feeds running after toggling outage mode repeatedly
**Error:** After several outage toggles, stock numbers were changing faster than the visible 3.5 second interval, as if two feeds were running.
**Cause:** I had briefly experimented with re-calling `setInterval(simulateEvent, 3500)` inside the toggle handler to "restart" the feed on reconnect, without clearing the original interval first. Each reconnect stacked another interval on top of the last.
**Resolution:** Rather than starting and stopping the interval at all, I left a single interval running for the lifetime of the page and instead gated the actual event logic behind a `syncConnected` boolean at the top of `simulateEvent()`. The interval always fires, but it does nothing while disconnected. This was simpler and removed the whole class of stacking bugs.

### 3.3 Suggestion list stayed open after a product was selected
**Error:** Clicking a suggestion filled the search box correctly but the dropdown stayed visible underneath.
**Cause:** I was calling `renderAnswer(p)` on click but not explicitly removing the `show` class from the suggestions container in that same handler.
**Resolution:** Added `suggestionsEl.classList.remove('show')` directly in both the click handler and the Enter key handler, rather than assuming a shared function would cover both paths. Also added a document level click listener that closes the dropdown when a click lands outside the input, since testing showed clicking anywhere else on the page left it open too.

### 3.4 Freshness label went stale looking even when sync was healthy
**Error:** Early on, the "synced Xs ago" label under the answer card only updated when a lookup was performed, so if an agent left an answer open for a minute it looked outdated even while the feed was running fine.
**Cause:** The freshness text was only being recalculated inside `renderAnswer()`, which only ran on a new search or a stock change to that specific product.
**Resolution:** Added a one second `setInterval` purely for the clock display, separate from the feed simulation interval, that re-renders the freshness line and the header timestamp continuously. Kept it deliberately separate from the feed logic so a slow clock tick could never be mistaken for a slow sync.

### 3.5 Table quantity flash animation applied to every row
**Error:** The intended behaviour was a brief highlight flash on only the row that just changed. Instead every row flashed on every update.
**Cause:** I was adding the `qty-flash` class inside the render loop without a conditional check, so it was applied unconditionally to every `<td>`.
**Resolution:** Passed the id of the product that just changed into `renderTable(flashId)` and only appended the class when a row's id matched. This meant threading the changed product's id through from both the simulated event handler and the manual override handler, rather than hardcoding it in one place.

### 3.6 Manual override accepted invalid input silently
**Error:** Typing a negative number or leaving the quantity field blank and pressing the push button did nothing, with no indication why.
**Cause:** No validation existed on the input before it was parsed and applied.
**Resolution:** Added an `isNaN` and negative number guard before applying the update, and return focus to the input field when the value is rejected, so the empty or invalid state is at least visible through the cursor landing back there. This is a minimal fix. A production version would need a visible inline error message rather than a silent focus return.

---

## 4. Blockers resolved without direct supervision

**Blocker: deciding how "realistic" the simulation needed to be.**
There was no one to ask whether random stock movement every few seconds was too fast or too slow to read as believable. I resolved this by testing several interval lengths against my own judgement of how quickly a support agent could plausibly refresh a lookup, and settled on 3.5 seconds as fast enough to demonstrate liveness without making the numbers unreadable mid animation.

**Blocker: how to represent an outage without inventing a second UI.**
I initially considered building a separate "system status" page. Instead I worked through the constraint that everything needed to live in one file with no routing, and resolved it by having the same pulse indicator, ticker, and answer card all react to a single `syncConnected` state, so one toggle demonstrates the failure mode across the whole interface rather than in an isolated corner.

**Blocker: keeping the CSS from becoming unreadable as panels were added.**
As the panel count grew, class names started overlapping in intent, for example table status tags and answer card status colors were near duplicates. I resolved this by consolidating the status color logic into a single naming convention, `instock` / `low` / `out`, reused consistently across the tag, the answer card, and the ticker item color, so a status change in one place could not silently diverge from another.

**Blocker: verifying the file worked without a dev server.**
Since this was meant to be opened directly as a static file, I could not assume access to browser dev tools debugging in the way I would with a running local server. I worked through this by keeping functions small and testing incrementally in the browser console as the file was built, checking `products` state directly, rather than writing the whole script and debugging at the end.

---

## 5. What I would do differently next time

- Write the freshness clock and the feed simulation as two separate named functions from the very start, rather than discovering the coupling problem in section 3.4 partway through.
- Add basic keyboard accessibility testing earlier rather than after the suggestion dropdown was already working with the mouse.
- Sketch the status color naming convention before writing any CSS, since retrofitting consistent naming across three components cost more time than deciding it up front would have.

---

## 6. Outcome

The prototype runs standalone, demonstrates the full loop from simulated warehouse event to support facing answer, and exposes a stale data state honestly instead of hiding it. The open item carried into the README is the same one noted there: this is a simulation of the pattern, not a connection to a real POS or warehouse system, and that boundary is stated plainly rather than implied to be more finished than it is.
