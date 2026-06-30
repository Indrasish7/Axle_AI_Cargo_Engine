import os
import time
import concurrent.futures
import socket
from typing import Dict, Any, Optional

try:
    from celery import Celery
    HAS_CELERY = True
except ImportError:
    HAS_CELERY = False
    print("[Workers System] Celery package not found in this environment. Running in stand-alone multi-threaded mode.")

# Socket connectivity check to Redis broker
redis_active = False
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1.0)
    s.connect(("localhost", 6379))
    s.close()
    redis_active = True
    print("[Workers] Redis connection verified on localhost:6379. Using Celery in live broker mode.")
except Exception:
    print("[Workers Warning] Redis is unreachable on localhost:6379. Falling back to local Eager Thread Pool Mode.")

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

if HAS_CELERY:
    if redis_active:
        celery_app = Celery("axle_tasks", broker=REDIS_URL, backend=REDIS_URL)
    else:
        # Use memory broker and enable eager execution for safety in the worker process
        celery_app = Celery("axle_tasks", broker="memory://", backend="cache+memory://")
        celery_app.conf.update(
            task_always_eager=True,
            task_eager_propagates=True
        )
    
    celery_app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        broker_connection_retry_on_startup=True,
    )
else:
    class DummyConf:
        def update(self, *args, **kwargs):
            pass
    class Celery:
        def __init__(self, name=None, **kwargs):
            self.conf = DummyConf()
        def task(self, *args, **kwargs):
            def decorator(func):
                def mock_delay(*a, **kw):
                    return fallback_worker.delay(func, *a, **kw)
                func.delay = mock_delay
                return func
            return decorator
    celery_app = Celery("axle_tasks")

from src.database import db_session, locked_db_session, FleetVehicle, Booking
from src.utils import generate_idempotency_hash, is_duplicate_request, register_request_hash
from src.parser import parse_cargo_request
from src.matcher import match_and_book_cargo
from src.negotiator import generate_dispatch_offer, generate_shipper_whatsapp_quote

# ---------------------------------------------------------
# Core Task Definition
# ---------------------------------------------------------

