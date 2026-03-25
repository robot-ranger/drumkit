#!/usr/bin/env python3
"""
MQTT Pad Events -> Raspberry Pi GPIO Relay Controller
Subscribes to pad hit topics and actuates active-low relays for the requested duration.
"""

from __future__ import annotations

import logging
import signal
import threading
import os
import time
from dataclasses import dataclass
import json
import dotenv
import paho.mqtt.client as mqtt
import RPi.GPIO as GPIO
from pydantic_settings import BaseSettings, SettingsConfigDict


logging.basicConfig(
    format="%(asctime)s - %(levelname)s: %(message)s",
    level=logging.INFO,
)

# ─── env ───────────────────────────────────────────────────────────────────

dotenv.load_dotenv()
MQTT_BROKER: str = str(os.getenv("MQTT_BROKER", "localhost"))
MQTT_PORT: int = int(os.getenv("MQTT_PORT", 1883))
MQTT_BASE: str = str(os.getenv("MQTT_BASE", "drums"))
MQTT_POOFER_TOPIC: str = f"{MQTT_BASE}/poofer"

# ─── DrumKit Config ───────────────────────────────────────────────────────────────────

class Settings(BaseSettings):
    # Relay board wiring for 6 pads (active-low outputs).
    PAD_GPIO_MAP: dict[int, int] = {
        38: 5,
        45: 19,
        46: 16,
        48: 6,
        49: 20,
        51: 13,
    }
    MAX_ON_MS: int = 2000
    COOLDOWN_MS: int = 2000


@dataclass
class PadState:
    timer: threading.Timer | None = None
    generation: int = 0
    opened_at: float | None = None
    cooldown_until: float = 0.0
    cooldown_on_generation: int | None = None


