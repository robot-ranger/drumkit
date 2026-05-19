#!/usr/bin/env python3
"""
MIDI Drum Pad → MQTT Bridge
Publishes pad hits to MQTT topics for ESP32 relay nodes to consume
"""

import json
import random
import sys
import threading
import time
from time import sleep
import mido
import logging
import dotenv
import os
import paho.mqtt.client as mqtt
from pydantic_settings import BaseSettings

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
    MAX_ON_MS: float = 500.
    MIN_RETRIGGER_MS: float = 200.
    PAD_CONFIG: list[int] = [
        38,
        45,
        46,
        48,
        49,
        51
    ]
    ENABLE_RANDOM: bool = False  # whether random rhythm is active
    RANDOM_PERIOD: int = 500   # ms between random hits

settings = Settings()

# ─── Helpers ──────────────────────────────────────────────────────────────────

def velocity_to_ms(velocity: int) -> float:
    v = max(1, min(127, velocity))
    return settings.MIN_ON_MS + (settings.MAX_ON_MS - settings.MIN_ON_MS) * ((v - 1) / 126)

def select_port() -> str:
    ports = [p for p in mido.get_input_names() if "Midi Through" not in p]
    if not ports:
        raise RuntimeError("No MIDI input ports found.")
    if len(ports) == 1:
        logging.info(f"Auto-selected MIDI port: {ports[0]}")
        return ports[0]
    for i, p in enumerate(ports):
        logging.info(f"  [{i}] {p}")
    midi_port_env = os.getenv("MIDI_PORT")
    if midi_port_env is None:
        try:
            import termios
            termios.tcflush(sys.stdin, termios.TCIFLUSH)
        except Exception:
            pass
        return ports[int(input("Select port: "))]
    else:
        logging.info(f"Using MIDI_PORT from env: {midi_port_env}")
        return midi_port_env

# ─── Random Rhythm Worker ────────────────────────────────────────────────────

def rhythm_worker(get_client: callable, stop: threading.Event) -> None:
    """Background thread: fires a random pad every RANDOM_PERIOD ms when ENABLE_RANDOM is True."""
    while not stop.wait(0):
        if not settings.ENABLE_RANDOM:
            stop.wait(0.1)  # idle poll while disabled
            continue
        pads = settings.PAD_CONFIG
        if not pads:
            stop.wait(0.1)
            continue
        note   = random.choice(pads)
        on_ms  = int(random.uniform(settings.MIN_ON_MS, settings.MAX_ON_MS))
        client = get_client()
        if client is not None:
            topic = f"{MQTT_BASE}/pad/{note}"
            client.publish(topic, on_ms, qos=0)
            logging.info(f"[rhythm] {topic}:{on_ms}ms")
        stop.wait(settings.RANDOM_PERIOD / 1000.0)

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
    client.message_callback_add(f"{MQTT_BASE}", on_config)
    client.loop_start()
    sleep(1)  # Allow time for MQTT connection to establish
    client.publish(f"{MQTT_BASE}/pad", settings.model_dump_json(), qos=0, retain=True)

    _client_ref = client
    stop_rhythm  = threading.Event()
    rhythm_thread = threading.Thread(
        target=rhythm_worker,
        args=(lambda: _client_ref, stop_rhythm),
        daemon=True,
        name="rhythm",
    )
    rhythm_thread.start()
    logging.info(f"Rhythm thread started (ENABLE_RANDOM={settings.ENABLE_RANDOM}, RANDOM_PERIOD={settings.RANDOM_PERIOD}ms)")

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
                on_ms = current_on_ms[msg.note] + new_on_ms
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
            action = "↻ extend" if is_extend else "Activated Note →"
            logging.info(f"{action} {topic}:{payload}")

    stop_rhythm.set()
    rhythm_thread.join(timeout=1)
    client.loop_stop()
    client.disconnect()

if __name__ == "__main__":
    main()