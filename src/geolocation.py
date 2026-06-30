import os
import threading
from typing import List, Dict, Tuple
from src.matcher import haversine_distance

# Try importing redis for production-grade geospatial capabilities
try:
    import redis
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False
    print("[Geo System Warning] Redis package not installed. Running in stand-alone in-memory spatial mode.")

# Local thread-safe in-memory cache to simulate Redis GEO indexing
_local_geo_cache: Dict[str, Tuple[float, float]] = {}
_geo_lock = threading.Lock()

class RedisGeoService:
    """
    Geospatial Tracking Service.
    Integrates with Redis using GEOADD and GEOSEARCH radius queries.
    Provides a thread-safe, high-fidelity in-memory Haversine fallback engine
    if Redis is unavailable or unconfigured in the current environment.
    """
    def __init__(self):
        self.redis_client = None
        if HAS_REDIS:
            try:
                redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
                self.redis_client = redis.Redis.from_url(
                    redis_url, 
                    socket_connect_timeout=2,
                    decode_responses=True
                )
                self.redis_client.ping()
                print("[Geo System] Connected successfully to live Redis broker.")
            except Exception:
                self.redis_client = None
                print("[Geo System] Redis connection failed. Falling back to stand-alone in-memory spatial mode.")

    def update_vehicle_coordinates(self, vehicle_id: str, lng: float, lat: float) -> None:
        """
        Records the real-time coordinates (longitude, latitude) of a fleet vehicle.
        Stores in Redis GEO index if available, else falls back to local memory.
        """
        # Save to Redis
        if self.redis_client:
            try:
                # Redis GEOADD expects (longitude, latitude, member)
                self.redis_client.geoadd("axle:fleet:geo", (lng, lat, vehicle_id))
                # Print debug log to trace coordinates updates
                print(f"[Geo] Redis GEOADD vehicle {vehicle_id} to position ({lng:.4f}, {lat:.4f})")
                return
            except Exception as e:
                print(f"[Geo Warning] Redis GEOADD failed: {e}. Writing to in-memory fallback.")

        # In-memory fallback
        with _geo_lock:
            _local_geo_cache[vehicle_id] = (lng, lat)
            print(f"[Geo Fallback] Recorded vehicle {vehicle_id} to position ({lng:.4f}, {lat:.4f}) in-memory.")

    def search_vehicles_in_radius(self, lng: float, lat: float, radius_km: float = 100.0) -> List[str]:
        """
        Queries the geospatial index to locate all vehicle IDs situated
        within a given radius (in kilometers) of origin coordinates.
        """
        # Search via Redis
        if self.redis_client:
            try:
                # Try modern GEOSEARCH (available in Redis 6.2+)
                results = self.redis_client.geosearch(
                    "axle:fleet:geo",
                    longitude=lng,
                    latitude=lat,
                    radius=radius_km,
                    unit="km"
                )
                print(f"[Geo] Redis GEOSEARCH located {len(results)} vehicles within {radius_km}km radius.")
                return results
            except AttributeError:
                # Fallback to legacy GEORADIUS if redis-py / server is older
                try:
                    results = self.redis_client.georadius(
                        "axle:fleet:geo",
                        longitude=lng,
                        latitude=lat,
                        radius=radius_km,
                        unit="km"
                    )
                    print(f"[Geo Legacy] Redis GEORADIUS located {len(results)} vehicles within {radius_km}km.")
                    return results
                except Exception as e:
                    print(f"[Geo Warning] Redis GEORADIUS failed: {e}. Falling back to in-memory search.")
            except Exception as e:
                print(f"[Geo Warning] Redis GEOSEARCH failed: {e}. Falling back to in-memory search.")

        # In-memory Haversine radius search fallback
        nearby_vehicles = []
        target_coords = (lat, lng)  # haversine expects (latitude, longitude)
        
        with _geo_lock:
            for vehicle_id, (v_lng, v_lat) in _local_geo_cache.items():
                vehicle_coords = (v_lat, v_lng)
                distance = haversine_distance(target_coords, vehicle_coords)
                if distance <= radius_km:
                    nearby_vehicles.append(vehicle_id)
                    
        print(f"[Geo Fallback] Haversine search located {len(nearby_vehicles)} vehicles within {radius_km}km radius.")
        return nearby_vehicles

    def get_vehicle_coordinates(self, vehicle_id: str) -> Tuple[float, float]:
        """
        Retrieves the current coordinates (latitude, longitude) of a vehicle.
        Queries the Redis GEO index if available, falling back to local thread-safe memory,
        and finally queries the persistent relational database as a final fallback.
        """
        if self.redis_client:
            try:
                # Redis GEOPOS returns a list of coordinates [[longitude, latitude]]
                pos = self.redis_client.geopos("axle:fleet:geo", vehicle_id)
                if pos and pos[0]:
                    lng, lat = pos[0]
                    return float(lat), float(lng)
            except Exception as e:
                print(f"[Geo Warning] Redis GEOPOS failed: {e}. Checking in-memory.")

        with _geo_lock:
            if vehicle_id in _local_geo_cache:
                lng, lat = _local_geo_cache[vehicle_id]
                return lat, lng

        # Final database fallback
        from src.database import db_session, FleetVehicle
        try:
            with db_session() as session:
                vehicle = session.query(FleetVehicle).filter(FleetVehicle.vehicle_id == vehicle_id).first()
                if vehicle:
                    return vehicle.latitude, vehicle.longitude
        except Exception as e:
            print(f"[Geo Error] Persistent database coordinates query failed: {e}")
            
        return 0.0, 0.0

# Export singleton instance
geo_service = RedisGeoService()

# Thread-safe telemetry helper
_telemetry_lock = threading.Lock()

def update_vehicle_telemetry(vehicle_id: str, lat: float, lng: float) -> None:
    """
    Concurrently updates the real-time coordinates of a vehicle in both
    the active geospatial index (Redis/in-memory) and the relational database,
    executed within a thread-safe transaction lock.
    """
    with _telemetry_lock:
        # 1. Update active geospatial tracker (Redis or local in-memory fallback)
        geo_service.update_vehicle_coordinates(vehicle_id, lng=lng, lat=lat)

        # 2. Persist the update in the relational database within a serializable transaction block
        from src.database import locked_db_session, FleetVehicle
        try:
            with locked_db_session() as session:
                vehicle = session.query(FleetVehicle).filter(FleetVehicle.vehicle_id == vehicle_id).first()
                if vehicle:
                    vehicle.latitude = lat
                    vehicle.longitude = lng
                    print(f"[Telemetry Persist] Persisted coordinates for {vehicle_id} to DB: lat={lat:.4f}, lng={lng:.4f}")
                else:
                    print(f"[Telemetry Warning] Vehicle {vehicle_id} not found in database during persistence.")
        except Exception as e:
            print(f"[Telemetry Persist Error] Relational telemetry write failed: {e}")
