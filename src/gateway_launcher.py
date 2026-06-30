import os
import sys
import time
import subprocess
import requests

def check_uvicorn_running() -> bool:
    """Checks if the local Axle AI Uvicorn server is running on port 8000."""
    try:
        response = requests.get("http://localhost:8000/health", timeout=1.0)
        return response.status_code == 200
    except requests.RequestException:
        return False

def get_active_tunnels() -> str:
    """Queries ngrok's local REST API to get the public HTTPS forwarding URL."""
    try:
        response = requests.get("http://localhost:4040/api/tunnels", timeout=1.0)
        if response.status_code == 200:
            data = response.json()
            tunnels = data.get("tunnels", [])
            for tunnel in tunnels:
                public_url = tunnel.get("public_url", "")
                if public_url.startswith("https://"):
                    return public_url
    except requests.RequestException:
        pass
    return ""

def main():
    print("+" + "=" * 78 + "+")
    print(f"| {'AXLE AI PUBLIC GATEWAY INFRASTRUCTURE LAUNCHER'.center(76)} |")
    print("+" + "=" * 78 + "+")

    # 1. Verify Uvicorn Server is Active
    print("[1/3] Verifying local Uvicorn FastAPI server status...")
    if not check_uvicorn_running():
        print("\n[!] WARNING: Local Axle AI Uvicorn server is not running on port 8000!")
        print("    Please start the server first in another terminal tab:")
        print("    --> python main.py")
        print("+" + "=" * 78 + "+\n")
        sys.exit(1)
    print("    --> Success: Local FastAPI engine verified on port 8000.\n")

    # 2. Check or Spawn ngrok Tunnel
    print("[2/3] Checking for active local ngrok tunnel...")
    public_url = get_active_tunnels()
    ngrok_process = None

    if public_url:
        print(f"    --> Found active ngrok tunnel: {public_url}\n")
    else:
        print("    --> Inactive. Spawning secure ngrok background tunnel on port 8000...")
        try:
            # Launch ngrok as a background subprocess
            ngrok_process = subprocess.Popen(
                ["ngrok", "http", "8000"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            
            # Poll ngrok's local API until tunnel URL becomes available
            retries = 10
            for i in range(1, retries + 1):
                time.sleep(1.0)
                public_url = get_active_tunnels()
                if public_url:
                    print(f"    --> Success: Spawned ngrok tunnel in background after {i}s.")
                    print(f"        Public Forwarding: {public_url}\n")
                    break
            
            if not public_url:
                print("\n[!] ERROR: ngrok started but failed to expose a public HTTPS URL in time.")
                print("    Ensure ngrok is installed and authenticated on your system:")
                print("    --> ngrok config add-authtoken <your-token>")
                if ngrok_process:
                    ngrok_process.terminate()
                sys.exit(1)
                
        except FileNotFoundError:
            print("\n[!] ERROR: 'ngrok' executable was not found on your system PATH!")
            print("    Please install ngrok or run the tunnel manually:")
            print("    --> ngrok http 8000")
            print("+" + "=" * 78 + "+\n")
            sys.exit(1)

    # Load .env if present
    if os.path.exists(".env"):
        with open(".env", "r") as f:
            for line in f:
                if "=" in line:
                    key, val = line.strip().split("=", 1)
                    os.environ[key.strip()] = val.strip()

    # 3. Output Configuration Webhook String
    webhook_url = f"{public_url}/webhook/v1/whatsapp"
    verify_token = os.environ.get("META_VERIFY_TOKEN", "axle_secret_2026")
    print("[3/3] Generating Meta WhatsApp Cloud API Webhook Configuration:")
    print("+" + "-" * 78 + "+")
    print(f"| Callback URL (GET/POST):                                                     |")
    print(f"| {webhook_url:<76} |")
    print(f"| Verify Token:                                                                |")
    print(f"| {verify_token:<76} |")
    print("+" + "-" * 78 + "+")
    print("\n[Operations] Instructions to connect Meta WhatsApp Cloud API:")
    print("1. Copy the Callback URL and Verify Token listed above.")
    print("2. Open your Meta Developer Console -> WhatsApp -> Configuration.")
    print("3. Click 'Edit' next to Webhooks, paste the Callback URL and Verify Token,")
    print("   and click 'Verify and save'.")
    print("4. Under Webhook fields, manage subscriptions and subscribe to 'messages'.")
    print("\nPress Ctrl+C to terminate the background gateway tunnel...")

    try:
        # Keep launcher running in terminal to sustain spawned ngrok process
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\n\n[Gateway] Shutting down gateway launcher...")
        if ngrok_process:
            print("[Gateway] Terminating background ngrok subprocess...")
            ngrok_process.terminate()
            ngrok_process.wait()
        print("[Gateway] Shutdown complete. Tunnel closed.")
        print("+" + "=" * 78 + "+\n")

if __name__ == "__main__":
    main()
