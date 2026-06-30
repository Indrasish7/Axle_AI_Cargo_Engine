import uuid
from fastapi import FastAPI, BackgroundTasks, Form, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from src.workers import process_cargo_request_task, process_callback_reply_task


app = FastAPI(
    title="Axle AI B2B Cargo Matching Engine API",
    description="Live webhook ingestion and carrier negotiation pipeline.",
    version="1.0.0"
)

@app.on_event("startup")
def load_geospatial_index():
    from src.database import db_session, FleetVehicle
    from src.geolocation import geo_service
    print("[Startup] Seeding in-memory geospatial index from persistent database...")
    try:
        with db_session() as session:
            vehicles = session.query(FleetVehicle).all()
            count = 0
            for v in vehicles:
                if v.latitude is not None and v.longitude is not None:
                    geo_service.update_vehicle_coordinates(v.vehicle_id, lng=v.longitude, lat=v.latitude)
                    count += 1
        print(f"[Startup] Successfully seeded {count} vehicle coordinates into geospatial index.")
    except Exception as e:
        print(f"[Startup Error] Failed to seed geospatial index: {e}")


class ShipperWebhookPayload(BaseModel):
    sender_id: str = Field(
        ..., 
        description="Simulated phone number, WhatsApp ID, or broker email address (e.g. 'whatsapp-user-82')."
    )
    message_text: str = Field(
        ..., 
        description="Conversational, unstructured text request detailing cargo weight, origin, destination, and budget."
    )

class CallbackWebhookPayload(BaseModel):
    sender_id: str = Field(
        ...,
        description="The messaging sender (e.g. vehicle_id like 'V-CHI-001' or shipper_id like 'whatsapp-user-82')."
    )
    reply_text: str = Field(
        ...,
        description="Inbound text content sent in reply (e.g. 'CONFIRM' or 'APPROVE')."
    )

class TelemetryPayload(BaseModel):
    vehicle_id: str = Field(
        ..., 
        description="Unique fleet vehicle tracking identifier (e.g. 'V-CHI-001')."
    )
    latitude: float = Field(
        ..., 
        description="Current latitude coordinate value."
    )
    longitude: float = Field(
        ..., 
        description="Current longitude coordinate value."
    )

@app.post("/webhook/v1/shipper", status_code=status.HTTP_202_ACCEPTED)
def ingest_shipper_request(payload: ShipperWebhookPayload, background_tasks: BackgroundTasks):
    """
    Accepts an incoming unstructured text request (simulating a webhook from WhatsApp/Email).
    Performs standard schema validation, registers a background task to process, geocode,
    and match the load asynchronously, and returns an immediate 202 Accepted response.
    """
    # Generate a unique tracking job ID
    job_id = f"JOB-{uuid.uuid4().hex[:8].upper()}"
    
    # Delegate task processing to execution threads in the background
    background_tasks.add_task(
        process_cargo_request_sync,
        sender_id=payload.sender_id,
        raw_text=payload.message_text
    )
    
    return {
        "status": "Accepted",
        "job_id": job_id,
        "message": "Conversational request received and scheduled for matching.",
        "tracking_endpoint": f"/api/v1/jobs/{job_id}"
    }

@app.post("/webhook/v1/callback", status_code=status.HTTP_202_ACCEPTED)
def ingest_inbound_callback(payload: CallbackWebhookPayload, background_tasks: BackgroundTasks):
    """
    Accepts an incoming B2B SMS/WhatsApp reply callback webhook from a matched driver or shipper.
    Validates, registers a background thread task to process the state-machine transition,
    and returns a 202 Accepted response.
    """
    callback_job_id = f"CB-{uuid.uuid4().hex[:8].upper()}"
    
    background_tasks.add_task(
        process_callback_reply_sync,
        sender_id=payload.sender_id,
        reply_text=payload.reply_text
    )
    
    return {
        "status": "Accepted",
        "callback_job_id": callback_job_id,
        "message": "Inbound reply callback received and scheduled for state-machine transition."
    }

from fastapi import Request, Response
import os

@app.get("/webhook/v1/whatsapp")
def verify_whatsapp_webhook(request: Request):
    """
    Handles Meta's Webhook verification challenge (GET).
    """
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")
    
    meta_verify_token = os.environ.get("META_VERIFY_TOKEN", "")
    
    if mode == "subscribe" and token == meta_verify_token:
        # Return challenge as raw text
        return Response(content=challenge, media_type="text/plain")
    return Response(content="Verification failed", status_code=403)

