import math
import uuid
import datetime
from typing import Optional, Tuple, List, Dict
from sqlalchemy.orm import Session
from src.models import CargoPayload
from src.database import FleetVehicle, Booking, VehicleStatus, locked_db_session

# High-fidelity mock geocoding database for logistics routing
CITY_COORDINATES: Dict[str, Tuple[float, float]] = {
    "chicago": (41.8781, -87.6298),
    "chicago, il": (41.8781, -87.6298),
    "chicago loop": (41.8818, -87.6231),
    "atlanta": (33.7490, -84.3880),
    "atlanta, ga": (33.7490, -84.3880),
    "seattle": (47.6062, -122.3321),
    "seattle, wa": (47.6062, -122.3321),
    "los angeles": (34.0522, -118.2437),
    "los angeles, ca": (34.0522, -118.2437),
    "la": (34.0522, -118.2437),
    "miami": (25.7617, -80.1918),
    "miami, fl": (25.7617, -80.1918),
    "houston": (29.7604, -95.3698),
    "houston, tx": (29.7604, -95.3698),
    "new york": (40.7128, -74.0060),
    "new york, ny": (40.7128, -74.0060),
    "boston": (42.3601, -71.0589),
    "boston, ma": (42.3601, -71.0589),
    "dallas": (32.7767, -96.7970),
    "dallas, tx": (32.7767, -96.7970),
}

def geocode_location(location_str: str) -> Tuple[float, float]:
    """
    Parses a location string into coordinates (latitude, longitude).
    If it is a coordinate string like '40.7128,-74.0060', parses it.
    Otherwise, resolves it using the CITY_COORDINATES dictionary, falling back
    to a default coordinate if unresolved.
    """
    cleaned = location_str.strip().lower()
    
    # Try parsing as coordinate format (e.g. "41.8781, -87.6298")
    if "," in cleaned:
        parts = cleaned.split(",")
        if len(parts) == 2:
            try:
                lat = float(parts[0].strip())
                lon = float(parts[1].strip())
                return lat, lon
            except ValueError:
                pass
                
    # Search dictionary keys for matches
    for key, coords in CITY_COORDINATES.items():
        if key in cleaned or cleaned in key:
            return coords
            
    # Default to Chicago central coordinates if unresolved
    print(f"[Matcher Warning] Location '{location_str}' could not be resolved. Defaulting to Chicago.")
    return (41.8781, -87.6298)

def haversine_distance(coords1: Tuple[float, float], coords2: Tuple[float, float]) -> float:
    """
    Computes the great-circle distance between two points on the Earth's surface
    using the Haversine formula. Returns distance in kilometers.
    """
    lat1, lon1 = coords1
    lat2, lon2 = coords2
    
    R = 6371.0  # Radius of Earth in kilometers
    
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    
    a = (math.sin(d_lat / 2) ** 2 + 
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * 
         math.sin(d_lon / 2) ** 2)
    c = 2 * math.asin(math.sqrt(a))
    
    return R * c

