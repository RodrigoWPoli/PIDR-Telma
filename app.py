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
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error
import os

import webview


DASHBOARD   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.py")
WINDOW_W    = 1400
WINDOW_H    = 860
READY_TRIES = 30     # seconds to wait for Streamlit before giving up


def _start_streamlit(port: int) -> subprocess.Popen:
    return subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run", DASHBOARD,
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

    print(f"Starting TELMA dashboard on {url} ...")
    process = _start_streamlit(args.port)

    if not _wait_for_server(url, READY_TRIES):
        process.terminate()
        print("Error: Streamlit did not start in time.", file=sys.stderr)
        sys.exit(1)

    print("Dashboard ready — opening window.")

    def on_closed():
        process.terminate()

    window = webview.create_window(
        title   = "TELMA Fault Detection Dashboard",
        url     = url,
        width   = WINDOW_W,
        height  = WINDOW_H,
        resizable = True,
    )
    window.events.closed += on_closed

    webview.start()


if __name__ == "__main__":
    main()
