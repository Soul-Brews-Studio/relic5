# hub-switch: run the relic5 hub on m5, switch back to white any time

Built 2026-11-13 (Nat: "make relic5 run on m5, just stop white and ready to switch back any time").
Clients keep `RELIC5_URL=http://white.follow-rankine.ts.net:8795`; nothing changes on them.

| File | Where it lives | What it does |
|---|---|---|
| `relic5-hub-switch` | white `~/.local/bin/` | `m5`: check m5 answers, stop `app-serve-1`, start the Caddy door. `white`: stop the door, pull `logs/`, `parts/m5/`, `vectors/` back from m5, start serve, index. `status`. |
| `Caddyfile` | white `~/relic5/switch/` | The door on white :8795 (tailnet IP + loopback) -> m5:8795, Host rewritten. |
| `relic5-m5-hub` | m5 `~/.local/bin/`, pm2 `relic5-hub` | `relic5 serve --root ~/relic5` on loopback + m5's tailnet IP, the hashed tokens copied from white (0600). |
| `relic5-m5-cycle` | m5 `~/.local/bin/`, pm2 `relic5-cycle` (every 30 min) | Pull white's parts (except `parts/m5`) and other dirs, `relic5 import` into the m5 hub (ANE embed), index BM25 + vectors. |
| `relic5-index-shim` | m5 `~/relic5/app/.venv/bin/relic5` | Old path the import used before `RELIC5_HUB_INDEX` (#291); unused now. |

## Why the door decides who gets in
m5 sees every forwarded caller as white (owner nat), which its tailnet door admits without a token. So the Caddyfile
admits only: the tailnet owner's own nodes (listed at switch time, minus the public droplet tailnet-gw by its tailnet IP)
and loopback callers with a loopback Host. Any `Cf-Connecting-Ip` gets 403, so cloudflared on white never inherits
"white". Loopback :8796 (tailscale serve :443) stays closed: HTTPS on the tailnet and the public MCP fail closed.

## Known limits
- After a white reboot while switched, the door is gone and serve stays stopped: run `relic5-hub-switch white`.
- pm2 on m5 comes back through a user LaunchAgent (`io.keymetrics.pm2.beta`), so only after `beta` logs in.
- white's own sessions reach the hub only when white's `relic-chain` runs (it pushes to white; the cycle pulls).
