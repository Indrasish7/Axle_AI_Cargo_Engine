import time
import math
import urllib.request
import json
import os
import sys

# Ensure project root is in python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.database import db_session, Booking, FleetVehicle
from src.matcher import geocode_location

def calculate_bearing(lat1, lon1, lat2, lon2):
    """Calculates the bearing (heading angle) between two points in degrees."""
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    d_lon = math.radians(lon2 - lon1)
    
    y = math.sin(d_lon) * math.cos(lat2_rad)
    x = math.cos(lat1_rad) * math.sin(lat2_rad) - math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(d_lon)
    
    bearing = math.atan2(y, x)
    return (math.degrees(bearing) + 360) % 360

def get_cardinal_direction(bearing):
    """Resolves bearing angle into a compass cardinal direction."""
    directions = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                  "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    idx = int((bearing + 11.25) / 22.5) % 16
    return directions[idx]

def get_interpolated_route(origin_str, dest_str, steps=100):
    """Generates steps coordinates between origin and destination."""
    origin_lat, origin_lng = geocode_location(origin_str)
    dest_lat, dest_lng = geocode_location(dest_str)
    
    route = []
    for i in range(steps):
        fraction = i / (steps - 1)
        lat = origin_lat + (dest_lat - origin_lat) * fraction
        lng = origin_lng + (dest_lng - origin_lng) * fraction
        route.append((lat, lng))
    return route

def find_closest_step(curr_lat, curr_lng, route):
    """Finds the index of the point on the route closest to current coordinates."""
    min_dist = float("inf")
    closest_idx = 0
    for idx, (lat, lng) in enumerate(route):
        dist = (lat - curr_lat) ** 2 + (lng - curr_lng) ** 2
        if dist < min_dist:
            min_dist = dist
            closest_idx = idx
    return closest_idx

def send_telemetry_update(vehicle_id, lat, lng):
    """Attempts to update coordinates via FastAPI telemetry API; falls back to direct DB write."""
    api_url = "http://localhost:8000/api/v1/fleet/telemetry"
    payload = {
        "vehicle_id": vehicle_id,
        "latitude": lat,
        "longitude": lng
    }
    data = json.dumps(payload).encode("utf-8")
    
    try:
        req = urllib.request.Request(
            api_url, 
            data=data, 
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=2) as response:
            return response.status == 200
    except Exception as e:
        # Fallback to direct DB write if API is down or unavailable
        try:
            from src.geolocation import update_vehicle_telemetry
            update_vehicle_telemetry(vehicle_id, lat, lng)
            return True
        except Exception as db_err:
            print(f"  [SIMULATOR ERROR] Telemetry persistence fallback failed: {db_err}")
            return False

def run_telemetry_simulation(interval_seconds=3):
    print("=" * 80)
    print("           AXLE AI REAL-TIME DRIVER TELEMETRY SIMULATOR ACTIVE           ")
    print("=" * 80)
    print(f"Monitoring axle_ai.db for active bookings. Sync interval: {interval_seconds}s\n")
    
    while True:
        try:
            active_jobs = []
            with db_session() as session:
                # Query bookings in ESCROW_AUTHORIZED or ON_TRIP
                active_bookings = session.query(Booking).filter(
                    Booking.status.in_(["ESCROW_AUTHORIZED", "ON_TRIP"])
                ).all()
                
                for booking in active_bookings:
                    vehicle_id = booking.vehicle_id
                    vehicle = session.query(FleetVehicle).filter(
                        FleetVehicle.vehicle_id == vehicle_id
                    ).first()
                    
                    if vehicle:
                        active_jobs.append({
                            "booking_id": booking.booking_id,
                            "vehicle_id": vehicle_id,
                            "origin": booking.origin,
                            "destination": booking.destination,
                            "curr_lat": vehicle.latitude,
                            "curr_lng": vehicle.longitude
                        })
            
            if not active_jobs:
                print("[Simulator] Idle. No active ESCROW_AUTHORIZED or ON_TRIP bookings found.")
            else:
                for job in active_jobs:
                    booking_id = job["booking_id"]
                    vehicle_id = job["vehicle_id"]
                    origin = job["origin"]
                    destination = job["destination"]
                    curr_lat = job["curr_lat"]
                    curr_lng = job["curr_lng"]
                    
                    # Generate route points
                    route = get_interpolated_route(origin, destination)
                    closest_idx = find_closest_step(curr_lat, curr_lng, route)
                    
                    # Calculate next step
                    if closest_idx >= len(route) - 1:
                        # Arrived! Wrap around to restart route simulation for demo loop
                        next_idx = 0
                        next_lat, next_lng = route[next_idx]
                        print(f"  [Arrived] Booking {booking_id} ({vehicle_id}) reached {destination}. Resetting to origin {origin} for simulation loop.")
                    else:
                        next_idx = closest_idx + 1
                        next_lat, next_lng = route[next_idx]
                        
                    # Calculate bearing and heading
                    bearing = calculate_bearing(curr_lat, curr_lng, next_lat, next_lng)
                    cardinal = get_cardinal_direction(bearing)
                    
                    # Update telemetry
                    success = send_telemetry_update(vehicle_id, next_lat, next_lng)
                    
                    if success:
                        progress_pct = (next_idx / (len(route) - 1)) * 100
                        print(f"  [Telemetry Pulse] Booking: {booking_id} | Vehicle: {vehicle_id} | "
                              f"Route: {origin} -> {destination} | "
                              f"Step: {next_idx + 1}/100 ({progress_pct:.1f}%) | "
                              f"Coords: ({next_lat:.4f}, {next_lng:.4f}) | "
                              f"Heading: {bearing:.1f}° ({cardinal})")
                    else:
                        print(f"  [Simulator Warning] Failed to update telemetry for vehicle {vehicle_id}.")
                        
        except Exception as err:
            print(f"[Simulator Loop Exception] Encountered error: {err}")
            
        time.sleep(interval_seconds)

if __name__ == "__main__":
    # Start simulation with a 3 second interval
    run_telemetry_simulation(interval_seconds=3)
