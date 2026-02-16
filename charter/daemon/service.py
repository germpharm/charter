"""Charter daemon service.

Runs as a background process that:
1. Periodically scans for AI tools on the machine
2. Logs detected tools to the hash chain
3. Serves the web dashboard on localhost
4. Can be installed as a system service (launchd/systemd)
"""

import json
import os
import platform
import shutil
import sys
import threading
import time

from charter.daemon.detector import detect_ai_tools, get_summary
from charter.identity import load_identity, append_to_chain

DEFAULT_PORT = 8374
SCAN_INTERVAL = 60


class CharterDaemon:
    """Main daemon process. Combines detection loop with web server."""

    def __init__(self, port=DEFAULT_PORT, scan_interval=SCAN_INTERVAL):
        self.port = port
        self.scan_interval = scan_interval
        self.running = False
        self._detection_log = []
        self._last_scan = None
        self._lock = threading.Lock()

    def start(self):
        """Start the daemon. Blocks until stopped."""
        self.running = True

        detector = threading.Thread(target=self._detection_loop, daemon=True)
        detector.start()

        self._start_web()

    def stop(self):
        """Signal the daemon to stop."""
        self.running = False

    def get_status(self):
        """Get current daemon state (thread-safe)."""
        with self._lock:
            return {
                "running": self.running,
                "port": self.port,
                "last_scan": self._last_scan,
                "detection_log": list(self._detection_log),
                "total_detected": len(self._detection_log),
            }

    def _detection_loop(self):
        """Background thread: scan for AI tools on interval."""
        while self.running:
            try:
                tools = detect_ai_tools()
                now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

                with self._lock:
                    self._last_scan = {
                        "tools": tools,
                        "scanned_at": now,
                    }

                    for tool in tools:
                        already_logged = any(
                            d["tool_id"] == tool["tool_id"]
                            for d in self._detection_log
                        )
                        if not already_logged:
                            self._detection_log.append(tool)
                            try:
                                append_to_chain("ai_tool_detected", {
                                    "tool": tool["name"],
                                    "vendor": tool["vendor"],
                                    "governable": tool["governable"],
                                })
                            except Exception:
                                pass
            except Exception:
                pass

            time.sleep(self.scan_interval)

    def _start_web(self):
        """Start the Flask web server."""
        try:
            from charter.web.app import create_app
            app = create_app(self)
            app.run(host="127.0.0.1", port=self.port, debug=False)
        except ImportError:
            print(
                "Flask not installed. Install with: "
                "pip install charter-governance[daemon]"
            )
            print("Daemon running without web UI. Detection loop active.")
            try:
                while self.running:
                    time.sleep(1)
            except KeyboardInterrupt:
                self.stop()


def run_serve(args):
    """CLI entry point for charter serve."""
    from charter import __version__

    port = getattr(args, "port", DEFAULT_PORT) or DEFAULT_PORT
    interval = getattr(args, "interval", SCAN_INTERVAL) or SCAN_INTERVAL

    identity = load_identity()
    if not identity:
        print("No identity found. Run 'charter init' first.")
        return

    daemon = CharterDaemon(port=port, scan_interval=interval)

    print(f"Charter Daemon v{__version__}")
    print(f"  Dashboard: http://127.0.0.1:{port}")
    print(f"  Detection: every {interval}s")
    print(f"  Identity:  {identity['alias']} ({identity['public_id'][:16]}...)")
    print()
    print("Press Ctrl+C to stop.")
    print()

    try:
        append_to_chain("daemon_started", {
            "port": port,
            "scan_interval": interval,
        })
    except Exception:
        pass

    try:
        daemon.start()
    except KeyboardInterrupt:
        daemon.stop()
        try:
            append_to_chain("daemon_stopped", {})
        except Exception:
            pass
        print("\nDaemon stopped.")


def run_detect(args):
    """CLI entry point for charter detect (one-shot scan)."""
    summary = get_summary()

    if not summary["tools"]:
        print("No AI tools detected on this machine.")
        return

    print(f"AI Tools Detected: {summary['total']}")
    print(f"  Governed:   {summary['governed']}")
    print(f"  Ungoverned: {summary['ungoverned']}")
    print()

    for tool in summary["tools"]:
        status = "GOVERNED" if tool["governable"] else "DETECTED"
        print(f"  [{status}] {tool['name']} ({tool['vendor']})")
        print(f"           PID: {tool['pid']}, Process: {tool['process_name']}")

    print(f"\nScanned at: {summary['scanned_at']}")


def run_install(args):
    """CLI entry point for charter install (system service)."""
    system = platform.system()

    if system == "Darwin":
        path = _install_launchd()
        if path:
            print(f"launchd plist written to: {path}")
            print()
            print("To start the service:")
            print(f"  launchctl load {path}")
            print()
            print("To stop the service:")
            print(f"  launchctl unload {path}")

    elif system == "Linux":
        path = _install_systemd()
        if path:
            print(f"systemd unit written to: {path}")
            print()
            print("To start the service:")
            print("  systemctl --user enable charter-daemon")
            print("  systemctl --user start charter-daemon")
            print()
            print("To stop the service:")
            print("  systemctl --user stop charter-daemon")

    else:
        print(f"Service installation not yet supported on {system}.")
        print("Run 'charter serve' manually instead.")


def _install_launchd():
    """Write macOS launchd plist."""
    charter_path = shutil.which("charter") or "/usr/local/bin/charter"

    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" \
"http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>org.charter.daemon</string>
    <key>ProgramArguments</key>
    <array>
        <string>{charter_path}</string>
        <string>serve</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/charter-daemon.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/charter-daemon.err</string>
</dict>
</plist>
"""

    plist_dir = os.path.expanduser("~/Library/LaunchAgents")
    os.makedirs(plist_dir, exist_ok=True)
    plist_path = os.path.join(plist_dir, "org.charter.daemon.plist")

    with open(plist_path, "w") as f:
        f.write(plist)

    return plist_path


def _install_systemd():
    """Write Linux systemd user unit file."""
    charter_path = shutil.which("charter") or "/usr/local/bin/charter"

    unit = f"""[Unit]
Description=Charter Governance Daemon
After=network.target

[Service]
ExecStart={charter_path} serve
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
"""

    unit_dir = os.path.expanduser("~/.config/systemd/user")
    os.makedirs(unit_dir, exist_ok=True)
    unit_path = os.path.join(unit_dir, "charter-daemon.service")

    with open(unit_path, "w") as f:
        f.write(unit)

    return unit_path