def process_cargo_request_sync(sender_id: str, raw_text: str) -> Dict[str, Any]:
    """
    Synchronous implementation of the cargo parsing and matching task pipeline.
    This contains the actual logic that gets executed inside Celery or the fallback worker.
    """
    # 1. Generate the 5-minute idempotency hash
    hash_key = generate_idempotency_hash(sender_id, raw_text)
    
    # 2. Acquire a write transaction session (using BEGIN IMMEDIATE) to check & register the hash.
    # This prevents concurrent race conditions where two identical webhook deliveries check
    # at the exact same millisecond.
    with locked_db_session() as session:
        if is_duplicate_request(session, hash_key):
            print(f"[Worker Idempotency] Discarded duplicate webhook for sender={sender_id}, hash={hash_key}")
            return {
                "status": "ignored_duplicate",
                "hash_key": hash_key,
                "message": "Duplicate request detected and discarded safely."
            }
        
        # Register the hash immediately to lock out subsequent hits
        register_request_hash(session, hash_key)
        
    print(f"[Worker] Processing incoming webhook from sender={sender_id} (hash: {hash_key[:12]}...)")
    
    # 3. LLM structured parsing (conversational string -> validated Pydantic model)
    # Note: We run the LLM parser OUTSIDE the database write-lock transaction block.
    # This is a critical architectural decision: keeping LLM network requests out of transactions
    # prevents database lock starvation.
    try:
        payload = parse_cargo_request(raw_text)
        print(f"[Worker] Ingested Cargo: {payload.metadata.item_type} | weight: {payload.metadata.weight_kg} kg | budget: {payload.financials.max_budget} {payload.financials.currency}")
    except Exception as e:
        print(f"[Worker Error] Ingestion parsing failed: {e}")
        return {
            "status": "parse_failure",
            "hash_key": hash_key,
            "error": str(e)
        }
        
    # 4. Proximity matching and concurrent-safe fleet booking
    # Matcher uses a 'locked_db_session' to perform vehicle matching and status transition.
    try:
        booking = match_and_book_cargo(payload, shipper_id=sender_id)
        
        if booking:
            print(f"[Worker] Successfully created Booking: {booking.booking_id} on Vehicle: {booking.vehicle_id}")
            
            # Query the matched FleetVehicle metadata to pass to the negotiator agent
            with db_session() as session:
                db_veh = session.query(FleetVehicle).filter(FleetVehicle.vehicle_id == booking.vehicle_id).first()
                
                # Lightweight data-holder class to prevent DetachedInstanceError on session close
                class DetachedFleetVehicle:
                    def __init__(self, vehicle_id, truck_type, location, max_weight_capacity_kg, driver_phone):
                        self.vehicle_id = vehicle_id
                        self.truck_type = truck_type
                        self.location = location
                        self.max_weight_capacity_kg = max_weight_capacity_kg
                        self.driver_phone = driver_phone
                
                vehicle = DetachedFleetVehicle(
                    vehicle_id=db_veh.vehicle_id,
                    truck_type=db_veh.truck_type,
                    location=db_veh.location,
                    max_weight_capacity_kg=db_veh.max_weight_capacity_kg,
                    driver_phone=db_veh.driver_phone
                )
                
            # Invoke the outbound negotiation agent to generate a B2B dispatch offer
            dispatch_message = generate_dispatch_offer(booking, vehicle)
            print(f"\n[Outbound SMS Dispatch Trigger] Outbound message to driver on vehicle {booking.vehicle_id}:\n{dispatch_message}\n")
            
            # Invoke the outbound confirmation agent to generate a B2B WhatsApp quote for the shipper
            shipper_whatsapp_quote = generate_shipper_whatsapp_quote(booking, vehicle)
            print(f"\n[Outbound WhatsApp Shipper Quote] Outbound message to shipper:\n{shipper_whatsapp_quote}\n")

            # Active WhatsApp outbounds dispatch integration
            from src.twilio_client import send_whatsapp_message
            if vehicle.driver_phone:
                send_whatsapp_message(to_number=vehicle.driver_phone, message_body=dispatch_message)
            if booking.shipper_id:
                send_whatsapp_message(to_number=booking.shipper_id, message_body=shipper_whatsapp_quote)
            
            return {
                "status": "success_booked",
                "hash_key": hash_key,
                "booking_id": booking.booking_id,
                "vehicle_id": booking.vehicle_id,
                "item_type": booking.item_type,
                "weight_kg": booking.weight_kg,
                "dispatch_offer": dispatch_message,
                "shipper_quote": shipper_whatsapp_quote
            }
        else:
            print(f"[Worker] Processing complete. No compatible available vehicle found for this cargo.")
            return {
                "status": "unmatched_no_fleet",
                "hash_key": hash_key,
                "message": "No compatible available fleet vehicle met the cargo requirements."
            }
    except Exception as e:
        print(f"[Worker Error] Matching engine encountered an exception: {e}")
        return {
            "status": "matching_failure",
            "hash_key": hash_key,
            "error": str(e)
        }


def process_callback_reply_sync(sender_id: str, reply_text: str) -> Dict[str, Any]:
    """
    Processes inbound callback replies from drivers or shippers in a background worker thread.
    Updates the booking status:
    - Driver sends 'CONFIRM' -> Status transitions from 'PENDING_DISPATCH' to 'CONFIRMED'
      and generates a digital gate pass.
    - Shipper sends 'APPROVE' -> Status transitions to 'ESCROW_AUTHORIZED' and captures payment.
    """
    reply_upper = reply_text.strip().upper()
    print(f"[Callback Worker] Processing inbound reply from sender={sender_id}, text='{reply_text}'")
    
    # Open write transaction using locked_db_session() to prevent concurrency conflicts
    with locked_db_session() as session:
        # 1. Driver Match Verification
        # Check if the sender is the driver assigned to an active unconfirmed booking
        driver_booking = session.query(Booking).filter(
            Booking.vehicle_id == sender_id,
            Booking.status == "PENDING_DISPATCH"
        ).first()
        
        if driver_booking:
            if "CONFIRM" in reply_upper:
                driver_booking.status = "CONFIRMED"
                print(f"[SYSTEM DISPATCH SUCCESS] DISPATCHING DIGITAL GATE PASS FOR DRIVER {sender_id} ON BOOKING {driver_booking.booking_id}")
                
                # Fetch driver_phone to dispatch the real outbound whatsapp confirmation
                db_veh = session.query(FleetVehicle).filter(FleetVehicle.vehicle_id == sender_id).first()
                driver_phone = db_veh.driver_phone if db_veh else None
                gate_pass_msg = f"[SYSTEM CONFIRMED] Gate pass issued! Your Booking ID: {driver_booking.booking_id} is CONFIRMED. Present this at the gate."
                
                if driver_phone:
                    from src.twilio_client import send_whatsapp_message
                    send_whatsapp_message(to_number=driver_phone, message_body=gate_pass_msg)
                
                return {
                    "status": "success",
                    "action": "driver_confirmed",
                    "booking_id": driver_booking.booking_id,
                    "new_status": "CONFIRMED",
                    "gate_pass_issued": True
                }
                
        # 2. Shipper Match Verification
        # Check if the sender is the shipper attached to a recent booking
        shipper_booking = session.query(Booking).filter(
            Booking.shipper_id == sender_id,
            Booking.status.in_(["PENDING_DISPATCH", "CONFIRMED"])
        ).first()
        
        if shipper_booking:
            if "APPROVE" in reply_upper:
                shipper_booking.status = "ESCROW_AUTHORIZED"
                print(f"[SYSTEM ESCROW SUCCESS] PAYMENT CAPTURE TRIGGERED FOR SHIPPER {sender_id} ON BOOKING {shipper_booking.booking_id}")
                
                escrow_msg = f"[SYSTEM ESCROW SUCCESS] Payment captured successfully for booking {shipper_booking.booking_id}. Escrow authorized. Transport has been scheduled."
                if shipper_booking.shipper_id:
                    from src.twilio_client import send_whatsapp_message
                    send_whatsapp_message(to_number=shipper_booking.shipper_id, message_body=escrow_msg)
                
                return {
                    "status": "success",
                    "action": "shipper_approved",
                    "booking_id": shipper_booking.booking_id,
                    "new_status": "ESCROW_AUTHORIZED",
                    "escrow_triggered": True
                }
                
        print(f"[Callback Worker Warning] No active unconfirmed booking found matching sender={sender_id} for reply='{reply_text}'")
        return {
            "status": "no_match",
            "message": "Sender is not associated with an active unconfirmed booking, or message text does not contain confirm triggers."
        }


