import os
import time
from fastapi.testclient import TestClient

# 1. Database Cleanup on disk BEFORE importing any database models
# This guarantees SQLite connection pools start fresh and avoid locks or stale handles.
db_file = "axle_ai.db"
db_wal = "axle_ai.db-wal"
db_shm = "axle_ai.db-shm"
for file in [db_file, db_wal, db_shm]:
    if os.path.exists(file):
        try:
            os.remove(file)
        except OSError:
            pass
print("[E2E Setup] Cleaned database files on disk.")

# Configure environment variables
os.environ["USE_MOCK_PARSER"] = "1"

# Import system layers
from src.database import init_db, SessionFactory, FleetVehicle, Booking, IdempotencyKey
from src.api import app

# Initialize TestClient
client = TestClient(app)

def print_separator(title: str):
    print("\n" + "=" * 80)
    print(f"  {title.upper()}")
    print("=" * 80)

def print_database_state():
    """Prints the current fleet and booking tables in a beautifully aligned format."""
    session = SessionFactory()
    try:
        print("\n--- CURRENT FLEET VEHICLES ---")
        print(f"{'Vehicle ID':<15} | {'Type':<12} | {'Max Capacity (kg)':<18} | {'Status':<12} | {'Location':<15}")
        print("-" * 80)
        vehicles = session.query(FleetVehicle).all()
        for v in vehicles:
            print(f"{v.vehicle_id:<15} | {v.truck_type:<12} | {v.max_weight_capacity_kg:<18,.1f} | {v.current_status.value:<12} | {v.location:<15}")
            
        print("\n--- ACTIVE BOOKINGS ---")
        bookings = session.query(Booking).all()
        if not bookings:
            print("No active bookings recorded.")
        else:
            print(f"{'Booking ID':<12} | {'Vehicle ID':<12} | {'Cargo Type':<22} | {'Weight (kg)':<12} | {'Status':<18} | {'Shipper ID':<18} | {'Budget':<10}")
            print("-" * 115)
            for b in bookings:
                print(f"{b.booking_id:<12} | {b.vehicle_id:<12} | {b.item_type:<22} | {b.weight_kg:<12,.1f} | {b.status:<18} | {str(b.shipper_id):<18} | {b.price_booked:<6.1f} {b.currency}")
                
        print("\n--- REGISTERED IDEMPOTENCY HASHES ---")
        hashes = session.query(IdempotencyKey).all()
        if not hashes:
            print("No idempotency hashes registered.")
        else:
            for idx, h in enumerate(hashes, 1):
                print(f"[{idx}] {h.hash_key} (Registered at {h.created_at})")
    finally:
        session.close()

