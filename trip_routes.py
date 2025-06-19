from fastapi import APIRouter, Request 
from sqlalchemy.orm import Session
from sqlalchemy import func
from geoalchemy2.shape import from_shape
from geoalchemy2.shape import to_shape 
from shapely.geometry import Point
from datetime import datetime, timezone
import openrouteservice
from models import TripPlan, Trip,Truck, Driver,TruckStats
from fastapi import Depends, HTTPException
from database import get_db
from models import Trip, LocationLog
from database import SessionLocal
from location_search import geocode_place
from pydantic import BaseModel
from websocket_utils import broadcast_location_sync


router = APIRouter()
ORS = openrouteservice.Client(key="5b3ce3597851110001cf6248e1d8e314ca754bc68acfb5b1aaa27ca5")

@router.post("/trip/start")
async def start_trip(request: Request):
    data = await request.json()
    vin = data["vin"]
    plan_id = data.get("plan_id")

    db: Session = SessionLocal()
    try:
        latest_location = db.query(LocationLog)\
            .filter_by(vin=vin)\
            .order_by(LocationLog.timestamp.desc())\
            .first()

        if not latest_location:
            return {"error": "No location data found for this truck."}

        origin_point = from_shape(Point(latest_location.longitude, latest_location.latitude), srid=4326)

        trip = Trip(
            vin=vin,
            start_time=datetime.now(timezone.utc),
            origin=origin_point,
            start_lat=latest_location.latitude,
            start_lon=latest_location.longitude,
            plan_id=plan_id,
            status="active"
        )
        db.add(trip)
        db.commit()
        db.refresh(trip)

        latest_location.trip_id = trip.trip_id
        db.commit()

        # WebSocket Broadcast
        broadcast_location_sync({
            "type": "trip_started",
            "vin": vin,
            "trip_id": trip.trip_id,
            "start_time": trip.start_time.isoformat(),
            "lat": latest_location.latitude,
            "lon": latest_location.longitude
        })
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

        trip_logs = db.query(LocationLog) \
            .filter_by(trip_id=trip_id) \
            .order_by(LocationLog.timestamp.asc()) \
            .all()

        if not trip_logs:
            return {"error": "No location logs found for this trip."}

        first_log = trip_logs[0]
        last_log = trip_logs[-1]

        lat1, lon1 = first_log.latitude, first_log.longitude
        lat2, lon2 = last_log.latitude, last_log.longitude

        origin_point = from_shape(Point(lon1, lat1), srid=4326)
        destination_point = from_shape(Point(lon2, lat2), srid=4326)

        from math import radians, cos, sin, sqrt, atan2

        def haversine(lat1, lon1, lat2, lon2):
            R = 6371
            dlat = radians(lat2 - lat1)
            dlon = radians(lon2 - lon1)
            a = sin(dlat / 2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2)**2
            c = 2 * atan2(sqrt(a), sqrt(1 - a))
            return R * c

        actual_distance_km = 0
        for i in range(1, len(trip_logs)):
            p1 = trip_logs[i - 1]
            p2 = trip_logs[i]
            actual_distance_km += haversine(p1.latitude, p1.longitude, p2.latitude, p2.longitude)

        trip.start_lat = lat1
        trip.start_lon = lon1
        trip.end_lat = lat2
        trip.end_lon = lon2
        trip.origin = origin_point
        trip.destination = destination_point
        trip.end_time = datetime.now(timezone.utc)
        trip.status = "completed"
        trip.distance_km = round(actual_distance_km, 2)

        duration_minutes = None
        duration = None
        if trip.start_time and trip.end_time:
            duration = trip.end_time - trip.start_time
            duration_minutes = duration.total_seconds() / 60  # ✅ now float

        comparison = None
        actual_avg_speed = 0

        if trip.plan_id:
            plan = db.query(TripPlan).filter_by(plan_id=trip.plan_id).first()
            if plan and duration_minutes:
                actual_avg_speed = actual_distance_km / (duration_minutes / 60)
                comparison = {
                    "expected_distance_km": plan.expected_distance_km,
                    "actual_distance_km": round(actual_distance_km, 2),
                    "expected_time_minutes": plan.expected_time_minutes,
                    "actual_time_minutes": duration_minutes,
                    "expected_avg_speed": plan.expected_avg_speed,
                    "actual_avg_speed": round(actual_avg_speed, 1)
                }

        # ✅ UPDATE STATS
        if duration_minutes:
            stats = db.query(TruckStats).filter(TruckStats.vin == trip.vin).first()
            if not stats:
                stats = TruckStats(
                    vin=trip.vin,
                    total_trips=1,
                    total_distance_km=actual_distance_km,
                    total_duration_minutes=duration_minutes,
                    average_distance_per_trip_km=actual_distance_km,
                    average_speed_kmph=actual_avg_speed,
                    last_updated=datetime.utcnow()
                )
                db.add(stats)
            else:
                stats.total_trips += 1
                stats.total_distance_km += actual_distance_km
                stats.total_duration_minutes += duration_minutes
                stats.average_distance_per_trip_km = stats.total_distance_km / stats.total_trips
                stats.average_speed_kmph = (
                    stats.total_distance_km / (stats.total_duration_minutes / 60)
                    if stats.total_duration_minutes > 0 else 0
                )
                stats.last_updated = datetime.utcnow()

        db.commit()
        broadcast_location_sync({
            "type": "trip_ended",
            "vin": trip.vin,
            "trip_id": trip.trip_id,
            "start_time": trip.start_time.isoformat() if trip.start_time else None,
            "end_time": trip.end_time.isoformat(),
            "distance_km": round(actual_distance_km, 2),
            "duration_minutes": duration_minutes,
            "comparison": comparison
        })

        return {
            "message": "Trip ended successfully.",
            "trip_id": trip.trip_id,
            "start_time": trip.start_time.isoformat() if trip.start_time else None,
            "end_time": trip.end_time.isoformat(),
            "start_lat": lat1,
            "start_lon": lon1,
            "end_lat": lat2,
            "end_lon": lon2,
            "duration_minutes": duration_minutes,
            "total_distance_km": round(actual_distance_km, 2),
            "comparison": comparison
        }

    finally:
        db.close()
        