@app.post("/webhook/v1/whatsapp", status_code=status.HTTP_202_ACCEPTED)
async def ingest_whatsapp_webhook(
    request: Request,
    background_tasks: BackgroundTasks
):
    """
    Accepts Meta's incoming JSON webhook payload or Twilio's form-urlencoded payload.
    Dynamically routes the message to either the callback transition worker (state-machine)
    or the cargo ingestion worker based on the sender's phone number mapping to database state.
    """
    from src.database import db_session, FleetVehicle, Booking

    content_type = request.headers.get("content-type", "")
    From = None
    Body = None

    if "application/json" in content_type:
        payload = await request.json()
        
        try:
            # Check if the incoming payload is using Meta's nested structure
            if "entry" in payload and payload["entry"]:
                changes = payload["entry"][0].get("changes", [])
                if changes:
                    value = changes[0].get("value", {})
                    messages = value.get("messages", [])
                    if messages:
                        user_text = messages[0].get("text", {}).get("body", "")
                        sender_phone = messages[0].get("from", "")
                        
                        From = sender_phone
                        Body = user_text
        except Exception as e:
            print(f"Extraction Error: {str(e)}")

        # Normalize Meta sender phone to have whatsapp:+ prefix for DB matching compatibility
        if From:
            if not From.startswith("whatsapp:"):
                if not From.startswith("+"):
                    From = f"+{From}"
                From = f"whatsapp:{From}"
    else:
        # Fallback to form-urlencoded parsing (Twilio simulator / tests)
        form_data = await request.form()
        From = form_data.get("From")
        Body = form_data.get("Body")

    if not From or not Body:
        return {"status": "ignored", "message": "Incomplete webhook payload."}

    routed_callback = False
    callback_sender_id = None
    
    with db_session() as session:
        # Check if From matches a driver's phone number
        vehicle = session.query(FleetVehicle).filter(FleetVehicle.driver_phone == From).first()
        if vehicle:
            # Check if there is an active booking requiring validation (status 'PENDING_DISPATCH') for this vehicle
            active_booking = session.query(Booking).filter(
                Booking.vehicle_id == vehicle.vehicle_id,
                Booking.status == "PENDING_DISPATCH"
            ).first()
            if active_booking:
                routed_callback = True
                callback_sender_id = vehicle.vehicle_id

        # If not already routed as driver, check if From matches a shipper_id with active unconfirmed booking
        if not routed_callback:
            active_booking = session.query(Booking).filter(
                Booking.shipper_id == From,
                Booking.status.in_(["PENDING_DISPATCH", "CONFIRMED"])
            ).first()
            if active_booking:
                routed_callback = True
                callback_sender_id = From

    if routed_callback:
        # Route to Celery callback reply task
        process_callback_reply_task.delay(
            sender_id=callback_sender_id,
            reply_text=Body
        )
        return {
            "status": "Accepted",
            "routed_to": "callback",
            "sender_id": callback_sender_id,
            "message": "WhatsApp reply callback received and queued via Celery."
        }
    else:
        # Route to brand-new Celery cargo order task
        process_cargo_request_task.delay(
            sender_id=From,
            raw_text=Body
        )
        return {
            "status": "Accepted",
            "routed_to": "cargo_request",
            "sender_id": From,
            "message": "WhatsApp cargo request received and queued via Celery."
        }


@app.post("/api/v1/fleet/telemetry", status_code=status.HTTP_200_OK)
def update_fleet_telemetry(payload: TelemetryPayload):
    """
    Exposes a high-throughput fleet telemetry ingestion endpoint.
    Accepts real-time coordinate updates from active vehicle GPS modules,
    updating both the geospatial index and relational persistent DB columns concurrently.
    """
    from src.geolocation import update_vehicle_telemetry
    
    update_vehicle_telemetry(
        vehicle_id=payload.vehicle_id,
        lat=payload.latitude,
        lng=payload.longitude
    )
    
    return {
        "status": "success",
        "message": f"Telemetry coordinates for vehicle {payload.vehicle_id} registered successfully."
    }

@app.get("/health", status_code=status.HTTP_200_OK)
def health_check():
    """Service health verification endpoint."""
    return {"status": "healthy", "service": "Axle AI Engine"}

@app.get("/api/v1/dashboard/data")
def get_dashboard_data():
    """
    Retrieves serialized bookings and fleet vehicles data for command center rendering.
    """
    from src.database import db_session, Booking, FleetVehicle
    
    with db_session() as session:
        # 1. Fetch and serialize vehicles
        vehicles_db = session.query(FleetVehicle).all()
        vehicles = []
        active_vehicles = 0
        for v in vehicles_db:
            vehicles.append({
                "vehicle_id": v.vehicle_id,
                "truck_type": v.truck_type,
                "max_weight_capacity_kg": v.max_weight_capacity_kg,
                "current_status": v.current_status.value,
                "driver_phone": v.driver_phone or "",
                "latitude": v.latitude,
                "longitude": v.longitude,
                "location": v.location
            })
            if v.current_status.value in ["AVAILABLE", "ON_TRIP"]:
                active_vehicles += 1
                
        # 2. Fetch and serialize bookings
        bookings_db = session.query(Booking).order_by(Booking.booked_at.desc()).all()
        bookings = []
        total_weight_kg = 0.0
        escrow_value_usd = 0.0
        active_matches = 0
        for b in bookings_db:
            bookings.append({
                "booking_id": b.booking_id,
                "vehicle_id": b.vehicle_id,
                "item_type": b.item_type,
                "weight_kg": b.weight_kg,
                "origin": b.origin,
                "destination": b.destination,
                "price_booked": b.price_booked,
                "currency": b.currency,
                "status": b.status,
                "shipper_id": b.shipper_id or "",
                "booked_at": b.booked_at.isoformat()
            })
            total_weight_kg += b.weight_kg
            if b.status == "ESCROW_AUTHORIZED":
                escrow_value_usd += b.price_booked
            if b.status in ["PENDING_DISPATCH", "CONFIRMED"]:
                active_matches += 1

        stats = {
            "active_vehicles": active_vehicles,
            "total_weight_kg": total_weight_kg,
            "escrow_value_usd": escrow_value_usd,
            "active_matches": active_matches
        }
        
        return {
            "vehicles": vehicles,
            "bookings": bookings,
            "stats": stats
        }

@app.get("/dashboard", response_class=HTMLResponse)
def serve_dashboard():
    """Serves the central control room HTML template."""
    import os
    template_path = "index.html"
    if not os.path.exists(template_path):
         return HTMLResponse("<h2>Dashboard template (index.html) not found in root.</h2>", status_code=404)
    with open(template_path, "r", encoding="utf-8") as f:
         content = f.read()
    return HTMLResponse(content)


