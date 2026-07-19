# Yahoo Finance IDX Live Stream Debug Tool

This is a non-production verification tool for checking whether Yahoo Finance's
`yfinance.AsyncWebSocket` emits timely updates for IDX `.JK` symbols. Its ticks are
not written to PostgreSQL and are not consumed by strategies, rankings, positions,
alerts, or the scheduler.

## Run

Deploy the normal API and frontend containers:

```bash
sudo -n ./deploy.sh
```

Open the live chart:

```text
http://localhost:21231/debug/live
```

The browser connects directly to the API SSE endpoint on port `21235`:

```bash
curl -N http://localhost:21235/stocks/BBCA.JK/live
```

Inspect the latest in-memory ticks, connection status, and subscriber count:

```bash
curl http://localhost:21235/debug/live/ticks/BBCA.JK
```

Cross-check every received Yahoo tick in the backend log:

```bash
sudo -n docker compose logs -f app
```

Sunday, July 19, 2026 is outside IDX trading hours, so an empty stream during the
deployment verification is expected. For the most meaningful result, test on the
next weekday while IDX is active. The UI's
verification warning follows 09:00-11:30 and 13:30-15:00 WIB and appears after 30
seconds without a tick. `day_volume` is Yahoo's cumulative session volume, not the
size of an individual trade.

The API keeps at most 10,000 ticks per symbol in memory. All debug data disappears
when the API container restarts.

## Session analytics

The dashboard can collect a browser-only verification session for 5, 15, 30, or
60 minutes. A finished session reports p50/p95/max source latency, p50/p95/max
inter-tick gap, stale gaps above 30 seconds, and a transparent verdict:

- `Insufficient Data`: unfinished session or fewer than 20 ticks.
- `Healthy`: latency p95 at most 5 seconds and gap p95 at most 15 seconds.
- `Delayed`: latency p95 above 5 seconds without unreliable gap behavior.
- `Unreliable`: gap p95 above the healthy range, gap p95 above 30 seconds, at
  least three stale gaps, or browser storage truncation.

Export buttons download the complete browser session as JSON and tick rows as CSV.
Reloading the page clears an unexported session. The browser retains at most
100,000 session ticks and marks the result truncated if that limit is reached.
