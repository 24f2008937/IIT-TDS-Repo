#!/usr/bin/env python3
import os
import sys
import time
import json
import subprocess
import urllib.request
import signal

def start_server():
    print("=" * 60)
    print("  Starting A2A Invoice Agent with Public Tunnel")
    print("=" * 60)

    # 1. Kill any existing process on port 8000 or 4040
    try:
        subprocess.run(["pkill", "-f", "uvicorn main:app"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["pkill", "-f", "ngrok http 8000"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    time.sleep(1)

    # 2. Start ngrok tunnel
    ngrok_cmd = ["ngrok", "http", "8000", "--log=stdout"]
    tunnel_proc = subprocess.Popen(ngrok_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("✓ Starting ngrok tunnel on port 8000...")

    public_url = None
    for _ in range(15):
        time.sleep(1)
        try:
            req = urllib.request.Request("http://127.0.0.1:4040/api/tunnels")
            res = urllib.request.urlopen(req)
            data = json.loads(res.read().decode("utf-8"))
            tunnels = data.get("tunnels", [])
            for t in tunnels:
                if t.get("proto") == "https":
                    public_url = t.get("public_url")
                    break
            if public_url:
                break
        except Exception:
            pass

    if not public_url:
        print("! ngrok not available or did not return tunnel URL. Falling back to localtunnel...")
        tunnel_proc.terminate()
        lt_cmd = ["npx", "localtunnel", "--port", "8000"]
        tunnel_proc = subprocess.Popen(lt_cmd, stdout=subprocess.PIPE, text=True)
        for _ in range(15):
            line = tunnel_proc.stdout.readline()
            if "your url is:" in line:
                public_url = line.split("your url is:")[1].strip()
                break

    if not public_url:
        print("❌ Error: Could not obtain public HTTPS tunnel URL.")
        sys.exit(1)

    a2a_base_url = f"{public_url.rstrip('/')}/a2a/"

    # 3. Start uvicorn with BASE_URL injected
    python_exe = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".venv", "bin", "python3")
    if not os.path.exists(python_exe):
        python_exe = sys.executable

    uvicorn_cmd = [
        python_exe, "-m", "uvicorn", "main:app",
        "--host", "127.0.0.1",
        "--port", "8000",
        "--log-level", "info"
    ]
    env = dict(os.environ)
    env["BASE_URL"] = a2a_base_url
    db_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "invoice_agent.db")
    env["DB_PATH"] = db_file

    server_proc = subprocess.Popen(uvicorn_cmd, cwd=os.path.dirname(os.path.abspath(__file__)), env=env)
    print(f"✓ Local Uvicorn server started on http://127.0.0.1:8000 (DB: {db_file})")

    time.sleep(2)

    print("\n" + "#" * 60)
    print("🚀 PUBLIC A2A INVOICE AGENT IS READY!")
    print(f"👉 Agent Card URL: {public_url}/.well-known/agent-card.json")
    print(f"👉 A2A interface base URL to submit in exam:")
    print(f"   {a2a_base_url}")
    print("#" * 60 + "\n")
    print("Press Ctrl+C to stop the agent.\n")

    def shutdown(sig, frame):
        print("\nStopping services...")
        try:
            server_proc.terminate()
            tunnel_proc.terminate()
        except Exception:
            pass
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    server_proc.wait()

if __name__ == "__main__":
    start_server()
