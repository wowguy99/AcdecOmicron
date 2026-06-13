"""Desktop entry point for the packaged Windows app."""
from __future__ import annotations

import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

# Ensure ``backend/`` is on sys.path when run directly (PyInstaller / dev).
_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))


def _port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def _open_browser(url: str) -> None:
    time.sleep(1.5)
    webbrowser.open(url)


def main() -> None:
    host = "127.0.0.1"
    port = 8000
    url = f"http://{host}:{port}"

    if _port_in_use(host, port):
        print(f"Port {port} is already in use.")
        print(f"If the app is already running, opening: {url}")
        webbrowser.open(url)
        return

    print("")
    print(f"Starting AcDec Flashcard Generator at {url}")
    print("Keep this window open while using the app. Press Ctrl+C to stop.")
    print("")

    threading.Thread(target=_open_browser, args=(url,), daemon=True).start()

    import uvicorn

    from app.main import app

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
        sys.exit(0)
