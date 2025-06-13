from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import asyncio, json
from gmqtt import Client as MQTTClient
from fastapi.middleware.cors import CORSMiddleware

from models import Base, Truck, Driver, LocationLog  
from database import engine, SessionLocal             

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from trip_routes import router as trip_router
app.include_router(trip_router)

# --- WebSocket Set ---
active_websockets = set()

# --- WebSocket endpoint ---
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

async def broadcast_location(data):
    if not active_websockets:
        return
    msg = json.dumps(data)
    await asyncio.gather(*(ws.send_text(msg) for ws in active_websockets))

# --- MQTT Setup ---
mqtt_client = MQTTClient("fleet-backend")

@app.on_event("startup")
async def startup_event():
    async def on_message(client, topic, payload, qos, properties):
        db = None  # Declare here to avoid UnboundLocalError in except/finally
        try:
            data = json.loads(payload.decode())
            print("📦 MQTT data received:", data)

            if data.get("_type") != "location":
                return

            lat = data.get("lat")
            lon = data.get("lon")
            timestamp = data.get("tst")
            device = data.get("tid", "unknown")
            dt = datetime.fromtimestamp(timestamp)

            db = SessionLocal()

            # Check if truck exists
            truck = db.query(Truck).filter_by(vin=device).first()
            if not truck:
                dummy_driver = Driver(
                    name="OwnTracks",
                    license_number="OWN123",
                    contact="0000000000"
                )
                db.add(dummy_driver)
                db.commit()
                db.refresh(dummy_driver)

                truck = Truck(vin=device, driver_id=dummy_driver.driver_id)
                db.add(truck)
                db.commit()
                print(f"🆕 Registered new truck: {device}")

            # Add location log
            log = LocationLog(
                vin=device,
                trip_id=None,
                timestamp=dt,
                latitude=lat,
                longitude=lon,
                speed=data.get("vel", 0.0)
            )
            db.add(log)
            db.commit()
            print(f"✅ Location logged for {device} at {dt}")

            # Send to WebSocket clients
            await broadcast_location({
                "device": device,
                "lat": lat,
                "lon": lon,
                "timestamp": dt.isoformat(),
                "speed": data.get("vel", 0.0)
            })

        except Exception as e:
            if db:
                db.rollback()
            print("❌ MQTT Handler Error:", e)
        finally:
            if db:
                db.close()

    mqtt_client.on_message = on_message
    await mqtt_client.connect("broker.mqttdashboard.com")
    mqtt_client.subscribe("owntracks/lincolnrao/lincolnord")

# --- Run ---
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
