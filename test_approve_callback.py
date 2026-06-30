import urllib.request
import json

url = "http://localhost:8000/webhook/v1/whatsapp"
headers = {
    "Content-Type": "application/json"
}

payload = {
  "object": "whatsapp_business_account",
  "entry": [
    {
      "id": "1017180474322655",
      "changes": [
        {
          "value": {
            "messaging_product": "whatsapp",
            "metadata": {
              "display_phone_number": "15556656163",
              "phone_number_id": "1149351458260985"
            },
            "contacts": [
              {
                "profile": {
                  "name": "User"
                },
                "wa_id": "917001203363"
              }
            ],
            "messages": [
              {
                "from": "917001203363",
                "id": "wamid.HBgLOTE3MDAxMjAzMzYzFQIAEhgWM0VCQjA2QTQ3QkEzOEYzN0Y1QkE0OAA=",
                "timestamp": "1686000000",
                "text": {
                  "body": "APPROVE"
                },
                "type": "text"
              }
            ]
          },
          "field": "messages"
        }
      ]
    }
  ]
}

data = json.dumps(payload).encode('utf-8')
req = urllib.request.Request(url, data=data, headers=headers, method="POST")

try:
    response = urllib.request.urlopen(req)
    res_data = json.loads(response.read().decode('utf-8'))
    print("=== Mock Webhook Response ===")
    print(json.dumps(res_data, indent=2))
except Exception as e:
    if hasattr(e, 'read'):
        print(f"Error: {e.read().decode('utf-8')}")
    else:
        print(f"Error: {e}")
