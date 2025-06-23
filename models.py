# models.py
from sqlalchemy import Column, Integer, String, Float, Text, ForeignKey, DateTime,text
from sqlalchemy.orm import relationship
from geoalchemy2 import Geography
from database import Base
from datetime import datetime
from pydantic import BaseModel


class Truck(Base):
    __tablename__ = "truck"

    vin = Column(String, unique=True, nullable=False, primary_key=True)
    model = Column(String)
    plate_number = Column(String)
    driver_id = Column(Integer, ForeignKey("driver.driver_id"))
    created_at = Column(DateTime, server_default=text("now()"))

class Driver(Base):
    __tablename__ = "driver"

    driver_id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    phone = Column(String)
    license_number = Column(String)
    contact = Column(String)

class DriverCreate(BaseModel):
    name: str
    phone: str
    license_number: str
    contact: str

class LocationLog(Base):
    __tablename__ = "location_log"

    log_id = Column(Integer, primary_key=True, index=True)
    vin = Column(Text, ForeignKey("truck.vin"))
    trip_id = Column(Integer, ForeignKey("trip.trip_id"), nullable=True)
    timestamp = Column(DateTime)
    latitude = Column(Float)
    longitude = Column(Float)
    speed = Column(Float)


class Trip(Base):
    __tablename__ = "trip"

    trip_id = Column(Integer, primary_key=True, index=True)
    vin = Column(String, ForeignKey("truck.vin"))  
    plan_id = Column(Integer, ForeignKey("trip_plan.plan_id"), nullable=True)  
    start_time = Column(DateTime(timezone=True))
    end_time = Column(DateTime(timezone=True))
    origin = Column(Geography(geometry_type='POINT', srid=4326))
    destination = Column(Geography(geometry_type='POINT', srid=4326))
    distance_km = Column(Float)
    status = Column(String)
    start_lat = Column(Float)
    start_lon = Column(Float)
    end_lat = Column(Float)
    end_lon = Column(Float)
    comparison = relationship("TripComparison", back_populates="trip", uselist=False)
    
    
class TripPlan(Base):
    __tablename__ = "trip_plan"

    plan_id = Column(Integer, primary_key=True, index=True)
    start_point = Column(Geography(geometry_type="POINT", srid=4326))
    end_point = Column(Geography(geometry_type="POINT", srid=4326))
    expected_distance_km = Column(Float)
    expected_time_minutes = Column(Float)
    expected_avg_speed = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)  

class TruckStats(Base):
    __tablename__ = "truck_stats"

    vin = Column(Text, ForeignKey("truck.vin"), primary_key=True)
    total_trips = Column(Integer, default=0)
    total_distance_km = Column(Float, default=0)
    total_duration_minutes = Column(Float, default=0)
    average_distance_per_trip_km = Column(Float, default=0)
    average_speed_kmph = Column(Float, default=0)
    last_updated = Column(DateTime, server_default=text('now()'))

class TripComparison(Base):
    __tablename__ = "trip_comparison"

    trip_id = Column(Integer, ForeignKey("trip.trip_id", ondelete="CASCADE"), primary_key=True)
    expected_distance_km = Column(Float)    
    actual_distance_km = Column(Float)
    expected_time_minutes = Column(Float)
    actual_time_minutes = Column(Float)
    expected_avg_speed = Column(Float)
    actual_avg_speed = Column(Float)
    efficiency_percent = Column(Float)

    trip = relationship("Trip", back_populates="comparison")
