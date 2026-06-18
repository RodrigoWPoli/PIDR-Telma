"""
PIDR launcher — Windows entry point bundled by PyInstaller.

Responsibilities:
  1. Point JAVA_HOME / PATH at the bundled JRE so owlready2's Pellet works.
  2. Ensure the MongoDB service is running.
  3. Start the Streamlit dashboard in a background thread on 127.0.0.1:8501.
  4. Open a native pywebview window pointing at that URL.

Special CLI mode: `--data-collection` dispatches into data_collection.collect()
so the dashboard's "Start collection" subprocess (which spawns sys.executable)
works inside the frozen build.
"""

import ctypes
import os
import socket
import subprocess
import sys
import threading
import time


for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass


def _bundle_dir() -> str:
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


BUNDLE_DIR = _bundle_dir()
JRE_DIR = os.path.join(BUNDLE_DIR, "jre")
DASHBOARD_SCRIPT = os.path.join(BUNDLE_DIR, "dashboard.py")
STREAMLIT_HOST = "127.0.0.1"
STREAMLIT_PORT = 8501


def _msgbox(title: str, text: str, style: int = 0x10) -> None:
    try:
        ctypes.windll.user32.MessageBoxW(0, text, title, style)
    except Exception:
        print(f"{title}: {text}", file=sys.stderr)


def setup_java() -> None:
    if not os.path.isdir(JRE_DIR):
        return
    os.environ["JAVA_HOME"] = JRE_DIR
    bin_dir = os.path.join(JRE_DIR, "bin")
    os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")


def ensure_mongodb() -> bool:
    """Return True if MongoDB is reachable on localhost:27017."""
    try:
        query = subprocess.run(
            ["sc", "query", "MongoDB"],
            capture_output=True, text=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        query = None

    if query and query.returncode == 0:
        if "RUNNING" not in query.stdout.upper():
            subprocess.run(
                ["net", "start", "MongoDB"],
                capture_output=True, text=True, timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
    else:
        if not _port_open("127.0.0.1", 27017, timeout=1.0):
            _msgbox(
                "MongoDB not installed",
                "MongoDB service was not found.\n\n"
                "Re-run the installer and keep the "
                "'Install MongoDB' option checked.",
                0x10,
            )
            return False

    for _ in range(30):
        if _port_open("127.0.0.1", 27017, timeout=0.5):
            return True
        time.sleep(0.5)

    _msgbox("MongoDB unreachable",
            "MongoDB service did not come up on port 27017.", 0x10)
    return False


def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def start_streamlit() -> None:
    # Streamlit calls signal.signal() during startup, which raises ValueError
    # when running in a non-main thread. Patch it to silently skip those calls
    # since pywebview owns the main thread and manages the app lifecycle.
    import signal as _signal
    _orig = _signal.signal
    def _safe_signal(sig, handler):
        try:
            return _orig(sig, handler)
        except ValueError:
            pass
    _signal.signal = _safe_signal

    sys.argv = [
        "streamlit", "run", DASHBOARD_SCRIPT,
        "--server.address", STREAMLIT_HOST,
        "--server.port", str(STREAMLIT_PORT),
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false",
        "--global.developmentMode", "false",
    ]
    from streamlit.web import cli as stcli  # noqa: WPS433
    stcli.main()


def wait_for_streamlit(timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _port_open(STREAMLIT_HOST, STREAMLIT_PORT, timeout=0.5):
            return True
        time.sleep(0.3)
    return False


def run_dashboard() -> int:
    setup_java()
    if not ensure_mongodb():
        return 2

    threading.Thread(target=start_streamlit, daemon=True).start()

    if not wait_for_streamlit():
        _msgbox("Dashboard failed to start",
                "The Streamlit server did not become reachable. "
                "Check %LOCALAPPDATA%\\TELMA\\launcher.log.", 0x10)
        return 3

    import webview  # noqa: WPS433
    webview.create_window(
        "TELMA Fault Detection",
        f"http://{STREAMLIT_HOST}:{STREAMLIT_PORT}",
        width=1400, height=900, min_size=(1024, 720),
    )
    webview.start()
    return 0


def run_data_collection() -> int:
    setup_java()
    sys.path.insert(0, BUNDLE_DIR)
    from data_collection import collect  # noqa: WPS433
    collect()
    return 0


def main() -> int:
    if "--data-collection" in sys.argv[1:]:
        return run_data_collection()
    return run_dashboard()


if __name__ == "__main__":
    sys.exit(main())