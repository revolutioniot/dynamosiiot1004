#!/usr/bin/env python3
"""
Dynamos Server Status Collector
Gathers system metrics and writes status.json for the dashboard.
Runs via cron every 30 seconds.
"""

import json
import os
import subprocess
import time
import socket
import platform
from pathlib import Path

OUTPUT = "/var/www/html/dynamos/status.json"
LOCK = "/tmp/dynamos-status.lock"

def run(cmd):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
        return r.stdout.strip()
    except:
        return "N/A"

def get_cpu():
    """CPU stats from /proc"""
    try:
        with open("/proc/stat") as f:
            line = f.readline().strip().split()
        # user nice system idle iowait irq softirq steal
        vals = [int(v) for v in line[1:]]
        total = sum(vals)
        idle = vals[3]
        return {
            "cores": os.cpu_count() or 1,
            "total_jiffies": total,
            "idle_jiffies": idle
        }
    except:
        return {"cores": 1, "total_jiffies": 0, "idle_jiffies": 0}

def get_cpu_percent():
    """Calculate CPU usage from /proc/stat delta"""
    try:
        with open("/proc/stat") as f:
            l1 = [int(v) for v in f.readline().strip().split()[1:]]
        time.sleep(0.1)
        with open("/proc/stat") as f:
            l2 = [int(v) for v in f.readline().strip().split()[1:]]
        total_delta = sum(l2) - sum(l1)
        idle_delta = (l2[3] - l1[3])
        if total_delta == 0:
            return 0
        return round(100 * (1 - idle_delta / total_delta), 1)
    except:
        return 0

def get_memory():
    """Memory stats"""
    try:
        with open("/proc/meminfo") as f:
            mem = {}
            for line in f:
                parts = line.split()
                if parts[0].rstrip(":") in ["MemTotal", "MemFree", "MemAvailable", "Buffers", "Cached", "SwapTotal", "SwapFree", "SReclaimable"]:
                    mem[parts[0].rstrip(":")] = int(parts[1])  # kB
        total = mem.get("MemTotal", 0)
        available = mem.get("MemAvailable", 0)
        free = mem.get("MemFree", 0)
        buffers = mem.get("Buffers", 0)
        cached = mem.get("Cached", 0)
        sreclaimable = mem.get("SReclaimable", 0)
        
        # Calculate used = total - (free + buffers + cached + sreclaimable)
        # Or simpler: total - available
        used = total - available
        
        swap_total = mem.get("SwapTotal", 0)
        swap_free = mem.get("SwapFree", 0)
        swap_used = swap_total - swap_free
        
        return {
            "total_gb": round(total / 1048576, 1),
            "used_gb": round(used / 1048576, 1),
            "available_gb": round(available / 1048576, 1),
            "free_gb": round(free / 1048576, 1),
            "percent_used": round(100 * used / total, 1) if total else 0,
            "swap_total_gb": round(swap_total / 1048576, 1),
            "swap_used_gb": round(swap_used / 1048576, 1),
            "swap_percent": round(100 * swap_used / swap_total, 1) if swap_total else 0
        }
    except:
        return {"total_gb": 0, "used_gb": 0, "available_gb": 0, "percent_used": 0, "swap_total_gb": 0, "swap_used_gb": 0, "swap_percent": 0}