@router.post("/trip/plan")
async def plan_trip(request: Request):
    data = await request.json()
    origin_place = data["start_place"]  # new key
    dest_place = data["end_place"]

    try:
        start_lat, start_lon = geocode_place(origin_place)
        end_lat, end_lon = geocode_place(dest_place)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    coords = ((start_lon, start_lat), (end_lon, end_lat))
    res = ORS.directions(coords, profile="driving-car")
    summary = res["routes"][0]["summary"]
    dist_km = summary["distance"] / 1000
    time_min = summary["duration"] / 60
    avg_speed = dist_km / (time_min / 60) if time_min else 0

    plan = TripPlan(
        start_point=from_shape(Point(start_lon, start_lat), srid=4326),
        end_point=from_shape(Point(end_lon, end_lat), srid=4326),
        expected_distance_km=round(dist_km, 2),
        expected_time_minutes=round(time_min, 1),
        expected_avg_speed=round(avg_speed, 1)
    )
    db = SessionLocal()
    db.add(plan); db.commit(); db.refresh(plan); db.close()

    broadcast_location_sync({
        "type": "trip_plan_created",
        "plan_id": plan.plan_id,
        "expected_distance_km": plan.expected_distance_km,
        "expected_time_minutes": plan.expected_time_minutes,
        "expected_avg_speed": plan.expected_avg_speed
    })

    return {
        "plan_id": plan.plan_id,
        "expected_distance_km": plan.expected_distance_km,
        "expected_time_minutes": plan.expected_time_minutes,
        "expected_avg_speed": plan.expected_avg_speed,
        "start_center": {"lat": start_lat, "lon": start_lon},
        "end_center": {"lat": end_lat, "lon": end_lon}
    }



@router.post("/trip/start/{plan_id}")
def start_trip_from_plan(plan_id: int, vin: str, db: Session = Depends(get_db)):
    plan = db.query(TripPlan).filter_by(plan_id=plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Trip plan not found")

    if not plan.start_point:
        raise HTTPException(status_code=400, detail="Trip plan has no start point")

    start_shape = to_shape(plan.start_point)

    trip = Trip(
        vin=vin,
        plan_id=plan_id,
        start_time=datetime.now(timezone.utc),
        origin=plan.start_point,
        start_lat=start_shape.y,
        start_lon=start_shape.x,
        status="active"
    )

    db.add(trip)
    db.commit()
    db.refresh(trip)

    return {
        "trip_id": trip.trip_id,
        "message": f"Trip started using plan {plan_id} with device {vin}"
    }


class TruckCreate(BaseModel):
    vin: str
    model: str
    plate_number: str
    driver_id: int

@router.post("/truck/register")
def register_truck(truck: TruckCreate):
    db: Session = SessionLocal()

    if db.query(Truck).filter(Truck.vin == truck.vin).first():
        db.close()
        raise HTTPException(status_code=400, detail="Truck with this VIN already exists.")

    if not db.query(Driver).filter(Driver.driver_id == truck.driver_id).first():
        db.close()
        raise HTTPException(status_code=404, detail="Driver not found.")

    new_truck = Truck(
        vin=truck.vin,
        model=truck.model,
        plate_number=truck.plate_number,
        driver_id=truck.driver_id,
        created_at=datetime.utcnow()
    )

    db.add(new_truck)
    db.commit()
    db.close()
    broadcast_location_sync({
        "type": "truck_registered",
        "vin": truck.vin,
        "model": truck.model,
        "plate_number": truck.plate_number,
        "driver_id": truck.driver_id
    })

    return {"message": "Truck registered successfully", "vin": truck.vin}

class DriverCreate(BaseModel):
    name: str
    phone: str
    license_number: str
    contact: str


@router.post("/driver/register")
def register_driver(driver: DriverCreate, db: Session = Depends(get_db)):
    new_driver = Driver(
        name=driver.name,
        phone=driver.phone,
        license_number=driver.license_number,
        contact=driver.contact
    )
    db.add(new_driver)
    db.commit()
    db.refresh(new_driver)
    broadcast_location_sync({
        "type": "driver_registered",
        "driver_id": new_driver.driver_id,
        "name": new_driver.name,
        "phone": new_driver.phone
    })

    return {"driver_id": new_driver.driver_id, "message": "Driver registered successfully"}

@router.get("/truck/stats/{vin}")
def get_truck_stats(vin: str, db: Session = Depends(get_db)):
    stats = db.query(TruckStats).filter(TruckStats.vin == vin).first()
    if not stats:
        raise HTTPException(status_code=404, detail="Stats not found for this truck")
    return {
        "vin": stats.vin,
        "total_trips": stats.total_trips,
        "total_distance_km": stats.total_distance_km,
        "total_duration_minutes": stats.total_duration_minutes,
        "average_distance_per_trip_km": stats.average_distance_per_trip_km,
        "average_speed_kmph": stats.average_speed_kmph,
        "last_updated": stats.last_updated,
    }
