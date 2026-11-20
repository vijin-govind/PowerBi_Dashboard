"""Start PBIX Canvas and open it in the browser.

Usage:  python run.py            (or double-click run.bat on Windows)
"""

import socket
import sys
import threading
import webbrowser
from pathlib import Path

if sys.version_info < (3, 10):
    sys.exit(f"PBIX Canvas needs Python 3.10 or newer (this is {sys.version.split()[0]}).")

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))

try:
    import uvicorn

    from app.main import app
except ImportError as exc:
    sys.exit(
        f"Missing package: {exc.name}\n"
        "Install the requirements first:\n"
        f'  "{sys.executable}" -m pip install -r backend/requirements.txt'
    )


def free_port(start: int = 8000) -> int:
    for port in range(start, start + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise SystemExit("No free port found between 8000 and 8049.")


if __name__ == "__main__":
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    print(f"\n  PBIX Canvas is running at {url}\n  Press Ctrl+C to stop.\n")
    if "--no-browser" not in sys.argv:
        threading.Timer(1.5, webbrowser.open, [url]).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
