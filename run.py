#!/usr/bin/env python3
"""
Browser-first single entry point.

python run.py  -> starts API (8000) + Dashboard (8501), minimal terminal output.
"""
import sys, subprocess, time, os, pathlib, threading, webbrowser, signal

DASHBOARD_PORT = 8501
API_PORT = 8000

def _is_port_open(port):
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.settimeout(0.5)
        s.connect(("127.0.0.1", port))
        s.close()
        return True
    except:
        return False

def main():
    print("Indian Stock Quant Lab")
    # ensure db initialized
    try:
        from app.database.db import init_db
        init_db()
    except Exception as e:
        print(f"DB init warning: {e}")

    # start API in background if not already running
    api_proc = None
    if not _is_port_open(API_PORT):
        try:
            api_proc = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "app.api.main:app", f"--port={API_PORT}", "--host=127.0.0.1", "--log-level=warning"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except Exception as e:
            print(f"API start failed (continuing): {e}")
    # also support FASTAPI optional
    # start streamlit
    print(f"Dashboard: http://localhost:{DASHBOARD_PORT}")
    print(f"API: http://localhost:{API_PORT}")
    print("Status: READY")
    print("Tip: Use the browser. Terminal is only for logs.")
    # try open browser after short delay
    def _open():
        time.sleep(1.5)
        try: webbrowser.open(f"http://localhost:{DASHBOARD_PORT}")
        except: pass
    threading.Thread(target=_open, daemon=True).start()

    # run streamlit in foreground (blocking) with minimal logs
    try:
        subprocess.run([sys.executable, "-m", "streamlit", "run", "app/ui/main.py",
                        f"--server.port={DASHBOARD_PORT}", "--server.headless=true", "--logger.level=warning", "--client.showErrorDetails=false"],
                       check=False)
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        if api_proc:
            try: api_proc.terminate()
            except: pass

if __name__ == "__main__":
    main()