def main():
    print_separator("E2E System Initialization")
    print("[E2E] Seeding relational database tables...")
    init_db()
    
    # Import geo_service to seed geospatial locations
    from src.geolocation import geo_service
    
    # 1. Seed geospatial coordinates for all trucks matching their DB seeded coordinates
    print("[E2E Seeding] Populating geospatial engine with initial truck positions...")
    geo_service.update_vehicle_coordinates("V-CHI-001", lng=-87.6298, lat=41.8781)  # Chicago
    geo_service.update_vehicle_coordinates("V-CHI-002", lng=-87.6231, lat=41.8818)  # Chicago Loop
    geo_service.update_vehicle_coordinates("V-ATL-003", lng=-84.3880, lat=33.7490)  # Atlanta
    geo_service.update_vehicle_coordinates("V-SEA-004", lng=-122.3321, lat=47.6062) # Seattle
    geo_service.update_vehicle_coordinates("V-LAX-005", lng=-118.2437, lat=34.0522) # LA
    geo_service.update_vehicle_coordinates("V-MIA-006", lng=-80.1918, lat=25.7617)  # Miami
    
    print_database_state()

    print_separator("Simulating Live Telemetry Ingestion & Active Transit")
    
    # 2. Telemetry Ingestion: V-CHI-001 streams a live coordinate ping to the live telemetry REST API
    # placing it outside Chicago Loop, then simulating dynamic route movement.
    start_lat, start_lng = 42.1000, -88.0000
    print(f"[E2E Telemetry] V-CHI-001 streams coordinates to /api/v1/fleet/telemetry: lat={start_lat}, lng={start_lng}")
    
    telemetry_payload = {
        "vehicle_id": "V-CHI-001",
        "latitude": start_lat,
        "longitude": start_lng
    }
    
    telemetry_response = client.post("/api/v1/fleet/telemetry", json=telemetry_payload)
    assert telemetry_response.status_code == 200, f"Expected 200, got {telemetry_response.status_code}"
    telemetry_json = telemetry_response.json()
    assert telemetry_json["status"] == "success"
    print(f"[E2E Telemetry Response] Status Code: 200 OK. Body: {telemetry_json}")

    # Verify persistent DB matches the updated float columns
    session = SessionFactory()
    try:
        db_veh = session.query(FleetVehicle).filter(FleetVehicle.vehicle_id == "V-CHI-001").first()
        assert db_veh.latitude == start_lat
        assert db_veh.longitude == start_lng
        print(f"[E2E Verification Success] Persistent db coordinates verified: lat={db_veh.latitude}, lng={db_veh.longitude}")
    finally:
        session.close()

    # 3. Simulate Active Transit: V-CHI-001 drives towards the warehouse origin in Chicago center
    from src.simulation import simulate_active_transit
    target_lat, target_lng = 41.8781, -87.6298
    simulate_active_transit("V-CHI-001", target_lat=target_lat, target_lng=target_lng, steps=5)
    
    # Define our cargo request Form urlencoded payload
    shipper_phone = "whatsapp:+15559876543"
    webhook_body = "Yo Axle! Got a rush order here. Need a Flatbed from Chicago, IL to Dallas, TX. Carrying steel coils, total load is 15 tons! Budget is around $4,500. Pickup by tomorrow morning at 8 AM. Hit me back ASAP!"
    
    print(f"\n[HTTP POST] Ingesting cargo request to /webhook/v1/whatsapp...")
    print(f"Payload (Form Data): From={shipper_phone}, Body={webhook_body}")
    
    # 1. Trigger live Twilio ingestion webhook route (using urlencoded Form data)
    response = client.post(
        "/webhook/v1/whatsapp",
        data={"From": shipper_phone, "Body": webhook_body}
    )
    
    # Assert 202 Accepted HTTP response code
    assert response.status_code == 202, f"Expected 202, got {response.status_code}"
    
    response_json = response.json()
    print(f"\n[HTTP Response] Status Code: {response.status_code} Accepted")
    print(f"[HTTP Response] Data: {response_json}")
    
    assert response_json["status"] == "Accepted"
    assert response_json["routed_to"] == "cargo_request"
    assert response_json["sender_id"] == shipper_phone
    
    # 2. Wait for the background task thread execution to complete
    print("\n[E2E] Waiting for background worker thread to process matching and negotiation...")
    time.sleep(1.0)
    
    print_separator("Verifying System State Post-Matching")
    
    # Query database to assert that the booking has been saved and matched
    session = SessionFactory()
    try:
        bookings = session.query(Booking).all()
        assert len(bookings) == 1, "Expected exactly 1 booking to be recorded."
        booking = bookings[0]
        
        # Verify matched vehicle status transitions to ON_TRIP
        vehicle = session.query(FleetVehicle).filter(FleetVehicle.vehicle_id == booking.vehicle_id).first()
        assert vehicle.current_status.value == "ON_TRIP", f"Expected vehicle status ON_TRIP, got {vehicle.current_status.value}"
        assert booking.status == "PENDING_DISPATCH", f"Expected status 'PENDING_DISPATCH', got {booking.status}"
        assert booking.shipper_id == shipper_phone, f"Expected shipper_id to be {shipper_phone}, got {booking.shipper_id}"
        
        print(f"[Assertion Success] Relational DB matches verified successfully!")
        print(f"  - Booking Created: {booking.booking_id} (Vehicle: {booking.vehicle_id})")
        print(f"  - Vehicle Status: {vehicle.vehicle_id} is now {vehicle.current_status.value}")
        print(f"  - Booking Status: {booking.status}")
        print(f"  - Booking Shipper ID: {booking.shipper_id}")
    finally:
        session.close()

    print_separator("Simulating Inbound Callback - Driver CONFIRM")
    driver_phone = "whatsapp:+15551110001" # Matches V-CHI-001 phone number
    print(f"[HTTP POST] Posting driver callback reply CONFIRM to /webhook/v1/whatsapp...")
    cb_response1 = client.post(
        "/webhook/v1/whatsapp",
        data={"From": driver_phone, "Body": "CONFIRM"}
    )
    assert cb_response1.status_code == 202
    cb_response1_json = cb_response1.json()
    print(f"[HTTP Response] Data: {cb_response1_json}")
    assert cb_response1_json["routed_to"] == "callback"
    assert cb_response1_json["sender_id"] == "V-CHI-001" # Successfully resolved to vehicle_id!
    
    print("\n[E2E] Waiting for background callback task to execute status transition to CONFIRMED...")
    time.sleep(1.0)
    
    # Verify booking status has transitioned to CONFIRMED
    session = SessionFactory()
    try:
        booking = session.query(Booking).first()
        assert booking.status == "CONFIRMED", f"Expected status 'CONFIRMED', got {booking.status}"
        print(f"[Assertion Success] Driver confirmation verified successfully!")
        print(f"  - Booking ID: {booking.booking_id} status has transitioned to: {booking.status}")
    finally:
        session.close()

    print_separator("Simulating Inbound Callback - Shipper APPROVE")
    print(f"[HTTP POST] Posting shipper callback reply APPROVE to /webhook/v1/whatsapp...")
    cb_response2 = client.post(
        "/webhook/v1/whatsapp",
        data={"From": shipper_phone, "Body": "APPROVE"}
    )
    assert cb_response2.status_code == 202
    cb_response2_json = cb_response2.json()
    print(f"[HTTP Response] Data: {cb_response2_json}")
    assert cb_response2_json["routed_to"] == "callback"
    assert cb_response2_json["sender_id"] == shipper_phone
    
    print("\n[E2E] Waiting for background callback task to execute status transition to ESCROW_AUTHORIZED...")
    time.sleep(1.0)
    
    # Verify booking status has transitioned to ESCROW_AUTHORIZED
    session = SessionFactory()
    try:
        booking = session.query(Booking).first()
        assert booking.status == "ESCROW_AUTHORIZED", f"Expected status 'ESCROW_AUTHORIZED', got {booking.status}"
        print(f"[Assertion Success] Shipper escrow authorization verified successfully!")
        print(f"  - Booking ID: {booking.booking_id} status has transitioned to: {booking.status}")
    finally:
        session.close()

    print_separator("Final System Database State")
    print_database_state()

    print_separator("Final Directory Structure Layout")
    print_tree_structure()

