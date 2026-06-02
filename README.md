# Dynamos ⚡ — Server Status Dashboard

A self-contained, real-time server monitoring portal. Collects system metrics and renders them in a clean, dark-themed dashboard.

## Live Demo

The dashboard runs at: **https://iiot1004.com/dynamos/**

## Features

| Metric | Description |
|---|---|
| 🧠 **CPU** | Real-time usage gauge, core count, load average (1/5/15m), temperature |
| 💾 **Memory** | Used/Available/Total RAM, swap usage with color-coded progress bars |
| 💿 **Disk** | Physical filesystem usage (ext4/xfs/btrfs) |
| ⏱️ **Uptime** | System uptime, kernel version, platform info |
| 🌐 **Network** | Hostname, IP addresses, TCP connections, per-interface traffic (RX/TX in GB) |
| ⚙️ **Services** | Live status for Apache, OpenClaw Gateway, Node-RED, MQTT proxy |
| 🐳 **Docker** | Container counts (running/total) and images |
| 📊 **Processes** | Top 6 processes sorted by CPU usage |

## How It Works

1. **Collector** (`dynamos-status.py`) — Python3 script that reads `/proc`, `/sys`, and system commands to gather metrics. Outputs JSON.
2. **Schedule** — Runs via cron every 30 seconds, writes `status.json` to the web root.
3. **Dashboard** (`dynamos/index.html`) — Pure HTML/CSS/JS with no external dependencies. Auto-refreshes every 10 seconds by polling `status.json`.

## Files

```
dynamos/
  index.html        # Dashboard UI (self-contained)
dynamos-status.py   # System metrics collector
```

## Requirements

- Python 3
- Apache or any static file server
- Standard Linux `/proc` filesystem

## Deployment

1. Put `dynamos/` in your web server's document root
2. Schedule `dynamos-status.py` via cron (every 30s recommended):
   ```cron
   * * * * * /path/to/dynamos-status.py
   * * * * * sleep 30 && /path/to/dynamos-status.py
   ```
3. Open `https://your-server/dynamos/`
