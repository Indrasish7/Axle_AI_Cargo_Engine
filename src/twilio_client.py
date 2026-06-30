import os
import logging
import requests

# Set up logging
logger = logging.getLogger("axle_ai.twilio")
logging.basicConfig(level=logging.INFO)

from dotenv import load_dotenv

def send_whatsapp_message(to_number: str, message_body: str) -> bool:
    """
    Sends a WhatsApp message to the specified number via Meta's WhatsApp Cloud API.
    If the required credentials (META_ACCESS_TOKEN, META_PHONE_NUMBER_ID)
    are missing or contain default placeholders in the environment,
    it gracefully falls back to a clean terminal log output.
    """
    # Reload environment dynamically so token updates take effect without restarting services
    load_dotenv(override=True)
    access_token = os.environ.get("META_ACCESS_TOKEN")
    phone_number_id = os.environ.get("META_PHONE_NUMBER_ID")

    # Clean the recipient phone number:
    # Meta WhatsApp Cloud API expects the destination number without "whatsapp:" or "+" prefix
    recipient = to_number
    if recipient.startswith("whatsapp:"):
        recipient = recipient[len("whatsapp:"):]
    if recipient.startswith("+"):
        recipient = recipient[1:]

    is_configured = (
        access_token and 
        phone_number_id and 
        "PLACEHOLDER" not in access_token and 
        "PLACEHOLDER" not in phone_number_id
    )

    # Verify if real credentials are present
    if is_configured:
        url = f"https://graph.facebook.com/v25.0/{phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "text",
            "text": {
                "body": message_body
            }
        }
        
        try:
            logger.info(f"[Meta Client] Attempting to send live WhatsApp message to {recipient} via Meta Graph API...")
            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=10
            )
            
            if response.status_code in [200, 201]:
                logger.info(f"[Meta Client] WhatsApp message sent successfully. Response: {response.json()}")
                return True
            else:
                logger.error(
                    f"[Meta Client Error] Meta API returned status code {response.status_code}. "
                    f"Response: {response.text}"
                )
                return False
        except Exception as e:
            logger.error(f"[Meta Client Error] Failed to POST message to Meta API: {e}")
            return False
    else:
        # Fallback simulation mode using safe ASCII characters for Windows console
        print("\n+" + "=" * 78 + "+")
        print(f"| {'META WHATSAPP OUTBOUND DISPATCH SIMULATION'.center(76)} |")
        print("+" + "=" * 78 + "+")
        print(f"| To:   {recipient:<70} |")
        print(f"| From: {phone_number_id or 'SIMULATED_META_SENDER':<70} |")
        print("+" + "-" * 78 + "+")
        
        # Print message body line by line
        lines = message_body.strip().split("\n")
        for line in lines:
            # Chunk long lines to fit nicely in the frame
            while len(line) > 70:
                print(f"|   {line[:70]:<74} |")
                line = line[70:]
            print(f"|   {line:<74} |")
            
        print("+" + "=" * 78 + "+\n")
        return True