def get_disk():
    """Disk usage for physical filesystems only"""
    try:
        r = run("df -B1 --type=ext4 --type=xfs --type=btrfs --type=zfs --output=target,size,used,avail,pcent,fstype 2>/dev/null | tail -n +2")
        if not r or r == "N/A":
            # Fallback: filter manually
            r = run("df -B1 --output=target,size,used,avail,pcent,fstype 2>/dev/null | tail -n +2")
        mounts = []
        seen = set()
        for line in r.strip().split("\n"):
            parts = line.rsplit(None, 5)
            if len(parts) >= 5:
                mount = parts[0]
                fstype = parts[5] if len(parts) >= 6 else ""
                # Only physical or meaningful mounts
                if (fstype in ("ext4", "xfs", "btrfs", "zfs", "ext3", "ext2") or
                    mount in ("/", "/var", "/home", "/opt", "/srv", "/data", "/mnt") or
                    mount.startswith("/mnt/") or mount.startswith("/data/")):
                    if mount in seen:
                        continue
                    seen.add(mount)
                    total = int(parts[1])
                    used = int(parts[2])
                    mounts.append({
                        "mount": mount,
                        "total_gb": round(total / 1073741824, 1),
                        "used_gb": round(used / 1073741824, 1),
                        "available_gb": round(int(parts[3]) / 1073741824, 1),
                        "percent_used": round(100 * used / total, 1) if total else 0
                    })
        if not mounts:
            # Last resort: just show root
            r = run("df -B1 / 2>/dev/null | tail -1")
            parts = r.split()
            if len(parts) >= 4:
                total = int(parts[1])
                used = int(parts[2])
                mounts.append({
                    "mount": "/",
                    "total_gb": round(total / 1073741824, 1),
                    "used_gb": round(used / 1073741824, 1),
                    "available_gb": round(int(parts[3]) / 1073741824, 1),
                    "percent_used": round(100 * used / total, 1) if total else 0
                })
        return mounts
    except:
        return [{"mount": "/", "total_gb": 0, "used_gb": 0, "available_gb": 0, "percent_used": 0}]

def get_load():
    """Load average"""
    try:
        with open("/proc/loadavg") as f:
            parts = f.read().strip().split()
        return {
            "1min": float(parts[0]),
            "5min": float(parts[1]),
            "15min": float(parts[2]),
            "processes": parts[3],
            "cores": os.cpu_count() or 1
        }
    except:
        return {"1min": 0, "5min": 0, "15min": 0, "processes": "0/0", "cores": 1}

def get_network():
    """Network I/O and connection counts"""
    try:
        # Total connections
        connt = run("ss -tun 2>/dev/null | wc -l")
        tcp_total = run("ss -t 2>/dev/null | wc -l")
        tcp_listen = run("ss -tln 2>/dev/null | wc -l")
        tcp_estab = run("ss -t state established 2>/dev/null | wc -l")
        
        # Network interfaces
        ifaces = []
        try:
            with open("/proc/net/dev") as f:
                lines = f.readlines()[2:]
            for line in lines:
                parts = line.strip().split()
                iface = parts[0].rstrip(":")
                if iface == "lo":
                    continue
                rx_bytes = int(parts[1])
                tx_bytes = int(parts[9])
                rx_packets = int(parts[2])
                tx_packets = int(parts[10])
                ifaces.append({
                    "name": iface,
                    "rx_mb": round(rx_bytes / 1048576, 1),
                    "tx_mb": round(tx_bytes / 1048576, 1),
                    "rx_gb": round(rx_bytes / 1073741824, 2),
                    "tx_gb": round(tx_bytes / 1073741824, 2),
                    "rx_packets": rx_packets,
                    "tx_packets": tx_packets
                })
        except:
            pass
        
        # Hostname & IPs
        hostname = socket.gethostname()
        ips = []
        try:
            for iface in ifaces:
                ip = run(f"ip -4 addr show {iface['name']} 2>/dev/null | grep inet | awk '{{print $2}}'")
                if ip and ip != "N/A":
                    ips.append(f"{iface['name']}: {ip}")
        except:
            pass

        return {
            "connections_total": connt,
            "tcp_total": tcp_total,
            "tcp_listen": tcp_listen,
            "tcp_established": tcp_estab,
            "interfaces": ifaces,
            "hostname": hostname,
            "ips": ips
        }
    except:
        return {"connections_total": 0, "tcp_total": 0, "tcp_listen": 0, "tcp_established": 0, "interfaces": [], "hostname": "unknown", "ips": []}

