#!/usr/bin/env python3
"""
Aquarium Light Controller - Gradual dimming for Magic Home LED controllers.

Controls Blue (R), White (G), and UV (B) channels independently with
smooth transitions between brightness levels throughout the day.
"""

import copy
import json
import math
import time
import threading
import logging
import os
import signal
import sys
from datetime import datetime
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
from flux_led import WifiLedBulb

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CONFIG_PATH = os.environ.get("CONFIG_PATH", "/data/config.json")
WEB_PORT = int(os.environ.get("WEB_PORT", "8080"))
API_PORT = int(os.environ.get("API_PORT", "8081"))

BUILD_SHA = os.environ.get("BUILD_SHA", "dev")
BUILD_VERSION = os.environ.get("BUILD_VERSION", "local")
BUILD_DATE = os.environ.get("BUILD_DATE", "unknown")
BUILD_INFO = {
    "sha": BUILD_SHA,
    "short_sha": BUILD_SHA[:7] if BUILD_SHA != "dev" else "dev",
    "version": BUILD_VERSION,
    "date": BUILD_DATE,
}

DEFAULT_CONFIG = {
    "controller_ip": "192.168.1.100",
    "transition_minutes": 30,
    "update_interval_seconds": 10,
    "channel_map": {
        "blue": "R",
        "white": "G",
        "uv": "B"
    },
    "schedule": [
        {"time": "07:00", "blue": 25, "white": 0,   "uv": 15, "label": "Amanhecer - azul suave"},
        {"time": "08:00", "blue": 40, "white": 15,  "uv": 25, "label": "Manhã cedo"},
        {"time": "10:00", "blue": 60, "white": 50,  "uv": 50, "label": "Manhã"},
        {"time": "12:00", "blue": 80, "white": 100, "uv": 80, "label": "Meio-dia - pico"},
        {"time": "15:00", "blue": 60, "white": 50,  "uv": 50, "label": "Tarde"},
        {"time": "17:00", "blue": 35, "white": 10,  "uv": 25, "label": "Entardecer"},
        {"time": "18:00", "blue": 15, "white": 0,   "uv": 10, "label": "Crepúsculo"},
        {"time": "18:30", "blue": 0,  "white": 0,   "uv": 0,  "label": "Desligado"},
    ]
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger("aquarium")

# ---------------------------------------------------------------------------
# Config management
# ---------------------------------------------------------------------------

def load_config() -> dict:
    """Load config from file, creating default if not found."""
    path = Path(CONFIG_PATH)
    if path.exists():
        try:
            with open(path) as f:
                cfg = json.load(f)
            log.info("Config loaded from %s", CONFIG_PATH)
            return cfg
        except Exception as e:
            log.warning("Error loading config: %s — using defaults", e)
    default = copy.deepcopy(DEFAULT_CONFIG)
    save_config(default)
    return default


def save_config(cfg: dict):
    """Persist config to file."""
    path = Path(CONFIG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    log.info("Config saved to %s", CONFIG_PATH)

# ---------------------------------------------------------------------------
# Schedule utilities (single source of truth for interpolation logic)
# ---------------------------------------------------------------------------

def parse_time(t: str) -> float:
    """Convert 'HH:MM' to minutes since midnight."""
    parts = t.strip().split(":")
    return int(parts[0]) * 60 + int(parts[1])


def interpolate_schedule(now: float, schedule: list, trans: float) -> dict:
    """
    Compute brightness levels at a given minute using cosine ease-in-out.

    This is the single implementation shared by the control loop and the
    preview API endpoint, eliminating duplicate logic.
    """
    schedule = sorted(schedule, key=lambda s: parse_time(s["time"]))
    if not schedule:
        return {"blue": 0, "white": 0, "uv": 0}

    first_time = parse_time(schedule[0]["time"])
    last_time = parse_time(schedule[-1]["time"])

    if now < first_time - trans:
        return {"blue": 0, "white": 0, "uv": 0}

    if now >= last_time:
        last = schedule[-1]
        return {"blue": last["blue"], "white": last["white"], "uv": last["uv"]}

    for i, point in enumerate(schedule):
        target_time = parse_time(point["time"])
        prev_levels = (
            {"blue": schedule[i-1]["blue"], "white": schedule[i-1]["white"], "uv": schedule[i-1]["uv"]}
            if i > 0
            else {"blue": 0, "white": 0, "uv": 0}
        )
        curr_levels = {"blue": point["blue"], "white": point["white"], "uv": point["uv"]}
        transition_start = target_time - trans

        if now < target_time:
            if now >= transition_start:
                elapsed = now - transition_start
                progress = min(1.0, elapsed / trans) if trans > 0 else 1.0
                smooth = (1 - math.cos(progress * math.pi)) / 2.0
                return {
                    ch: prev_levels[ch] + (curr_levels[ch] - prev_levels[ch]) * smooth
                    for ch in ("blue", "white", "uv")
                }
            return prev_levels

    last = schedule[-1]
    return {"blue": last["blue"], "white": last["white"], "uv": last["uv"]}

# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------

def validate_config(cfg: dict) -> list:
    """Validate a config dict. Returns a list of error messages (empty = valid)."""
    errors = []

    if not isinstance(cfg, dict):
        return ["config must be a JSON object"]

    if "controller_ip" in cfg:
        ip = cfg["controller_ip"]
        if not isinstance(ip, str) or not ip.strip():
            errors.append("controller_ip must be a non-empty string")

    if "transition_minutes" in cfg:
        t = cfg["transition_minutes"]
        if not isinstance(t, (int, float)) or t < 0 or t > 180:
            errors.append("transition_minutes must be a number between 0 and 180")

    if "update_interval_seconds" in cfg:
        u = cfg["update_interval_seconds"]
        if not isinstance(u, (int, float)) or u < 2 or u > 3600:
            errors.append("update_interval_seconds must be a number between 2 and 3600")

    if "channel_map" in cfg:
        cm = cfg["channel_map"]
        if not isinstance(cm, dict):
            errors.append("channel_map must be an object")
        else:
            for k in ("blue", "white", "uv"):
                if k in cm and cm[k] not in ("R", "G", "B"):
                    errors.append(f"channel_map.{k} must be 'R', 'G', or 'B'")

    if "schedule" in cfg:
        sched = cfg["schedule"]
        if not isinstance(sched, list):
            errors.append("schedule must be an array")
        elif len(sched) == 0:
            errors.append("schedule must have at least one entry")
        else:
            for idx, entry in enumerate(sched):
                if not isinstance(entry, dict):
                    errors.append(f"schedule[{idx}] must be an object")
                    continue
                for field in ("time", "blue", "white", "uv"):
                    if field not in entry:
                        errors.append(f"schedule[{idx}] missing field '{field}'")
                if "time" in entry:
                    try:
                        parse_time(entry["time"])
                    except (ValueError, IndexError):
                        errors.append(f"schedule[{idx}].time '{entry['time']}' is not a valid HH:MM value")
                for ch in ("blue", "white", "uv"):
                    if ch in entry:
                        v = entry[ch]
                        if not isinstance(v, (int, float)) or v < 0 or v > 100:
                            errors.append(f"schedule[{idx}].{ch} must be between 0 and 100")

    return errors

# ---------------------------------------------------------------------------
# Light controller
# ---------------------------------------------------------------------------

class AquariumController:
    def __init__(self):
        self.config = load_config()
        self.bulb = None
        self.running = False
        self.current_levels = {"blue": 0, "white": 0, "uv": 0}
        self.target_levels = {"blue": 0, "white": 0, "uv": 0}
        self.status = "initializing"
        self.last_error = None
        self.lock = threading.Lock()

    def connect(self) -> bool:
        """Connect to the Magic Home controller."""
        ip = self.config.get("controller_ip", "192.168.1.100")
        try:
            self.bulb = WifiLedBulb(ip)
            self.bulb.refreshState()
            log.info("Connected to controller at %s (model: %s)", ip, self.bulb.model)
            self.status = "connected"
            self.last_error = None
            return True
        except Exception as e:
            log.error("Failed to connect to %s: %s", ip, e)
            self.status = "disconnected"
            self.last_error = str(e)
            self.bulb = None
            return False

    def request_reconnect(self):
        """
        Request reconnection on the next control loop iteration (thread-safe).

        Acquires the lock so _apply_levels cannot be mid-execution when we
        null out self.bulb, avoiding a race condition.
        """
        with self.lock:
            self.bulb = None
            self.status = "reconnecting"
        log.info("Reconnect requested")

    def _pct_to_byte(self, pct: float) -> int:
        """Convert 0-100 percentage to 0-255 byte."""
        return max(0, min(255, int(round(pct / 100.0 * 255))))

    def _apply_levels(self, blue: float, white: float, uv: float):
        """Send RGB values to the controller based on channel mapping."""
        if not self.bulb:
            return

        cmap = self.config.get("channel_map", {"blue": "R", "white": "G", "uv": "B"})
        channels = {"R": 0, "G": 0, "B": 0}
        channels[cmap.get("blue", "R")] = self._pct_to_byte(blue)
        channels[cmap.get("white", "G")] = self._pct_to_byte(white)
        channels[cmap.get("uv", "B")] = self._pct_to_byte(uv)

        try:
            all_off = blue <= 0 and white <= 0 and uv <= 0
            if all_off:
                self.bulb.turnOff()
            else:
                if not self.bulb.isOn():
                    self.bulb.turnOn()
                    time.sleep(0.3)
                self.bulb.setRgb(channels["R"], channels["G"], channels["B"])

            self.current_levels = {"blue": blue, "white": white, "uv": uv}
            self.last_error = None
        except Exception as e:
            log.error("Error applying levels: %s", e)
            self.last_error = str(e)
            self.bulb = None
            self.status = "disconnected"

    def _now_minutes(self) -> float:
        """Current time as minutes since midnight."""
        now = datetime.now()
        return now.hour * 60 + now.minute + now.second / 60.0

    def compute_target(self) -> dict:
        """Compute the target brightness for each channel at the current time."""
        return interpolate_schedule(
            self._now_minutes(),
            self.config["schedule"],
            self.config.get("transition_minutes", 30)
        )

    def run(self):
        """Main control loop."""
        self.running = True
        log.info("Controller started")

        reconnect_delay = 10
        while self.running:
            if not self.bulb:
                if not self.connect():
                    log.warning("Retrying connection in %ds...", reconnect_delay)
                    time.sleep(reconnect_delay)
                    reconnect_delay = min(reconnect_delay * 2, 120)
                    continue
                reconnect_delay = 10

            target = self.compute_target()
            self.target_levels = target

            with self.lock:
                self._apply_levels(target["blue"], target["white"], target["uv"])

            interval = self.config.get("update_interval_seconds", 10)
            # Only mark as running if the bulb is still connected after apply.
            # _apply_levels sets status="disconnected" on error; preserving that
            # here ensures the dashboard reflects the real state.
            if self.bulb:
                self.status = "running"
            time.sleep(interval)

    def stop(self):
        self.running = False
        log.info("Controller stopping...")

    def get_state(self) -> dict:
        """Return current state for the API."""
        schedule = sorted(self.config["schedule"], key=lambda s: parse_time(s["time"]))
        now = datetime.now()
        return {
            "status": self.status,
            "time": now.strftime("%H:%M:%S"),
            "current_levels": {k: round(v, 1) for k, v in self.current_levels.items()},
            "target_levels": {k: round(v, 1) for k, v in self.target_levels.items()},
            "controller_ip": self.config.get("controller_ip"),
            "transition_minutes": self.config.get("transition_minutes", 30),
            "update_interval_seconds": self.config.get("update_interval_seconds", 10),
            "schedule": schedule,
            "last_error": self.last_error,
            "build": BUILD_INFO,
        }

    def update_config(self, new_config: dict):
        """Update configuration and save."""
        with self.lock:
            self.config.update(new_config)
            save_config(self.config)
            log.info("Config updated")

# ---------------------------------------------------------------------------
# API Server
# ---------------------------------------------------------------------------

controller = AquariumController()


class APIHandler(SimpleHTTPRequestHandler):
    """Minimal REST API for the controller."""

    def log_message(self, fmt, *args):
        pass

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send_json({})

    def do_GET(self):
        if self.path == "/api/state":
            self._send_json(controller.get_state())
        elif self.path == "/api/version":
            self._send_json(BUILD_INFO)
        elif self.path == "/api/config":
            self._send_json(controller.config)
        elif self.path == "/api/preview":
            preview = []
            schedule = controller.config["schedule"]
            trans = controller.config.get("transition_minutes", 30)
            for minute in range(0, 1440, 2):
                target = interpolate_schedule(minute, schedule, trans)
                preview.append({
                    "minute": minute,
                    "time": f"{minute // 60:02d}:{minute % 60:02d}",
                    **{k: round(v, 1) for k, v in target.items()}
                })
            self._send_json(preview)
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path == "/api/config":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length))
                errors = validate_config(body)
                if errors:
                    self._send_json({"error": "; ".join(errors)}, 400)
                    return
                controller.update_config(body)
                self._send_json({"ok": True})
            except json.JSONDecodeError as e:
                self._send_json({"error": f"JSON inválido: {e}"}, 400)
            except Exception as e:
                self._send_json({"error": str(e)}, 400)
        elif self.path == "/api/reconnect":
            controller.request_reconnect()
            self._send_json({"ok": True, "status": controller.status})
        else:
            self._send_json({"error": "not found"}, 404)

# ---------------------------------------------------------------------------
# Web server for static files (dashboard)
# ---------------------------------------------------------------------------

WEB_DIR = os.environ.get("WEB_DIR", "/app/web")


class WebHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_DIR, **kwargs)

    def log_message(self, fmt, *args):
        pass

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    log.info(
        "Build: version=%s sha=%s date=%s",
        BUILD_INFO["version"], BUILD_INFO["short_sha"], BUILD_INFO["date"],
    )

    ctrl_thread = threading.Thread(target=controller.run, daemon=True)
    ctrl_thread.start()

    api_server = HTTPServer(("0.0.0.0", API_PORT), APIHandler)
    api_thread = threading.Thread(target=api_server.serve_forever, daemon=True)
    api_thread.start()
    log.info("API server on port %d", API_PORT)

    web_server = HTTPServer(("0.0.0.0", WEB_PORT), WebHandler)
    log.info("Web dashboard on port %d", WEB_PORT)

    def shutdown(sig, frame):
        log.info("Shutting down...")
        controller.stop()
        api_server.shutdown()
        web_server.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    web_server.serve_forever()


if __name__ == "__main__":
    main()
