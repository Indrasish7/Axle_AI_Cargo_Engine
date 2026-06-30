import sys
import requests

def get_active_tunnel_url() -> str:
    """Detects if an active ngrok tunnel is running and returns its base public URL."""
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
    print(f"| {'AXLE AI TWILIO SANDBOX PAYLOAD TEST SIMULATOR'.center(76)} |")
    print("+" + "=" * 78 + "+")

    # 1. Resolve Target Webhook Endpoint
    local_url = "http://localhost:8000/webhook/v1/whatsapp"
    public_url = get_active_tunnel_url()
    
    endpoint = local_url
    if public_url:
        public_endpoint = f"{public_url}/webhook/v1/whatsapp"
        print(f"[Info] Active ngrok tunnel detected: {public_url}")
        print(f"1. Local Endpoint  : {local_url}")
        print(f"2. Public Endpoint : {public_endpoint}")
        choice = input("Select destination endpoint [1]: ").strip()
        if choice == "2":
            endpoint = public_endpoint
    
    print(f"\n[Ready] Target Webhook: {endpoint}")
    print("Type 'exit' or press Ctrl+C at any prompt to quit.\n")

    # Default values
    default_phone = "whatsapp:+15559876543"

    try:
        while True:
            print("-" * 80)
            # 2. Collect Input Message
            body_text = input("Message text: ").strip()
            if not body_text:
                continue
            if body_text.lower() == "exit":
                break
                
            # 3. Collect Phone Number Override
            phone_input = input(f"Sender phone [default: {default_phone}]: ").strip()
            phone = phone_input if phone_input else default_phone
            
            # Ensure correct formatting
            if not phone.startswith("whatsapp:"):
                phone = f"whatsapp:{phone}"

            print(f"\n[HTTP POST] Dispatching form-urlencoded payload to {endpoint}...")
            payload = {
                "From": phone,
                "Body": body_text
            }
            
            try:
                # Mimic standard Twilio webhook payload
                response = requests.post(endpoint, data=payload, timeout=5.0)
                
                # Render beautiful response box
                print("+" + "=" * 78 + "+")
                print(f"| {'WEBHOOK GATEWAY RESPONSE'.center(76)} |")
                print("+" + "=" * 78 + "+")
                print(f"| HTTP Status: {response.status_code:<63} |")
                
                if response.status_code == 202:
                    data = response.json()
                    print(f"| Routed To  : {data.get('routed_to', 'N/A'):<63} |")
                    print(f"| Sender ID  : {data.get('sender_id', 'N/A'):<63} |")
                    print("+" + "-" * 78 + "+")
                    
                    # Print message cleanly
                    msg = data.get("message", "")
                    lines = msg.split("\n")
                    for line in lines:
                        while len(line) > 70:
                            print(f"|   {line[:70]:<74} |")
                            line = line[70:]
                        print(f"|   {line:<74} |")
                else:
                    print("+" + "-" * 78 + "+")
                    print(f"| Raw Error: {response.text[:70]:<70} |")
                    
                print("+" + "=" * 78 + "+\n")
            except requests.RequestException as e:
                print(f"\n[!] Network Error: Failed to reach gateway endpoint: {e}\n")

    except KeyboardInterrupt:
        pass
        
    print("\n\n[Simulator] Test harness terminated. Exiting.")
    print("+" + "=" * 78 + "+\n")

if __name__ == "__main__":
    main()
