"""
app.py
Launches the TELMA dashboard in a native desktop window (no browser needed).

Starts Streamlit as a local server, waits until it is ready, then opens a
pywebview window pointing to it. Closing the window shuts everything down.

Usage:
    python app.py
    python app.py --port 8502   # use a different port if 8501 is taken
"""

import argparse
import socket
import subprocess
import sys
import time
import urllib.request
import urllib.error
import os
from pathlib import Path

import webview


WINDOW_W    = 1400
WINDOW_H    = 860
READY_TRIES = 30     # seconds to wait for Streamlit before giving up


def _base_path() -> Path:
    return Path(os.path.dirname(os.path.abspath(__file__)))


DASHBOARD = _base_path() / "dashboard.py"


def _ensure_mongodb():
    """Start portable mongod.exe if nothing is listening on port 27017.

    Returns the Popen handle if we started mongod ourselves, else None.
    The caller must terminate() the handle when the app exits.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if s.connect_ex(("localhost", 27017)) == 0:
            return None  # already running (system MongoDB or prior start)

    mongod = _base_path() / "mongodb" / "bin" / "mongod.exe"
    if not mongod.exists():
        return None  # no portable mongod bundled; hope system MongoDB is installed

    # Store data in %LOCALAPPDATA%\TELMA\mongodb\data (always user-writable)
    if sys.platform == "win32":
        data_root = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "TELMA"
    else:
        data_root = Path.home() / ".telma"
    data_dir = data_root / "mongodb" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    print("Starting portable MongoDB...")
    proc = subprocess.Popen(
        [str(mongod), "--dbpath", str(data_dir), "--port", "27017"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    for _ in range(10):
        time.sleep(1)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("localhost", 27017)) == 0:
                print("MongoDB ready.")
                return proc

    print("Warning: MongoDB did not respond in 10 s — continuing anyway.")
    return proc


def _start_streamlit(port: int) -> subprocess.Popen:
    return subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run", str(DASHBOARD),
            "--server.port",     str(port),
            "--server.headless", "true",      # no auto-open browser
            "--server.address",  "localhost",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _wait_for_server(url: str, timeout: int) -> bool:
    """Poll until Streamlit responds or timeout expires."""
    for _ in range(timeout):
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except (urllib.error.URLError, OSError):
            time.sleep(1)
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8501)
    args = parser.parse_args()

    url = f"http://localhost:{args.port}"

    mongo_proc = _ensure_mongodb()

    print(f"Starting TELMA dashboard on {url} ...")
    process = _start_streamlit(args.port)

    if not _wait_for_server(url, READY_TRIES):
        process.terminate()
        if mongo_proc:
            mongo_proc.terminate()
        print("Error: Streamlit did not start in time.", file=sys.stderr)
        sys.exit(1)

    print("Dashboard ready — opening window.")

    try:
        def on_closed():
            process.terminate()
            if mongo_proc:
                mongo_proc.terminate()

        window = webview.create_window(
            title     = "TELMA Fault Detection Dashboard",
            url       = url,
            width     = WINDOW_W,
            height    = WINDOW_H,
            resizable = True,
        )
        window.events.closed += on_closed
        webview.start()
    except Exception:
        # No GUI backend available (e.g. missing GTK on Linux).
        # Fall back to opening the default browser and keeping the server alive.
        import webbrowser
        print("Native window unavailable — opening browser instead.")
        print(f"Dashboard: {url}  (press Ctrl+C to stop)")
        webbrowser.open(url)
        try:
            process.wait()
        except KeyboardInterrupt:
            process.terminate()
            if mongo_proc:
                mongo_proc.terminate()


if __name__ == "__main__":
    main()
