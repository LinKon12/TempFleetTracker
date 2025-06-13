from fastapi import APIRouter, Request
from sqlalchemy.orm import Session
from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from datetime import datetime

from models import Trip, LocationLog
from database import SessionLocal

router = APIRouter()

@router.post("/trip/start")
async def start_trip(request: Request):
    data = await request.json()
    vin = data["vin"]

    db: Session = SessionLocal()
    try:
        latest_location = db.query(LocationLog).filter_by(vin=vin).order_by(LocationLog.timestamp.desc()).first()
        if not latest_location:
            return {"error": "No location data found for this truck."}

        origin_point = from_shape(Point(latest_location.longitude, latest_location.latitude), srid=4326)

        trip = Trip(
            vin=vin,
            start_time=datetime.utcnow(),
            origin=origin_point,
            status="active"
        )
        db.add(trip)
        db.commit()
        db.refresh(trip)
        return {"trip_id": trip.trip_id}
    finally:
        db.close()

@router.post("/trip/end")
async def end_trip(request: Request):
    data = await request.json()
    trip_id = data["trip_id"]

    db: Session = SessionLocal()
    try:
        trip = db.query(Trip).filter_by(trip_id=trip_id, status="active").first()
        if not trip:
            return {"error": "Trip not found or already ended."}

        latest_location = db.query(LocationLog).filter_by(vin=trip.vin).order_by(LocationLog.timestamp.desc()).first()
        destination_point = from_shape(Point(latest_location.longitude, latest_location.latitude), srid=4326)

        trip.end_time = datetime.utcnow()
        trip.destination = destination_point
        trip.status = "completed"
        db.commit()

        return {"message": "Trip ended successfully."}
    finally:
        db.close()
