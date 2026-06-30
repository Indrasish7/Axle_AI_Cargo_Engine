import os
from google import genai
from google.genai import types
from src.database import Booking, FleetVehicle

def generate_dispatch_offer(booking: Booking, vehicle: FleetVehicle) -> str:
    """
    Generates a highly tailored, professional outbound conversational message
    intended for the vehicle's fleet manager or driver, pitching the booked cargo load.
    Utilizes the modern google-genai SDK with 'gemini-2.5-flash'.
    Includes a high-fidelity rule-based template engine as a fallback.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    
    # Resilient fallback if no API key is configured or for local test runners
    if not api_key or api_key == "MOCK_KEY" or os.environ.get("USE_MOCK_PARSER") == "1":
        return _mock_generate_offer(booking, vehicle)
        
    try:
        # Initialize Google GenAI client
        client = genai.Client()
        
        prompt = f"""
        You are the automated outbound carrier negotiation agent for Axle AI.
        Your job is to generate a highly tailored, warm, professional, and persuasive dispatch offer message 
        to send to a truck fleet manager or driver. The driver has been matched with a cargo load.
        
        CRITICAL INFORMATION TO STATE:
        - Cargo Type: {booking.item_type}
        - Exact Weight: {booking.weight_kg:,.1f} kg
        - Pickup Origin: {booking.origin}
        - Drop-off Destination: {booking.destination}
        - Financial Budget: {booking.price_booked:,.1f} {booking.currency}
        - Matched Vehicle ID: {vehicle.vehicle_id}
        - Truck Type: {vehicle.truck_type}
        
        TONE & FORMAT:
        - Highly professional yet conversational (friendly B2B tone).
        - Treat it as an attractive, premium immediate dispatch offer.
        - Be direct and concise. Avoid corporate waffle.
        - Ensure a clear call to action to accept the load.
        
        Draft the outbound message text:
        """
        
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.7,
            )
        )
        
        return response.text.strip()
        
    except Exception as e:
        print(f"[Negotiator Warning] Gemini generation failed or is unconfigured: {e}. Using fallback generator.")
        return _mock_generate_offer(booking, vehicle)

def _mock_generate_offer(booking: Booking, vehicle: FleetVehicle) -> str:
    """
    High-fidelity rule-based template builder that simulates natural B2B chat/SMS
    offers based on vehicle and booking characteristics.
    """
    # Customize greeting based on truck ID prefix
    recipient_name = "Fleet Dispatcher"
    if "CHI" in vehicle.vehicle_id:
        recipient_name = "Marcus"
    elif "ATL" in vehicle.vehicle_id:
        recipient_name = "Suresh"
    elif "LAX" in vehicle.vehicle_id:
        recipient_name = "Elena"
        
    # Build a conversational, premium-sounding SMS/WhatsApp dispatch pitch
    offer_text = (
        f"Hey {recipient_name}! Axle AI has a premium load available for {vehicle.truck_type} ({vehicle.vehicle_id}). "
        f"We've matched you with a high-paying shipment of {booking.item_type} ({booking.weight_kg:,.1f} kg) "
        f"ready to roll from {booking.origin} over to {booking.destination}. "
        f"The budget is fixed at {booking.price_booked:,.1f} {booking.currency} for immediate dispatch. "
        f"This matches your fleet constraints perfectly. Tap reply with 'CONFIRM' to lock this in and receive gate passes!"
    )
    return offer_text

def generate_shipper_whatsapp_quote(booking: Booking, vehicle: FleetVehicle) -> str:
    """
    Generates a conversational B2B WhatsApp notification quote back to the original shipper.
    Confirms a driver is located, states confirmation ID, references cargo metrics,
    pricing, and contains a clear call to action.
    Uses 'gemini-2.5-flash' and modern google-genai SDK.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    
    # Resilient fallback if no API key is configured or for local test runners
    if not api_key or api_key == "MOCK_KEY" or os.environ.get("USE_MOCK_PARSER") == "1":
        return _mock_generate_shipper_whatsapp_quote(booking, vehicle)
        
    try:
        # Initialize Google GenAI client
        client = genai.Client()
        
        prompt = f"""
        You are the automated shipper confirmation dispatcher for Axle AI.
        Your job is to generate a conversational, friendly, B2B WhatsApp notification back to the original shipper,
        confirming that their cargo load has been matched and booked with a nearby fleet vehicle.
        
        CRITICAL INFORMATION TO INJECT:
        - Shipper Booking ID: {booking.booking_id}
        - Driver / Vehicle ID: {vehicle.vehicle_id}
        - Cargo Description: {booking.item_type}
        - Exact Cargo Weight: {booking.weight_kg:,.1f} kg
        - Route: From {booking.origin} to {booking.destination}
        - Price Locked: {booking.price_booked:,.1f} {booking.currency} (This matches their maximum budget!)
        - ETA / Deadline Reference: The matched carrier is moving immediately to make the pickup.
        
        TONE & FORMAT:
        - Friendly, B2B conversational, highly reassuring.
        - Ensure a very clear call to action to lock in the freight line (e.g. "To approve and lock in this dispatch line, please tap 'APPROVE'").
        - Keep the text concise and optimized for a WhatsApp chat UI (can use bullet points or bold text *like this*).
        
        Draft the WhatsApp shipper confirmation message:
        """
        
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.7,
            )
        )
        
        return response.text.strip()
        
    except Exception as e:
        print(f"[Negotiator Warning] Gemini shipper quote failed: {e}. Using fallback generator.")
        return _mock_generate_shipper_whatsapp_quote(booking, vehicle)

def _mock_generate_shipper_whatsapp_quote(booking: Booking, vehicle: FleetVehicle) -> str:
    """
    High-fidelity template fallback simulating the WhatsApp B2B shipper quote.
    Uses pure ASCII characters to prevent Windows console encoding crashes.
    """
    quote_text = (
        f"Hi there! Quick update from *Axle AI* [Dispatch Offer]\n\n"
        f"Great news! We've successfully locked in a nearby driver for your load:\n"
        f"- *Booking ID*: {booking.booking_id}\n"
        f"- *Cargo*: {booking.item_type} ({booking.weight_kg:,.1f} kg)\n"
        f"- *Route*: From {booking.origin} to {booking.destination}\n"
        f"- *Assigned Unit*: {vehicle.truck_type} ({vehicle.vehicle_id})\n"
        f"- *Fixed Rate*: {booking.price_booked:,.1f} {booking.currency} (100% matched to your budget!)\n\n"
        f"Our driver is currently en route and ready for immediate dispatch. "
        f"Please reply with *'APPROVE'* to finalize the freight line and receive your digital tracking link!"
    )
    return quote_text