def print_tree_structure():
    """Prints out the finalized workspace directory structure using ASCII."""
    tree = """
d:\\Axle AI\\
|-- src/
|   |-- api.py          # FastAPI web routing & live Twilio form receiver endpoint
|   |-- database.py     # SQLAlchemy ORM, composite Point spatial schema, WAL mode, WAL lock
|   |-- geolocation.py  # Redis & thread-safe spatial coordinate tracking index
|   |-- matcher.py      # Haversine proximity matcher & vehicle geocoding
|   |-- models.py       # Pydantic v2 validation schema models
|   |-- negotiator.py   # AI conversational negotiation B2B outbound dispatch agent
|   |-- parser.py       # Google-GenAI Gemini 2.5 Flash / high-fidelity fallback
|   |-- simulation.py   # Real-time driver active transit route simulator
|   |-- twilio_client.py# Outbound Twilio WhatsApp Adaptor with ASCII console fallback
|   |-- utils.py        # SHA-256 windowed idempotency hashing
|   `-- workers.py      # Asynchronous Celery tasks & multi-threaded local fallback
|-- axle_ai.db          # Relational SQLite Database
|-- ngrok_setup.md      # Live public exposure & Twilio Sandbox operations manual
|-- test_e2e.py         # End-to-end integration and API TestClient test suite
`-- test_integration.py # Multi-threaded stress-test harness
"""
    print(tree.strip())

if __name__ == "__main__":
    main()
