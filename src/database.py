import enum
import datetime
from contextlib import contextmanager
from typing import Generator
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Float,
    Enum as SQLEnum,
    DateTime,
    ForeignKey,
    text
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session, composite
from sqlalchemy.ext.hybrid import hybrid_property

# Create SQLAlchemy Base
Base = declarative_base()

class VehicleStatus(str, enum.Enum):
    AVAILABLE = "AVAILABLE"
    ON_TRIP = "ON_TRIP"
    OFFLINE = "OFFLINE"

class Point:
    """
    Standard Point domain representation, ready to map seamlessly
    to PostgreSQL geometric Point types or PostGIS geometry.
    """
    def __init__(self, latitude: float, longitude: float):
        self.latitude = latitude
        self.longitude = longitude

    def __composite_values__(self):
        return [self.latitude, self.longitude]

    def __repr__(self):
        return f"Point(lat={self.latitude:.4f}, lng={self.longitude:.4f})"

    def __eq__(self, other):
        return (
            isinstance(other, Point) and 
            other.latitude == self.latitude and 
            other.longitude == self.longitude
        )

class FleetVehicle(Base):
    __tablename__ = "fleet_vehicles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    vehicle_id = Column(String(50), unique=True, nullable=False, index=True)
    truck_type = Column(String(50), nullable=False)
    max_weight_capacity_kg = Column(Float, nullable=False)
    current_status = Column(SQLEnum(VehicleStatus), default=VehicleStatus.AVAILABLE, nullable=False)
    driver_phone = Column(String(50), unique=True, nullable=True, index=True)

    # Standard database float columns, prepared for standard PostgreSQL Point mapping
    latitude = Column(Float, nullable=False, default=0.0)
    longitude = Column(Float, nullable=False, default=0.0)

    # Spatial composite mapping
    geom_point = composite(Point, latitude, longitude)

    # Hybrid property for backward-compatible "latitude,longitude" string mapping
    @hybrid_property
    def location(self) -> str:
        return f"{self.latitude},{self.longitude}"

    @location.setter
    def location(self, val: str) -> None:
        if val:
            try:
                lat_str, lng_str = val.split(",")
                self.latitude = float(lat_str.strip())
                self.longitude = float(lng_str.strip())
            except (ValueError, AttributeError):
                pass


class Booking(Base):
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    booking_id = Column(String(50), unique=True, nullable=False, index=True)
    vehicle_id = Column(String(50), ForeignKey("fleet_vehicles.vehicle_id"), nullable=False)
    item_type = Column(String(100), nullable=False)
    weight_kg = Column(Float, nullable=False)
    origin = Column(String(100), nullable=False)
    destination = Column(String(100), nullable=False)
    price_booked = Column(Float, nullable=False)
    currency = Column(String(10), nullable=False, default="USD")
    status = Column(String(50), default="PENDING_DISPATCH", nullable=False)
    shipper_id = Column(String(100), nullable=True)
    booked_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    hash_key = Column(String(64), primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


# Initialize Database Engine
# Using WAL journal mode and a long busy_timeout ensures concurrent operations wait for locks
# rather than throwing 'database is locked' errors immediately.
DATABASE_URL = "sqlite:///axle_ai.db"
engine = create_engine(
    DATABASE_URL,
    connect_args={"timeout": 30},  # Wait up to 30s for database locks
    echo=False
)

# Set up WAL mode on sqlite connection creation
from sqlalchemy import event
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()

# SQLite Pessimistic locking recipe:
# This event listener intercept the implicit transaction begin block of SQLAlchemy 
# and emits "BEGIN IMMEDIATE" instead of standard "BEGIN". 
# This serializes write operations across concurrent threads instantly at connection level.
@event.listens_for(engine, "begin")
def do_begin(conn):
    conn.exec_driver_sql("BEGIN IMMEDIATE")

# Sessionmaker for standard non-locking read operations
SessionFactory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

def init_db():
    """Initializes tables and seeds the fleet database."""
    Base.metadata.create_all(engine)
    
    # Seed fleet vehicles if database is empty
    session = SessionFactory()
    try:
        if session.query(FleetVehicle).count() == 0:
            vehicles = [
                # Chicago-based trucks
                FleetVehicle(
                    vehicle_id="V-CHI-001",
                    truck_type="Dry Van",
                    max_weight_capacity_kg=20000.0,
                    current_status=VehicleStatus.AVAILABLE,
                    location="41.8781,-87.6298",  # Chicago Center
                    driver_phone="whatsapp:+15551110001"
                ),
                FleetVehicle(
                    vehicle_id="V-CHI-002",
                    truck_type="Flatbed",
                    max_weight_capacity_kg=25000.0,
                    current_status=VehicleStatus.AVAILABLE,
                    location="41.8818,-87.6231",  # Near Chicago Loop
                    driver_phone="whatsapp:+15551110002"
                ),
                # Atlanta-based reefer (temperature-controlled)
                FleetVehicle(
                    vehicle_id="V-ATL-003",
                    truck_type="Reefer",
                    max_weight_capacity_kg=18000.0,
                    current_status=VehicleStatus.AVAILABLE,
                    location="33.7490,-84.3880",  # Atlanta Center
                    driver_phone="whatsapp:+15551110003"
                ),
                # Seattle-based small truck
                FleetVehicle(
                    vehicle_id="V-SEA-004",
                    truck_type="Dry Van",
                    max_weight_capacity_kg=4000.0,
                    current_status=VehicleStatus.AVAILABLE,
                    location="47.6062,-122.3321",  # Seattle Center
                    driver_phone="whatsapp:+15551110004"
                ),
                # Los Angeles heavy transport
                FleetVehicle(
                    vehicle_id="V-LAX-005",
                    truck_type="Flatbed",
                    max_weight_capacity_kg=30000.0,
                    current_status=VehicleStatus.AVAILABLE,
                    location="34.0522,-118.2437",  # Los Angeles Center
                    driver_phone="whatsapp:+15551110005"
                ),
                # Offline vehicle
                FleetVehicle(
                    vehicle_id="V-MIA-006",
                    truck_type="Reefer",
                    max_weight_capacity_kg=15000.0,
                    current_status=VehicleStatus.AVAILABLE,
                    location="25.7617,-80.1918",  # Miami Center
                    driver_phone="whatsapp:+15551110006"
                ),
            ]
            session.add_all(vehicles)
            session.commit()
            print("[Database] Fleet database seeded with 6 vehicles.")
    except Exception as e:
        session.rollback()
        print(f"[Database Error] Seeding failed: {e}")
    finally:
        session.close()

@contextmanager
def db_session() -> Generator[Session, None, None]:
    """Provide a transactional merge session for standard operations."""
    session = SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

@contextmanager
def locked_db_session() -> Generator[Session, None, None]:
    """
    Acquires a database session that automatically begins transaction
    with "BEGIN IMMEDIATE" at SQLite engine level.
    This guarantees that no other concurrent thread or worker can read/modify
    the same state until the session commits or rolls back.
    """
    session = SessionFactory()
    try:
        # Standard SQLAlchemy transaction starts, which fires the 'begin' listener 
        # to execute 'BEGIN IMMEDIATE' automatically!
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
