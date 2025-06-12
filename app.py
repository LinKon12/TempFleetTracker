from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from sqlalchemy import create_engine, Column, Integer, String, Float, Text, ForeignKey, DateTime, Interval, text
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from geoalchemy2 import Geography
from datetime import datetime, timedelta
import asyncio, json
from gmqtt import Client as MQTTClient

app = FastAPI()
Base = declarative_base()

# Database connection
DATABASE_URL = "postgresql+psycopg2://postgres:root@localhost:5432/FleetTracker"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

# --- WebSocket Connections Set ---
active_websockets = set()

# --- Database Models ---

class Driver(Base):
    __tablename__ = "driver"
    driver_id = Column(Integer, primary_key=True, index=True)
    name = Column(Text)
    license_number = Column(Text)
    contact = Column(Text)

class Truck(Base):
    __tablename__ = "truck"
    vin = Column(Text, primary_key=True)
    driver_id = Column(Integer, ForeignKey("driver.driver_id"))
    driver = relationship("Driver")

class Route(Base):
    __tablename__ = "route"
    route_id = Column(Integer, primary_key=True)
    source = Column(Text)
    destination = Column(Text)
    expected_distance = Column(Float)
    expected_duration = Column(Interval)

class Trip(Base):
    __tablename__ = "trip"
    trip_id = Column(Integer, primary_key=True)
    truck_id = Column(Text, ForeignKey("truck.vin"))
    route_id = Column(Integer, ForeignKey("route.route_id"))
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    status = Column(Text)
    actual_distance = Column(Float)
    actual_duration = Column(Interval)

class LocationLog(Base):
    __tablename__ = "locationlog"
    log_id = Column(Integer, primary_key=True)
    truck_id = Column(Text, ForeignKey("truck.vin"))
    trip_id = Column(Integer, ForeignKey("trip.trip_id"), nullable=True)
    timestamp = Column(DateTime)
    latitude = Column(Float)
    longitude = Column(Float)
    speed = Column(Float)

class GeoFenceZone(Base):
    __tablename__ = "geofencezone"
    zone_id = Column(Integer, primary_key=True)
    name = Column(Text)
    center = Column(Geography(geometry_type='POINT', srid=4326))
    radius = Column(Float)

# --- API Endpoints ---

@app.get("/")
def root():
    return {"message": "FastAPI is working!"}

@app.get("/test-db")
def test_db_connection():
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        return {"status": "Connected to DB!"}
    except Exception as e:
        return {"status": "Failed to connect", "error": str(e)}
    finally:
        db.close()

@app.get("/trucks")
def get_trucks():
    db = SessionLocal()
    trucks = db.query(Truck).all()
    return [{"vin": t.vin, "driver": t.driver.name if t.driver else None} for t in trucks]

@app.get("/drivers")
def get_drivers():
    db = SessionLocal()
    return db.query(Driver).all()

@app.get("/trips")
def get_trips():
    db = SessionLocal()
    return db.query(Trip).all()

@app.get("/locations")
def get_locations():
    db = SessionLocal()
    return db.query(LocationLog).all()

@app.get("/geofences")
def get_geofences():
    db = SessionLocal()
    zones = db.query(GeoFenceZone).all()
    result = [{"name": z.name, "radius": z.radius} for z in zones]
    return result

# --- WebSocket Endpoint ---
@app.websocket("/ws/location")
async def location_ws(websocket: WebSocket):
    await websocket.accept()
    active_websockets.add(websocket)
    print(f"🧩 WebSocket connected. Total: {len(active_websockets)}")
    try:
        while True:
            await websocket.receive_text()  # Keep alive
    except WebSocketDisconnect:
        active_websockets.remove(websocket)
        print(f"❌ WebSocket disconnected. Remaining: {len(active_websockets)}")

async def broadcast_location_to_websockets(data):
    if not active_websockets:
        return
    message = json.dumps(data)
    await asyncio.gather(*(ws.send_text(message) for ws in active_websockets))

# --- MQTT Listener ---
mqtt_client = MQTTClient("fleet-backend")

@app.on_event("startup")
async def startup_event():
    async def on_message(client, topic, payload, qos, properties):
        try:
            data = json.loads(payload.decode())
            print("📥 MQTT Data:", data)

            if data.get("_type") != "location":
                return

            lat = data.get("lat")
            lon = data.get("lon")
            timestamp = data.get("tst")
            device = data.get("tid", "unknown")

            if not all([lat, lon, timestamp]):
                print("Incomplete data")
                return

            dt = datetime.fromtimestamp(timestamp)
            if datetime.utcnow() - dt > timedelta(minutes=10):
                print(f"Old data ignored: {dt}")
                return

            db = SessionLocal()
            try:
                # Check if already inserted
                exists = db.query(LocationLog).filter_by(truck_id=device, timestamp=dt).first()
                if exists:
                    print(f"Duplicate entry skipped for {device} at {dt}")
                    return

                truck = db.query(Truck).filter_by(vin=device).first()
                if not truck:
                    dummy_driver = Driver(name="OwnTracks Driver", license_number="OWN123", contact="0000000000")
                    db.add(dummy_driver)
                    db.commit()
                    db.refresh(dummy_driver)

                    truck = Truck(vin=device, driver_id=dummy_driver.driver_id)
                    db.add(truck)
                    db.commit()
                    print(f"Added new truck/driver for {device}")

                log = LocationLog(
                    truck_id=device,
                    trip_id=None,
                    timestamp=dt,
                    latitude=lat,
                    longitude=lon,
                    speed=data.get("vel", 0.0)
                )
                db.add(log)
                db.commit()
                print(f"✅ Logged location for {device} at {dt}")

                # 🛰 Broadcast to WebSocket clients
                await broadcast_location_to_websockets({
                    "device": device,
                    "lat": lat,
                    "lon": lon,
                    "timestamp": dt.isoformat(),
                    "speed": data.get("vel", 0.0)
                })

            finally:
                db.close()

        except Exception as e:
            print("MQTT Handler Error:", e)

    mqtt_client.on_message = on_message
    await mqtt_client.connect("broker.mqttdashboard.com")
    mqtt_client.subscribe("owntracks/lincolnrao/lincolnord")

# --- Main App Runner ---

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
