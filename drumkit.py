#!/usr/bin/env python3
"""
MIDI Drum Pad → MQTT Bridge
Publishes pad hits to MQTT topics for ESP32 relay nodes to consume
"""

import json
from time import sleep
import mido
import logging
import paho.mqtt.client as mqtt
from pydantic_settings import BaseSettings, SettingsConfigDict

logging.basicConfig(
    format='%(asctime)s - %(levelname)s: %(message)s',
    level=logging.INFO
    )


# ─── Config ───────────────────────────────────────────────────────────────────

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Use top level .env file (one level above ./backend/)
        env_file="../.env",
        env_ignore_empty=True,
        extra="ignore",
    )
    MQTT_BROKER: str = "192.168.0.247"
    MQTT_PORT: int = 1883
    MQTT_BASE: str = "drums"
    MIDI_CHANNEL: int = 9
    MIN_ON_MS: float = 20
    MAX_ON_MS: float = 1000
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
    try:
        payload = json.loads(msg.payload.decode())
        logging.debug(f"Received config update: {payload}")
        incoming = Settings.model_construct(**{
            **settings.model_dump(),
            "MIN_ON_MS": payload.get("min_on_ms", settings.MIN_ON_MS),
            "MAX_ON_MS": payload.get("max_on_ms", settings.MAX_ON_MS),
        })
        if incoming == settings:
            return
        settings.MIN_ON_MS = incoming.MIN_ON_MS
        settings.MAX_ON_MS = incoming.MAX_ON_MS
        logging.info(f"Config updated: MIN_ON_MS={settings.MIN_ON_MS}, MAX_ON_MS={settings.MAX_ON_MS}")
    except Exception as e:
        logging.error(f"Error processing config message: {e}")

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    port_name = select_port()
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="midi-bridge")
    client.connect(settings.MQTT_BROKER, settings.MQTT_PORT)
    client.subscribe(f"{settings.MQTT_BASE}/#")
    client.message_callback_add(f"{settings.MQTT_BASE}/config", on_config)
    client.loop_start()
    sleep(1)  # Allow time for MQTT connection to establish
    client.publish(f"{settings.MQTT_BASE}/config", json.dumps({"min_on_ms": settings.MIN_ON_MS, "max_on_ms": settings.MAX_ON_MS}), qos=0, retain=True)

    logging.info(f"Listening on: {port_name}  →  MQTT {settings.MQTT_BROKER}:{settings.MQTT_PORT}/{settings.MQTT_BASE}/\n")

    with mido.open_input(port_name) as port:
        for msg in port:
            if msg.type != "note_on" or msg.channel != settings.MIDI_CHANNEL or msg.velocity == 0:
                continue
            if msg.note not in settings.PAD_CONFIG:
                continue
            on_ms   = velocity_to_ms(msg.velocity)
            topic   = f"{settings.MQTT_BASE}/pad/{msg.note}"
            payload = round(on_ms, 1)

            client.publish(topic, payload, qos=0)  # QoS 0 for lowest latency
            logging.debug(msg)
            logging.info(f"→ {topic}:{payload}")

    client.loop_stop()
    client.disconnect()

if __name__ == "__main__":
    main()