def match_and_book_cargo(payload: CargoPayload, shipper_id: str = None) -> Optional[Booking]:
    """
    Core matching logic. 
    1. Geocodes the cargo origin.
    2. Queries the Redis Geospatial tracking service to locate all vehicle IDs within a 100km radius.
    3. Opens a transaction using SQLite BEGIN IMMEDIATE for pessimistic locking.
    4. Filters the nearby vehicle IDs against the relational DB database table to check for 'AVAILABLE' status and payload capacity.
    5. Selects the closest vehicle, transitions it to ON_TRIP, and writes a Booking record.
    
    Returns the Booking record on success, or None if no compatible vehicle was found.
    """
    origin_coords = geocode_location(payload.routing.origin)
    lat, lon = origin_coords
    
    # Import geo_service locally to avoid circular module loads
    from src.geolocation import geo_service
    
    # Query geospatial service for vehicle IDs within a 100km radius of the cargo origin
    # Redis expects (longitude, latitude) -> (lon, lat)
    nearby_ids = geo_service.search_vehicles_in_radius(lng=lon, lat=lat, radius_km=100.0)
    
    cargo_weight = payload.metadata.weight_kg
    cargo_type = payload.metadata.item_type
    special_handling = payload.metadata.special_handling
    
    # Open the pessimistic database transaction
    with locked_db_session() as session:
        # If no nearby vehicle IDs are indexed, we abort immediately
        if not nearby_ids:
            print(f"[Matcher] Geospatial index returned 0 trucks within 100km of origin ({payload.routing.origin}).")
            return None
            
        # Query only nearby, AVAILABLE vehicles in a single SQL operation
        vehicles = session.query(FleetVehicle).filter(
            FleetVehicle.vehicle_id.in_(nearby_ids),
            FleetVehicle.current_status == VehicleStatus.AVAILABLE
        ).all()
        
        compatible_vehicles: List[Tuple[FleetVehicle, float]] = []
        
        for v in vehicles:
            # Constraint 1: Physical maximum weight capacity
            if v.max_weight_capacity_kg < cargo_weight:
                continue
                
            # Constraint 2: Special Handling compatibility (e.g. temperature controlled needs Reefers)
            if special_handling and "temp" in special_handling.lower():
                if v.truck_type.lower() != "reefer":
                    continue
            
            # Parse vehicle location to calculate exact proximity distance
            try:
                vehicle_coords = geocode_location(v.location)
                distance = haversine_distance(origin_coords, vehicle_coords)
                compatible_vehicles.append((v, distance))
            except Exception as e:
                print(f"[Matcher Warning] Error parsing location for vehicle {v.vehicle_id}: {e}")
                
        if not compatible_vehicles:
            print(f"[Matcher] No compatible nearby AVAILABLE vehicle found for '{cargo_type}' ({cargo_weight} kg).")
            return None
            
        # Sort compatible vehicles by distance (proximity logic) ascending
        compatible_vehicles.sort(key=lambda x: x[1])
        selected_vehicle, distance = compatible_vehicles[0]
        
        # Double-check availability state inside transaction block
        db_vehicle = session.query(FleetVehicle).filter(
            FleetVehicle.vehicle_id == selected_vehicle.vehicle_id,
            FleetVehicle.current_status == VehicleStatus.AVAILABLE
        ).first()
        
        if not db_vehicle:
            print(f"[Matcher Lock Conflict] Vehicle {selected_vehicle.vehicle_id} is no longer available.")
            return None
            
        # Transition truck state to ON_TRIP
        db_vehicle.current_status = VehicleStatus.ON_TRIP
        
        # Generate booking ID and record
        booking_id = f"BK-{uuid.uuid4().hex[:8].upper()}"
        new_booking = Booking(
            booking_id=booking_id,
            vehicle_id=db_vehicle.vehicle_id,
            item_type=payload.metadata.item_type,
            weight_kg=payload.metadata.weight_kg,
            origin=payload.routing.origin,
            destination=payload.routing.destination,
            price_booked=payload.financials.max_budget,
            currency=payload.financials.currency,
            status="PENDING_DISPATCH",
            shipper_id=shipper_id,
            booked_at=datetime.datetime.utcnow()
        )
        
        session.add(new_booking)
        print(f"[Matcher Success] Booked closest geospatial vehicle {db_vehicle.vehicle_id} "
              f"({distance:.2f} km away, capacity {db_vehicle.max_weight_capacity_kg} kg) "
              f"for cargo '{cargo_type}' ({cargo_weight} kg). Booking ID: {booking_id}")
        
        return Booking(
            booking_id=new_booking.booking_id,
            vehicle_id=new_booking.vehicle_id,
            item_type=new_booking.item_type,
            weight_kg=new_booking.weight_kg,
            origin=new_booking.origin,
            destination=new_booking.destination,
            price_booked=new_booking.price_booked,
            currency=new_booking.currency,
            status=new_booking.status,
            shipper_id=new_booking.shipper_id,
            booked_at=new_booking.booked_at
        )
