# models.py
from sqlalchemy import Column, Integer, String, Float, Text, ForeignKey, DateTime
from sqlalchemy.orm import declarative_base, relationship
from geoalchemy2 import Geography
from database import Base

class Driver(Base):
    __tablename__ = "driver"
    driver_id = Column(Integer, primary_key=True)
    name = Column(Text)
    license_number = Column(Text)
    contact = Column(Text)

class Truck(Base):
    __tablename__ = "truck"
    vin = Column(Text, primary_key=True)
    driver_id = Column(Integer, ForeignKey("driver.driver_id"))
    driver = relationship("Driver")

class LocationLog(Base):
    __tablename__ = "location_log"

    log_id = Column(Integer, primary_key=True, index=True)
    vin = Column(Text, ForeignKey("truck.vin"))  # ✅ important: use `vin` here
    trip_id = Column(Integer, ForeignKey("trip.trip_id"), nullable=True)
    timestamp = Column(DateTime)
    latitude = Column(Float)
    longitude = Column(Float)
    speed = Column(Float)


class Trip(Base):
    __tablename__ = "trip"
    trip_id = Column(Integer, primary_key=True)
    vin = Column(Text, ForeignKey("truck.vin"))
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    origin = Column(Geography("POINT", 4326))
    destination = Column(Geography("POINT", 4326))
    distance_km = Column(Float)
    status = Column(Text)  # 'active', 'completed'
