from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from datetime import datetime
import asyncio, json
import paho.mqtt.client as mqtt
from fastapi.middleware.cors import CORSMiddleware
import openrouteservice
from models import Trip, LocationLog
from trip_routes import router as trip_router
from models import Truck, Driver, LocationLog
from database import SessionLocal
from websocket_utils import active_websockets, broadcast_location_sync 
ORS = openrouteservice.Client(key="5b3ce3597851110001cf6248e1d8e314ca754bc68acfb5b1aaa27ca5")

app = FastAPI()

app.include_router(trip_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.websocket("/ws/location")
async def location_ws(websocket: WebSocket):
    await websocket.accept()
    active_websockets.add(websocket)
    print(f"✅ WebSocket connected. Count: {len(active_websockets)}")
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        active_websockets.remove(websocket)
        print(f"❌ WebSocket disconnected. Remaining: {len(active_websockets)}")

# MQTT Setup
MQTT_BROKER = "broker.mqttdashboard.com"
MQTT_PORT = 1883
MQTT_TOPIC = "owntracks/lincolnrao/lincolnord"

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("Connected to MQTT Broker")
        client.subscribe(MQTT_TOPIC)
        print(f"Subscribed to topic: {MQTT_TOPIC}")
    else:
        print(f"Failed to connect, return code {rc}")

def on_message(client, userdata, msg):
    print(f"\nMessage received on topic {msg.topic}")
    db = None
    try:
        payload = json.loads(msg.payload.decode())
        print("MQTT data received:", payload)

        if payload.get("_type") != "location":
            print("⚠️ Skipping non-location message:", payload)
            return

        lat = payload.get("lat")
        lon = payload.get("lon")
        timestamp = payload.get("tst")
        device = payload.get("tid", "unknown")

        if lat and lon and timestamp:
            dt = datetime.fromtimestamp(timestamp)
            print(f"Device: {device}, Lat: {lat}, Lon: {lon}, Time: {dt}")

            db = SessionLocal()

            truck = db.query(Truck).filter_by(vin=device).first()
            if not truck:
                dummy_driver = Driver(name="OwnTracks", license_number="OWN123", contact="0000000000")
                db.add(dummy_driver)
                db.commit()
                db.refresh(dummy_driver)

                truck = Truck(vin=device, driver_id=dummy_driver.driver_id)
                db.add(truck)
                db.commit()
                print(f"🚚 Registered new truck: {device}")

            active_trip = db.query(Trip).filter_by(vin=device, status="active").first()
            active_trip_id = active_trip.trip_id if active_trip else None

            log = LocationLog(
                vin=device,
                trip_id=active_trip_id,
                timestamp=dt,
                latitude=lat,
                longitude=lon,
                speed=payload.get("vel", 0.0)
            )
            db.add(log)
            db.commit()
            print(f"📍 Location logged for {device} at {dt} [Trip ID: {active_trip_id}]")

            websocket_data = {
                "device": device,
                "lat": lat,
                "lon": lon,
                "timestamp": dt.isoformat(),
                "speed": payload.get("vel", 0.0)
            }
            broadcast_location_sync(websocket_data)

        else:
            print("⚠️ Incomplete payload:", payload)

    except json.JSONDecodeError:
        print("❌ Failed to decode JSON")
    except Exception as e:
        if db:
            db.rollback()
        print("💥 MQTT Handler Error:", e)
    finally:
        if db:
            db.close()

mqtt_client = mqtt.Client()
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message

@app.on_event("startup")
async def startup_event():
    import websocket_utils  # make sure you import this at the top
    websocket_utils.main_loop = asyncio.get_running_loop()  # ✅ correctly share loop
    print("Starting MQTT client...")
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
    mqtt_client.loop_start()

@app.on_event("shutdown")
async def shutdown_event():
    mqtt_client.loop_stop()
    mqtt_client.disconnect()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
