#!/usr/bin/env python3
"""
MIDI Drum Pad → MQTT Bridge
Publishes pad hits to MQTT topics for ESP32 relay nodes to consume
"""

import json
import time
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

# ─── env ───────────────────────────────────────────────────────────────────

dotenv.load_dotenv()
MQTT_BROKER: str = str(os.getenv("MQTT_BROKER", "localhost"))
MQTT_PORT: int = int(os.getenv("MQTT_PORT", 1883))
MQTT_BASE: str = str(os.getenv("MQTT_BASE", "drums"))

# ─── DrumKit Config ───────────────────────────────────────────────────────────────────

class Settings(BaseSettings):
    MIDI_CHANNEL: int = 9
    MIN_ON_MS: float = 100.
    MAX_ON_MS: float = 1000.
    MAX_HIT_MS: float = 2000.  # Absolute max duration for a hit, even with re-hits
    MIN_RETRIGGER_MS: float = 200.
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
        logging.debug(f"Received config update from {MQTT_BASE}/config: {payload}")
        incoming = Settings.model_construct(**{
            **settings.model_dump(),
            **payload
        })
        if incoming == settings:
            logging.debug("Config update matches current settings, ignoring.")
            return
        settings = incoming
        logging.info(f"Config updated : {settings}")
    except Exception as e:
        logging.error(f"Error processing config message from {MQTT_BASE}/config: {e}")

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    port_name = select_port()
    logging.info(f"Connecting to MQTT broker at {MQTT_BROKER}:{MQTT_PORT} with base topic '{MQTT_BASE}/'")
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="midi-bridge")
    client.connect(MQTT_BROKER, MQTT_PORT)
    client.subscribe(f"{MQTT_BASE}/#")
    client.subscribe(f"{MQTT_BASE}/")
    client.message_callback_add(f"{MQTT_BASE}", on_config)
    client.loop_start()
    sleep(1)  # Allow time for MQTT connection to establish
    client.publish(f"{MQTT_BASE}", settings.model_dump_json(), qos=0, retain=True)

    logging.info(f"Listening on: {port_name}  →  MQTT {MQTT_BROKER}:{MQTT_PORT}/{MQTT_BASE}/\n")

    # Per-pad state for debounce
    last_hit_time = {}
    current_on_ms = {}

    with mido.open_input(port_name) as port:
        for msg in port:
            if msg.type != "note_on" or msg.channel != settings.MIDI_CHANNEL or msg.velocity == 0:
                continue
            if msg.note not in settings.PAD_CONFIG:
                continue
            
            # Debounce logic: check if this pad is still in lockout window
            now = time.monotonic()
            new_on_ms = velocity_to_ms(msg.velocity)
            elapsed = now - last_hit_time.get(msg.note, -float('inf'))
            
            if elapsed < settings.MIN_RETRIGGER_MS / 1000:
                # Within lockout window: extend the on_ms (re-hit), capped at MAX_HIT_MS
                on_ms = min(settings.MAX_HIT_MS, current_on_ms[msg.note] + new_on_ms)
                is_extend = True
            else:
                # Fresh hit: outside lockout window
                on_ms = new_on_ms
                is_extend = False
            
            # Update state and publish
            last_hit_time[msg.note] = now
            current_on_ms[msg.note] = on_ms
            
            topic = f"{MQTT_BASE}/pad/{msg.note}"
            payload = int(on_ms)
            client.publish(topic, payload, qos=0)  # QoS 0 for lowest latency
            
            logging.debug(msg)
            action = "↻ extend" if is_extend else "→"
            logging.info(f"{action} {topic}:{payload}")

    client.loop_stop()
    client.disconnect()

if __name__ == "__main__":
    main()