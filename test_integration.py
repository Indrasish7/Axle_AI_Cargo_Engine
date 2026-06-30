import os
import time
import concurrent.futures

# Clean up database files on disk BEFORE importing SQLAlchemy modules
# This guarantees SQLite doesn't reuse connections to stale or deleted file descriptors.
db_file = "axle_ai.db"
db_wal = "axle_ai.db-wal"
db_shm = "axle_ai.db-shm"
for file in [db_file, db_wal, db_shm]:
    if os.path.exists(file):
        try:
            os.remove(file)
        except OSError:
            pass
print("[Setup] Cleaned database files on disk.")

# Now import the database and worker modules
from sqlalchemy import text
from src.database import init_db, engine, SessionFactory, FleetVehicle, Booking, IdempotencyKey
from src.workers import process_cargo_request_task

# Configuration: Enable high-fidelity mock parser for self-verification
os.environ["USE_MOCK_PARSER"] = "1"

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
            print(f"{'Booking ID':<12} | {'Vehicle ID':<12} | {'Cargo Type':<22} | {'Weight (kg)':<12} | {'Origin':<15} | {'Budget':<10}")
            print("-" * 90)
            for b in bookings:
                print(f"{b.booking_id:<12} | {b.vehicle_id:<12} | {b.item_type:<22} | {b.weight_kg:<12,.1f} | {b.origin:<15} | {b.price_booked:<6.1f} {b.currency}")
                
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
    
    print_separator("System Initialization")
    print("[Init] Seeding relational database tables...")
    init_db()
    print_database_state()

    print_separator("Simulating Chaotic Webhook Ingestion")
    
    # 3 Real-World logistics text requests containing slang, conversational elements,
    # messy formats, and variable weight metrics.
    requests = [
        # Request A: High budget, Flatbed in Chicago, 15 tons weight
        {
            "sender_id": "whatsapp-user-82",
            "text": "Yo Axle! Sender: whatsapp-user-82. Got a rush order here. Need a Flatbed from Chicago, IL to Dallas, TX. Carrying steel coils, total load is 15 tons! Budget is around $4,500. Pickup by tomorrow morning at 8 AM. Hit me back ASAP!"
        },
        # Request B (Concurrent Weight/Proximity Conflict): Steel pipes in Chicago Loop, 22 tons.
        # Only V-CHI-002 (Flatbed 25,000 kg capacity) can take this weight.
        # V-CHI-001 (Dry Van, 20,000 kg capacity) is too small!
        # This will trigger database locks as they compete for V-CHI-002!
        {
            "sender_id": "email-broker-99",
            "text": "Axle AI dispatcher - sender: email-broker-99. High urgency shipment. Steel pipes from Chicago Loop to Houston, TX. Load weight: 22 tons. Max budget: 6000 USD. Need it picked up by tomorrow."
        },
        # Request C: Cold chain cargo in Atlanta, 8,000 lbs weight.
        # Requires reefer temp-control. Matches V-ATL-003 (Reefer, Atlanta).
        {
            "sender_id": "whatsapp-user-11",
            "text": "Yo dispatcher! sender: whatsapp-user-11. Got a cold cargo load of frozen salmon. Atlanta to Miami, FL. Weight: 8,000 lbs. Budget: 3500. Needs reefer temp control, pickup by Friday. Cheers!"
        }
    ]

    print("[Stress Test] Spawning 3 concurrent asynchronous workers via simulated Celery Queue...")
    
    # Dispatch tasks concurrently to trigger locking and matching competition
    results = []
    start_time = time.time()
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(process_cargo_request_task.delay, r["sender_id"], r["text"]): r["sender_id"] 
            for r in requests
        }
        
        for future in concurrent.futures.as_completed(futures):
            sender = futures[future]
            try:
                # Retrieve standard Celery AsyncResult simulator
                task_res = future.result()
                # Block until result is ready
                result_data = task_res.get()
                results.append(result_data)
                print(f"[Queue Log] Task finished for sender {sender}: status={result_data['status']}")
            except Exception as exc:
                print(f"[Queue Log] Task generated an exception for sender {sender}: {exc}")
                
    elapsed = time.time() - start_time
    print(f"\n[Stress Test] All concurrent requests processed in {elapsed:.4f} seconds.")
    
    print_separator("Idempotency Verification")
    print("[Idempotency Test] Re-submitting the exact same webhook for whatsapp-user-82...")
    
    # Send the duplicate webhook
    dup_req = requests[0]
    task_res = process_cargo_request_task.delay(dup_req["sender_id"], dup_req["text"])
    dup_result = task_res.get()
    
    print(f"[Idempotency Result] Status: {dup_result['status']}")
    print(f"[Idempotency Result] Message: {dup_result.get('message', 'N/A')}")
    print(f"[Idempotency Result] Hash Blocked: {dup_result.get('hash_key')}")

    print_separator("Final Relational System State")
    print_database_state()

    print_separator("Directory Structure Layout")
    print_tree_structure()

def print_tree_structure():
    """Prints out the finalized workspace directory structure using ASCII."""
    tree = """
d:\\Axle AI\\
|-- src/
|   |-- database.py     # SQLAlchemy ORM, SQLite WAL mode, BEGIN IMMEDIATE lock
|   |-- matcher.py      # Haversine proximity matcher & vehicle geocoding
|   |-- models.py       # Pydantic v2 validation schema models
|   |-- parser.py       # Google-GenAI Gemini 2.5 Flash / high-fidelity fallback
|   |-- utils.py        # SHA-256 windowed idempotency hashing
|   `-- workers.py      # Asynchronous Celery tasks & multi-threaded local fallback
|-- axle_ai.db          # Relational SQLite Database
`-- test_integration.py # Multi-threaded stress-test harness
"""
    print(tree.strip())

if __name__ == "__main__":
    main()
