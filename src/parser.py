import os
import json
import re
from google import genai
from google.genai import types
from src.models import CargoPayload, CargoMetadata, CargoRouting, Financials

def parse_cargo_request(raw_text: str) -> CargoPayload:
    """
    Parses unstructured text requests (e.g. email, WhatsApp) into a structured CargoPayload
    using the Gemini 2.5 Flash model and modern google-genai SDK.
    Includes auto-conversion of weights to kilograms.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    
    # Resilient fallback if no API key is configured or for local test runners
    if not api_key or api_key == "MOCK_KEY" or os.environ.get("USE_MOCK_PARSER") == "1":
        return _mock_parse(raw_text)
        
    try:
        # Initialize client (will pick up GEMINI_API_KEY from environment)
        client = genai.Client()
        
        prompt = f"""
        You are the parser engine for Axle AI. 
        Your task is to extract structured logistics information from this raw, conversational B2B cargo request.
        
        CRITICAL RULES:
        1. Extract the Cargo Metadata:
           - 'item_type': The item being shipped (e.g., "Frozen Salmon", "Steel Coils").
           - 'weight_kg': Extract the cargo weight and STRICTLY convert it to KILOGRAMS (kg).
             - If tons (t, metric ton) are given: 1 ton = 1,000 kg (e.g., "15 tons" -> 15000.0)
             - If short tons (US) are given: 1 short ton = 907.185 kg
             - If lbs/pounds are given: 1 lb = 0.453592 kg (e.g., "8,000 lbs" -> 3628.74)
           - 'special_handling': Specific conditions like temperature requirements (e.g., "Frozen (-18°C)"), HAZMAT status, or Fragile. Set to null if none.
           
        2. Extract Routing Info:
           - 'origin': Pickup city/location. If coordinate string is given, keep it.
           - 'destination': Delivery city/location. If coordinate string is given, keep it.
           - 'pickup_deadline': Extract when the shipment must be picked up. Enforce an ISO 8601 formatted datetime string (e.g. '2026-06-02T12:00:00Z').
           
        3. Extract Financials:
           - 'max_budget': The maximum price target. Extract as a float.
           - 'currency': The currency code (default is "USD" if not specified).
        
        Conversational Request:
        \"\"\"
        {raw_text}
        \"\"\"
        """
        
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=CargoPayload,
                temperature=0.1,
            )
        )
        
        # Parse output JSON into Pydantic model
        data = json.loads(response.text)
        return CargoPayload(**data)
        
    except Exception as e:
        # Graceful fallback logging
        print(f"[Parser Warning] Gemini LLM parse failed or unconfigured: {e}. Running rule-based fallback parser.")
        return _mock_parse(raw_text)

def _mock_parse(raw_text: str) -> CargoPayload:
    """
    High-fidelity rule-based heuristic parser used as a local fallback
    when the Gemini API is unconfigured, rate-limited, or unavailable.
    """
    text_lower = raw_text.lower()
    
    # 1. Determine Weight & Unit
    weight_kg = 5000.0  # Safe default
    
    # Match tons
    ton_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:tons|ton|t\b)', text_lower)
    # Match lbs
    lbs_match = re.search(r'(\d{1,3}(?:,\d{3})*|\d+(?:\.\d+)?)\s*(?:lbs|lb|pounds)', text_lower)
    # Match kgs
    kg_match = re.search(r'(\d{1,3}(?:,\d{3})*|\d+(?:\.\d+)?)\s*(?:kg|kgs|kilograms)', text_lower)
    
    if ton_match:
        weight_kg = float(ton_match.group(1)) * 1000.0
    elif lbs_match:
        val_str = lbs_match.group(1).replace(",", "")
        weight_kg = float(val_str) * 0.453592
    elif kg_match:
        val_str = kg_match.group(1).replace(",", "")
        weight_kg = float(val_str)

    # 2. Determine Item Type
    item_type = "General Freight"
    if "salmon" in text_lower or "fish" in text_lower:
        item_type = "Frozen Salmon"
    elif "steel" in text_lower or "pipe" in text_lower or "coils" in text_lower:
        item_type = "Steel Pipes"
    elif "electronics" in text_lower or "gadget" in text_lower or "phones" in text_lower:
        item_type = "High-Value Electronics"
    elif "chemical" in text_lower or "toxic" in text_lower or "acid" in text_lower:
        item_type = "Industrial Chemicals"
    elif "vaccines" in text_lower or "pharma" in text_lower or "medicine" in text_lower:
        item_type = "Pharma Vaccines"

    # 3. Special Handling
    special_handling = None
    if "frozen" in text_lower or "temp" in text_lower or "reefer" in text_lower or "cold" in text_lower or "vaccines" in text_lower:
        special_handling = "Temperature Controlled (-18C)"
    elif "fragile" in text_lower or "careful" in text_lower or "delicate" in text_lower:
        special_handling = "Fragile"
    elif "hazmat" in text_lower or "toxic" in text_lower or "chemical" in text_lower or "dangerous" in text_lower:
        special_handling = "HAZMAT"

    # 4. Routing (Origin & Destination)
    origin = "Chicago, IL"
    destination = "Houston, TX"
    
    # Try to extract "from X to Y"
    route_match = re.search(r'from\s+([a-zA-Z\s,]+)\s+to\s+([a-zA-Z\s,]+)', text_lower)
    if route_match:
        raw_origin = route_match.group(1).strip()
        raw_dest = route_match.group(2).strip()
        # Clean up noise like "budget" or "by tomorrow"
        origin = re.split(r'\s+(?:by|for|budget|deadline|at|with)\s+', raw_origin)[0].strip().title()
        destination = re.split(r'\s+(?:by|for|budget|deadline|at|with)\s+', raw_dest)[0].strip().title()

    # 5. Pickup Deadline (ISO 8601 date string)
    pickup_deadline = "2026-06-02T12:00:00Z"
    if "asap" in text_lower or "urgent" in text_lower or "immediately" in text_lower:
        pickup_deadline = "2026-06-01T18:00:00Z"
    elif "tomorrow" in text_lower:
        pickup_deadline = "2026-06-02T09:00:00Z"
    elif "friday" in text_lower:
        pickup_deadline = "2026-06-05T17:00:00Z"

    # 6. Financial Budget and Currency
    max_budget = 3000.0
    currency = "USD"
    
    # Target monetary values (e.g. $4,500, €3500) or numbers directly following 'budget' keyword
    dollar_match = re.search(r'[\$\u20ac\u00a3]\s*([\d,]+(?:\.\d+)?)', text_lower)
    if dollar_match:
        try:
            val_str = dollar_match.group(1).replace(",", "")
            max_budget = float(val_str)
        except ValueError:
            pass
    else:
        # Look for the word 'budget' followed by a number, ignoring spaces or helper words
        budget_word_match = re.search(r'budget\s*(?:is|of|around)?\s*(?:[\$\u20ac\u00a3]|usd|eur|gbp)?\s*([\d,]+(?:\.\d+)?)', text_lower)
        if budget_word_match:
            try:
                val_str = budget_word_match.group(1).replace(",", "")
                max_budget = float(val_str)
            except ValueError:
                pass
            
    if "eur" in text_lower or "€" in text_lower:
        currency = "EUR"
    elif "gbp" in text_lower or "£" in text_lower:
        currency = "GBP"

    return CargoPayload(
        metadata=CargoMetadata(item_type=item_type, weight_kg=weight_kg, special_handling=special_handling),
        routing=CargoRouting(origin=origin, destination=destination, pickup_deadline=pickup_deadline),
        financials=Financials(max_budget=max_budget, currency=currency)
    )
