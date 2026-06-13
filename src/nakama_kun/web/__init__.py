from __future__ import annotations

import threading
import time
import webbrowser

import uvicorn
from loguru import logger

from nakama_kun.web.app import app
from nakama_kun.web.auth import get_session_token
from nakama_kun.web.service_wiring import get_web_context


def run_web_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    workspace_root: str | None = None,
) -> None:
    """Launch the FastAPI/Uvicorn server and auto-open the browser to the web session."""
    # Pre-initialize services in the context
    context = get_web_context(workspace_root)
    token = get_session_token()
    url = f"http://{host}:{port}/?token={token}"

    print("\n" + "═" * 70)
    print(" 🤖 nakama_kun Web Interface is starting up...")
    print(f" 📁 Workspace Root: {context.workspace_root}")
    print(f" 🔌 Server Endpoint: http://{host}:{port}")
    print("\n 🔗 Click the link below to open the dashboard:")
    print(f"    \033[1;36m{url}\033[0m")
    print("═" * 70 + "\n")

    def open_browser_delayed() -> None:
        try:
            time.sleep(1.0)
            webbrowser.open(url)
        except Exception as e:
            logger.warning(f"Failed to auto-open browser: {e}")

    # Start browser-open thread
    thread = threading.Thread(target=open_browser_delayed, daemon=True)
    thread.start()

    # Launch uvicorn
    uvicorn.run(app, host=host, port=port, log_level="info")
