#!/usr/bin/env python3
"""
MIDI Drum Pad → MQTT Bridge
Publishes pad hits to MQTT topics for ESP32 relay nodes to consume
"""

import json
import mido
import logging
import paho.mqtt.client as mqtt

logging.basicConfig(
    format='%(asctime)s - %(levelname)s: %(message)s',
    level=logging.DEBUG
    )


# ─── Config ───────────────────────────────────────────────────────────────────

MQTT_BROKER   = "192.168.0.247"   # Run Mosquitto on the Pi itself
MQTT_PORT     = 1883
MQTT_BASE     = "drums"       # Topics will be drums/pad/<note>

PAD_CONFIG = {
    38: {"name": "Snare"},
    45: {"name": "HiHat_Closed"},
    46: {"name": "HiHat_Open"},
    48: {"name": "Crash"},
    49: {"name": "Ride"},
    51: {"name": "Tom_High"},
}

MIDI_CHANNEL  = 9
MIN_ON_MS     = 20
MAX_ON_MS     = 1000

# ─── Helpers ──────────────────────────────────────────────────────────────────

def velocity_to_ms(velocity: int) -> float:
    v = max(1, min(127, velocity))
    return MIN_ON_MS + (MAX_ON_MS - MIN_ON_MS) * ((v - 1) / 126)

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
    global MIN_ON_MS, MAX_ON_MS
    try:
        payload = json.loads(msg.payload.decode())
        MIN_ON_MS     = payload.get("min_on_ms", MIN_ON_MS)
        MAX_ON_MS     = payload.get("max_on_ms", MAX_ON_MS)
        logging.info(f"Config updated: MIN_ON_MS={MIN_ON_MS}, MAX_ON_MS={MAX_ON_MS}")
    except Exception as e:
        logging.error(f"Error processing config message: {e}")

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="midi-bridge")
    client.connect(MQTT_BROKER, MQTT_PORT)
    client.subscribe(f"{MQTT_BASE}/#")
    client.message_callback_add(f"{MQTT_BASE}/config", on_config)
    client.loop_start()
    client.publish(f"{MQTT_BASE}/config", json.dumps({"min_on_ms": MIN_ON_MS, "max_on_ms": MAX_ON_MS}), qos=0, retain=True)

    port_name = select_port()
    logging.info(f"Listening on: {port_name}  →  MQTT {MQTT_BROKER}:{MQTT_PORT}/{MQTT_BASE}/\n")

    with mido.open_input(port_name) as port:
        for msg in port:
            if msg.type != "note_on" or msg.channel != MIDI_CHANNEL or msg.velocity == 0:
                continue
            if msg.note not in PAD_CONFIG:
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