#!/usr/bin/env python3
"""
MIDI Drum Pad → MQTT Bridge
Publishes pad hits to MQTT topics for ESP32 relay nodes to consume
"""

import json
from time import sleep
import mido
import logging
import dotenv
import os
import paho.mqtt.client as mqtt
from pydantic_settings import BaseSettings, SettingsConfigDict

logging.basicConfig(
    format='%(asctime)s - %(levelname)s: %(message)s',
    level=logging.INFO
    )

dotenv.load_dotenv()

# ─── Config ───────────────────────────────────────────────────────────────────

MQTT_BROKER: str = str(os.getenv("MQTT_BROKER", "localhost"))
MQTT_PORT: int = int(os.getenv("MQTT_PORT", 1883))
MQTT_BASE: str = str(os.getenv("MQTT_BASE", "drums"))

class Settings(BaseSettings):
    MIDI_CHANNEL: int = 9
    MIN_ON_MS: float = 100.
    MAX_ON_MS: float = 1000.
    PAD_CONFIG: list[int] = [
        38,
        45,
        46,
        48,
        49,
        51
    ]

settings = Settings()

# ─── Helpers ──────────────────────────────────────────────────────────────────

def velocity_to_ms(velocity: int) -> float:
    v = max(1, min(127, velocity))
    return settings.MIN_ON_MS + (settings.MAX_ON_MS - settings.MIN_ON_MS) * ((v - 1) / 126)

def select_port() -> str:
    ports = mido.get_input_names()
    if not ports:
        raise RuntimeError("No MIDI input ports found.")
    if len(ports) == 1:
        return ports[0]
    for i, p in enumerate(ports):
        print(f"  [{i}] {p}")
    return ports[int(input("Select port: "))]

# ─── MQTT Config Handler ─────────────────────────────────────────────────────

def on_config(client, userdata, msg):
    global settings
    try:
        payload = json.loads(msg.payload.decode())
        logging.debug(f"Received config update: {payload}")
        incoming = Settings.model_construct(**{
            **settings.model_dump(),
            **payload
        })
        if incoming == settings:
            return
        settings = incoming
        logging.info(f"Config updated: {settings}")
    except Exception as e:
        logging.error(f"Error processing config message: {e}")

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    port_name = select_port()
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="midi-bridge")
    client.connect(MQTT_BROKER, MQTT_PORT)
    client.subscribe(f"{MQTT_BASE}/#")
    client.message_callback_add(f"{MQTT_BASE}/config", on_config)
    client.loop_start()
    sleep(1)  # Allow time for MQTT connection to establish
    client.publish(f"{MQTT_BASE}/config", settings.model_dump_json(), qos=0, retain=True)

    logging.info(f"Listening on: {port_name}  →  MQTT {MQTT_BROKER}:{MQTT_PORT}/{MQTT_BASE}/\n")

    with mido.open_input(port_name) as port:
        for msg in port:
            if msg.type != "note_on" or msg.channel != settings.MIDI_CHANNEL or msg.velocity == 0:
                continue
            if msg.note not in settings.PAD_CONFIG:
                continue
            on_ms   = velocity_to_ms(msg.velocity)
            topic   = f"{MQTT_BASE}/pad/{msg.note}"
            payload = round(on_ms, 1)

            client.publish(topic, payload, qos=0)  # QoS 0 for lowest latency
            logging.debug(msg)
            logging.info(f"→ {topic}:{payload}")

    client.loop_stop()
    client.disconnect()

if __name__ == "__main__":
    main()