def get_services():
    """Check status of key services - uses both systemd and port checks"""
    check_port = lambda p: run(f"ss -tlnp 2>/dev/null | grep -qE ':{p} ' && echo 'running' || echo 'stopped'")
    check_systemd = lambda s: run(f"systemctl is-active {s} 2>/dev/null")
    check_process = lambda n: run(f"pgrep -f '{n}' 2>/dev/null | head -1 && echo 'running' || echo 'stopped'")
    
    # Detect web server
    web = check_systemd("apache2")
    if web == "N/A" or web not in ("active", "inactive"):
        web = check_port("80")
    
    return {
        "web_server": {"status": web, "port": "80/443", "purpose": "Apache HTTP Server"},
        "openclaw_gateway": {"status": check_port("18789"), "port": "18789", "purpose": "OpenClaw AI Gateway"},
        "node_red": {"status": check_port("1880"), "port": "1880", "purpose": "Node-RED Flow Engine"},
        "mqtt_proxy": {"status": check_port("9001"), "port": "9001", "purpose": "MQTT WebSocket Proxy"},
    }

def get_processes():
    """Top processes by CPU"""
    try:
        r = run("ps aux --sort=-%cpu 2>/dev/null | head -8 | tail -6")
        procs = []
        for line in r.strip().split("\n"):
            parts = line.split(None, 10)
            if len(parts) >= 11:
                procs.append({
                    "user": parts[0],
                    "cpu": parts[2],
                    "mem": parts[3],
                    "cmd": parts[10][:60]
                })
        return procs
    except:
        return []

def get_uptime():
    """System uptime"""
    try:
        with open("/proc/uptime") as f:
            uptime_seconds = float(f.read().split()[0])
        days = int(uptime_seconds // 86400)
        hours = int((uptime_seconds % 86400) // 3600)
        minutes = int((uptime_seconds % 3600) // 60)
        return {
            "seconds": uptime_seconds,
            "days": days,
            "hours": hours,
            "minutes": minutes,
            "display": f"{days}d {hours}h {minutes}m"
        }
    except:
        return {"seconds": 0, "days": 0, "hours": 0, "minutes": 0, "display": "N/A"}

def get_temperature():
    """CPU/System temperature"""
    temps = []
    try:
        # Try thermal zones
        for tz in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
            try:
                raw = int(tz.read_text().strip())
                name = (tz.parent / "type").read_text().strip() if (tz.parent / "type").exists() else tz.name
                temps.append({"name": name, "temp_c": round(raw / 1000, 1)})
            except:
                pass
    except:
        pass
    return temps

def get_docker():
    """Docker info if available"""
    try:
        r = run("docker info --format '{{.Containers}} {{.Running}} {{.Images}}' 2>/dev/null")
        if r != "N/A" and r:
            parts = r.split()
            return {
                "containers_total": int(parts[0]) if parts[0].isdigit() else 0,
                "containers_running": int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0,
                "images": int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0,
                "installed": True
            }
    except:
        pass
    return {"installed": False, "containers_total": 0, "containers_running": 0, "images": 0}

def main():
    try:
        # Create lock to prevent concurrent runs
        if os.path.exists(LOCK):
            age = time.time() - os.path.getmtime(LOCK)
            if age < 10:  # Less than 10s old, skip
                return
        Path(LOCK).touch()
        
        data = {
            "timestamp": int(time.time()),
            "datetime": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "system": {
                "hostname": socket.gethostname(),
                "platform": platform.platform(),
                "kernel": platform.release(),
                "architecture": platform.machine(),
                "python_version": platform.python_version(),
                "uptime": get_uptime()
            },
            "cpu": {
                "percent": get_cpu_percent(),
                "cores": os.cpu_count() or 1,
                "load": get_load(),
                "temperature": get_temperature()
            },
            "memory": get_memory(),
            "disk": get_disk(),
            "network": get_network(),
            "services": get_services(),
            "processes": get_processes(),
            "docker": get_docker()
        }
        
        os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
        with open(OUTPUT, "w") as f:
            json.dump(data, f, indent=2)
        
        os.unlink(LOCK)
    except Exception as e:
        try:
            os.unlink(LOCK)
        except:
            pass
        # Write error status
        with open(OUTPUT, "w") as f:
            json.dump({"error": str(e), "timestamp": int(time.time())}, f)

if __name__ == "__main__":
    main()
