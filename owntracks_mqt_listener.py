import json
import paho.mqtt.client as mqtt
from datetime import datetime

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
    try:
        payload = json.loads(msg.payload.decode())
        lat = payload.get("lat")
        lon = payload.get("lon")
        timestamp = payload.get("tst")
        device = payload.get("tid") or "unknown"

        if lat and lon and timestamp:
            ts = datetime.fromtimestamp(timestamp)
            print(f"Device: {device}, Lat: {lat}, Lon: {lon}, Time: {ts}")
        else:
            print("Incomplete payload:", payload)

    except json.JSONDecodeError:
        print("Failed to decode JSON")

client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message

print("Starting MQTT client...")
client.connect(MQTT_BROKER, MQTT_PORT, 60)
client.loop_forever()