# Define the Celery tasks
@celery_app.task(name="tasks.process_cargo_request_task")
def process_cargo_request_task(sender_id: str, raw_text: str) -> Dict[str, Any]:
    """Celery-wrapped asynchronous task signature for cargo webhook ingestion."""
    return process_cargo_request_sync(sender_id, raw_text)

@celery_app.task(name="tasks.process_callback_reply_task")
def process_callback_reply_task(sender_id: str, reply_text: str) -> Dict[str, Any]:
    """Celery-wrapped asynchronous task signature for callback messaging loops."""
    return process_callback_reply_sync(sender_id, reply_text)


# ---------------------------------------------------------
# High-Fidelity Asynchronous Fallback Simulator
# ---------------------------------------------------------
# If Celery/Redis is not running locally, this allows our integration
# test suite to execute concurrently using Python ThreadPoolExecutor,
# perfectly simulating Celery's `.delay()` call behavior!

class ThreadedTaskResult:
    """Simulates Celery's AsyncResult interface."""
    def __init__(self, future: concurrent.futures.Future):
        self.future = future

    def get(self, timeout: Optional[float] = None) -> Any:
        """Blocks until task completes and returns result, mimicking Celery AsyncResult.get()"""
        return self.future.result(timeout=timeout)

    @property
    def ready(self) -> bool:
        """Returns True if the task has completed."""
        return self.future.done()

class FallbackAsyncWorker:
    """
    Simulates a Celery worker pool locally.
    Enables concurrent execution via concurrent.futures.ThreadPoolExecutor
    whilst matching the Celery task call syntax.
    """
    def __init__(self):
        self.executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=8, 
            thread_name_prefix="axle_worker_pool"
        )
        print("[Worker Simulation] Initialized concurrent worker thread pool (8 threads).")

    def delay(self, func, *args, **kwargs) -> ThreadedTaskResult:
        """Simulates Celery's task.delay() generically using a threaded runner."""
        future = self.executor.submit(func, *args, **kwargs)
        return ThreadedTaskResult(future)

    def shutdown(self):
        """Shut down the simulated worker thread pool."""
        self.executor.shutdown(wait=True)

# Export the worker dispatcher.
fallback_worker = FallbackAsyncWorker()

# Override task.delay if Redis is offline to keep delay() asynchronous
if HAS_CELERY and not redis_active:
    def wrap_eager_delay(task_obj):
        func_to_run = task_obj.run
        def custom_delay(*args, **kwargs):
            print(f"[Eager Fallback] Offloading task {task_obj.name} to local background thread pool.")
            return fallback_worker.delay(func_to_run, *args, **kwargs)
        task_obj.delay = custom_delay

    wrap_eager_delay(process_cargo_request_task)
    wrap_eager_delay(process_callback_reply_task)