class GPIOController:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._lock = threading.RLock()
        self._stopped = False
        self._pad_state: dict[int, PadState] = {
            note: PadState() for note in self.settings.PAD_GPIO_MAP
        }
        self._client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id="gpio-controller",
        )
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message

    def setup_gpio(self) -> None:
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)

        unique_pins = sorted(set(self.settings.PAD_GPIO_MAP.values()))
        for pin in unique_pins:
            GPIO.setup(pin, GPIO.OUT)
            GPIO.output(pin, GPIO.HIGH)

        logging.info("GPIO initialized (active-low relays): %s", self.settings.PAD_GPIO_MAP)

    def connect(self) -> None:
        logging.info(
            "Connecting to MQTT broker at %s:%s, base topic '%s'",
            MQTT_BROKER,
            MQTT_PORT,
            MQTT_BASE,
        )
        self._client.connect(MQTT_BROKER, MQTT_PORT)

    def run(self) -> None:
        self.setup_gpio()
        self.connect()
        self._client.loop_forever()

    def stop(self) -> None:
        with self._lock:
            if self._stopped:
                return
            self._stopped = True

            for state in self._pad_state.values():
                if state.timer is not None:
                    state.timer.cancel()
                    state.timer = None
        self._client.disconnect()
        GPIO.cleanup()
        logging.info("GPIO controller stopped cleanly")

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata,
        flags,
        reason_code,
        properties,
    ) -> None:
        client.message_callback_add(MQTT_POOFER_TOPIC, self._on_config)
        client.message_callback_add(f"{MQTT_BASE}/pad/+", self._on_message)
        topics = [
            (f"{MQTT_BASE}/pad/+", 0),
            (MQTT_POOFER_TOPIC, 0)
        ]
        client.subscribe(topics)
        logging.info("Subscribed to %s", topics)
        client.publish(MQTT_POOFER_TOPIC, self.settings.model_dump_json(), qos=0, retain=True)

    # ─── On Config Callback ──────────────────────────────────────────────────────

    def _on_config(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            logging.debug(f"Received config update from {MQTT_BASE}/poofer: {payload}")
            incoming = Settings.model_validate({
                **self.settings.model_dump(),
                **payload
            })
            if incoming == self.settings:
                logging.debug("Config update matches current settings, ignoring.")
                return
            self.settings = incoming
            logging.info(f"Config updated : {self.settings}")
        except Exception as e:
            logging.error(f"Error processing config message from {MQTT_BASE}/poofer: {e}")

    # ─── On Message Callback ─────────────────────────────────────────────────────

    def _on_message(self, client: mqtt.Client, userdata, msg: mqtt.MQTTMessage) -> None:
        try:
            note = self._parse_note_from_topic(msg.topic)
            on_ms = int(float(msg.payload.decode().strip()))
            on_ms = max(1, on_ms)
            self._activate_pad(note, on_ms)
        except Exception as exc:
            logging.error("Ignoring malformed message topic=%s payload=%r error=%s", msg.topic, msg.payload, exc)

    def _activate_pad(self, note: int, on_ms: int) -> None:
        pin = self.settings.PAD_GPIO_MAP.get(note)
        if pin is None:
            logging.warning("No GPIO mapping configured for note %s", note)
            return

        with self._lock:
            now = time.monotonic()
            state = self._pad_state[note]

            if now < state.cooldown_until:
                remaining_ms = int((state.cooldown_until - now) * 1000)
                logging.debug(
                    "Ignoring note=%s pin=%s while in cooldown (%sms remaining)",
                    note,
                    pin,
                    max(0, remaining_ms),
                )
                return

            if state.opened_at is None:
                state.opened_at = now

            elapsed_ms = int((now - state.opened_at) * 1000)
            remaining_budget_ms = self.settings.MAX_ON_MS - elapsed_ms
            if remaining_budget_ms <= 0:
                self._start_cooldown_locked(note, pin, state)
                return

            effective_on_ms = min(on_ms, remaining_budget_ms)
            state.generation += 1
            generation = state.generation

            if state.timer is not None:
                state.timer.cancel()

            GPIO.output(pin, GPIO.LOW)
            self._client.publish(f"{MQTT_POOFER_TOPIC}/{pin}", effective_on_ms, qos=0, retain=False)
            state.cooldown_on_generation = (
                generation if effective_on_ms >= remaining_budget_ms else None
            )

            timer = threading.Timer(
                effective_on_ms / 1000.0,
                self._deactivate_pad_if_current,
                args=(note, generation),
            )
            timer.daemon = True
            timer.start()
            state.timer = timer

        logging.info(
            "Activated note=%s pin=%s for %sms (requested=%sms)",
            note,
            pin,
            effective_on_ms,
            on_ms,
        )

    def _deactivate_pad_if_current(self, note: int, generation: int) -> None:
        pin = self.settings.PAD_GPIO_MAP[note]
        with self._lock:
            state = self._pad_state[note]
            if state.generation != generation:
                return

            GPIO.output(pin, GPIO.HIGH)
            self._client.publish(f"{MQTT_POOFER_TOPIC}/{pin}", 0, qos=0, retain=False)
            state.timer = None
            state.opened_at = None
            if state.cooldown_on_generation == generation:
                state.cooldown_until = time.monotonic() + (self.settings.COOLDOWN_MS / 1000.0)
                state.cooldown_on_generation = None
                logging.warning(
                    "Max-on reached for note=%s pin=%s; entering cooldown for %sms",
                    note,
                    pin,
                    self.settings.COOLDOWN_MS,
                )

        logging.debug("Deactivated note=%s pin=%s", note, pin)

    def _start_cooldown_locked(self, note: int, pin: int, state: PadState) -> None:
        if state.timer is not None:
            state.timer.cancel()
            state.timer = None
        GPIO.output(pin, GPIO.HIGH)
        self._client.publish(f"{MQTT_POOFER_TOPIC}/{pin}", 0, qos=0, retain=False)
        state.opened_at = None
        state.generation += 1
        state.cooldown_on_generation = None
        state.cooldown_until = time.monotonic() + (self.settings.COOLDOWN_MS / 1000.0)
        logging.warning(
            "Force-closing note=%s pin=%s after max-on %sms; cooldown %sms",
            note,
            pin,
            self.settings.MAX_ON_MS,
            self.settings.COOLDOWN_MS,
        )

    def _parse_note_from_topic(self, topic: str) -> int:
        parts = topic.split("/")
        if len(parts) < 3:
            raise ValueError("topic too short")
        if parts[-2] != "pad":
            raise ValueError("topic does not contain /pad/")
        return int(parts[-1])


def main() -> None:
    dotenv.load_dotenv()
    settings = Settings()
    controller = GPIOController(settings)

    stop_event = threading.Event()

    def _handle_signal(signum, frame) -> None:
        logging.info("Received signal %s", signum)
        stop_event.set()
        controller.stop()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    try:
        controller.run()
    except KeyboardInterrupt:
        controller.stop()
    except Exception:
        controller.stop()
        raise


if __name__ == "__main__":
    main()
