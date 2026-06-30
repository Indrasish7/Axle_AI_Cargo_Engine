import time
from typing import Tuple
from src.geolocation import geo_service, update_vehicle_telemetry

def simulate_active_transit(vehicle_id: str, target_lat: float, target_lng: float, steps: int = 5) -> None:
    """
    Smoothly increments a vehicle's coordinates from its current position
    toward a target destination in real-time, persisting coordinates concurrently
    in the active tracking indices and relational databases at each step.
    """
    # 1. Fetch current coordinate values
    start_lat, start_lng = geo_service.get_vehicle_coordinates(vehicle_id)
    
    print("\n" + "=" * 80)
    print(f"  [SIMULATOR] ACTIVE TRANSIT SIMULATION FOR VEHICLE: {vehicle_id}")
    print(f"  From: ({start_lat:.4f}, {start_lng:.4f}) -> Target: ({target_lat:.4f}, {target_lng:.4f})")
    print("=" * 80)

    # 2. Iterate and interpolate coordinate positions
    for step in range(1, steps + 1):
        fraction = step / steps
        current_lat = start_lat + (target_lat - start_lat) * fraction
        current_lng = start_lng + (target_lng - start_lng) * fraction
        
        print(f"  [SIMULATOR] Step {step}/{steps}: Position updated to ({current_lat:.4f}, {current_lng:.4f})")
        
        # Concurrently update persistent DB columns and in-memory geospatial indices
        update_vehicle_telemetry(vehicle_id, current_lat, current_lng)
        
        # Sleep for a small, responsive duration (50ms) to simulate real-time driving
        time.sleep(0.05)
        
    print(f"  [SIMULATOR] Transit completed successfully for vehicle {vehicle_id}.\n")
