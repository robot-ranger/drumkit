#!/usr/bin/env python3
"""
MQTT Pad Events -> Raspberry Pi GPIO Relay Controller
Subscribes to pad hit topics and actuates active-low relays for the requested duration.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import os
import time
from dataclasses import dataclass
import json
import dotenv
import aiomqtt
import RPi.GPIO as GPIO
from pydantic_settings import BaseSettings


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
    OVERRIDE_MODE: bool = False  # If True, ignores MAX_ON_MS and COOLDOWN_MS for testing


@dataclass
class PadState:
    timer: asyncio.Task | None = None
    opened_at: float | None = None
    cooldown_until: float = 0.0


class GPIOController:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._pad_state: dict[int, PadState] = {
            note: PadState() for note in self.settings.PAD_GPIO_MAP
        }
        self._client: aiomqtt.Client | None = None

    def setup_gpio(self) -> None:
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)

        unique_pins = sorted(set(self.settings.PAD_GPIO_MAP.values()))
        for pin in unique_pins:
            GPIO.setup(pin, GPIO.OUT)
            GPIO.output(pin, GPIO.HIGH)

        logging.info("GPIO initialized (active-low relays): %s", self.settings.PAD_GPIO_MAP)

    def run(self) -> None:
        asyncio.run(self._run_async())

    async def _run_async(self) -> None:
        self.setup_gpio()
        loop = asyncio.get_running_loop()
        main_task = asyncio.current_task()

        def _signal_handler() -> None:
            if main_task:
                main_task.cancel()

        loop.add_signal_handler(signal.SIGINT, _signal_handler)
        loop.add_signal_handler(signal.SIGTERM, _signal_handler)

        logging.info(
            "Connecting to MQTT broker at %s:%s, base topic '%s'",
            MQTT_BROKER,
            MQTT_PORT,
            MQTT_BASE,
        )

        try:
            async with aiomqtt.Client(
                MQTT_BROKER,
                MQTT_PORT,
                identifier="gpio-controller",
            ) as client:
                self._client = client
                await client.subscribe(f"{MQTT_BASE}/pad/+")
                await client.subscribe(MQTT_POOFER_TOPIC)
                await client.publish(
                    MQTT_POOFER_TOPIC,
                    self.settings.model_dump_json(),
                    qos=0,
                    retain=True,
                )
                logging.info(
                    "Subscribed to %s/pad/+ and %s",
                    MQTT_BASE,
                    MQTT_POOFER_TOPIC,
                )
                async for message in client.messages:
                    topic = str(message.topic)
                    if topic == MQTT_POOFER_TOPIC:
                        await self._on_config(message)
                    else:
                        await self._on_message(message)
        except asyncio.CancelledError:
            logging.info("Shutdown signal received")
        finally:
            await self._shutdown()

    async def _shutdown(self) -> None:
        for state in self._pad_state.values():
            if state.timer is not None:
                state.timer.cancel()
                state.timer = None
        for pin in set(self.settings.PAD_GPIO_MAP.values()):
            try:
                GPIO.output(pin, GPIO.HIGH)
            except Exception:
                pass
        GPIO.cleanup()
        logging.info("GPIO controller stopped cleanly")

    # ─── On Config Callback ──────────────────────────────────────────────────────

    async def _on_config(self, message: aiomqtt.Message) -> None:
        try:
            payload = json.loads(message.payload.decode())
            logging.debug("Received config update from %s: %s", MQTT_POOFER_TOPIC, payload)
            incoming = Settings.model_validate({
                **self.settings.model_dump(),
                **payload,
            })
            if incoming == self.settings:
                logging.debug("Config update matches current settings, ignoring.")
                return
            self.settings = incoming
            logging.info("Config updated: %s", self.settings)
        except Exception as e:
            logging.error("Error processing config message from %s: %s", MQTT_POOFER_TOPIC, e)

    # ─── On Message Callback ─────────────────────────────────────────────────────

    async def _on_message(self, message: aiomqtt.Message) -> None:
        try:
            note = self._parse_note_from_topic(str(message.topic))
            on_ms = int(float(message.payload.decode().strip()))
            if on_ms == 0:
                await self._deactivate_pad(note)
                return
            on_ms = max(1, on_ms)
            await self._activate_pad(note, on_ms)
        except Exception as exc:
            logging.error(
                "Ignoring malformed message topic=%s payload=%r error=%s",
                message.topic,
                message.payload,
                exc,
            )

    async def _deactivate_pad(self, note: int) -> None:
        pin = self.settings.PAD_GPIO_MAP.get(note)
        if pin is None:
            logging.warning("No GPIO mapping configured for note %s", note)
            return
        state = self._pad_state[note]
        if state.timer is not None:
            state.timer.cancel()
            state.timer = None
        GPIO.output(pin, GPIO.HIGH)
        await self._client.publish(f"{MQTT_POOFER_TOPIC}/{pin}", 0, qos=0, retain=False)
        state.opened_at = None
        logging.info("Deactivated note=%s pin=%s (received 0)", note, pin)

    async def _activate_pad(self, note: int, on_ms: int) -> None:
        pin = self.settings.PAD_GPIO_MAP.get(note)
        if pin is None:
            logging.warning("No GPIO mapping configured for note %s", note)
            return

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
            await self._start_cooldown(note, pin, state)
            return

        effective_on_ms = min(on_ms, remaining_budget_ms)
        should_cooldown = effective_on_ms >= remaining_budget_ms


        if state.timer is not None:
            state.timer.cancel()

        GPIO.output(pin, GPIO.LOW)
        await self._client.publish(f"{MQTT_POOFER_TOPIC}/{pin}", effective_on_ms, qos=0, retain=False)
        state.timer = asyncio.create_task(
            self._deactivate_after(note, pin, effective_on_ms / 1000.0, should_cooldown)
        )

        logging.info(
            f"Activated poofer pin={pin} for {effective_on_ms}ms (requested={on_ms}ms)"
        )

    async def _deactivate_after(
        self, note: int, pin: int, delay_s: float, start_cooldown: bool
    ) -> None:
        try:
            await asyncio.sleep(delay_s)
        except asyncio.CancelledError:
            return  # Re-activation cancelled us; relay stays LOW under new task

        GPIO.output(pin, GPIO.HIGH)
        await self._client.publish(f"{MQTT_POOFER_TOPIC}/{pin}", 0, qos=0, retain=False)
        state = self._pad_state[note]
        state.timer = None
        state.opened_at = None
        if start_cooldown:
            state.cooldown_until = time.monotonic() + (self.settings.COOLDOWN_MS / 1000.0)
            logging.warning(
                "Max-on reached for note=%s pin=%s; entering cooldown for %sms",
                note,
                pin,
                self.settings.COOLDOWN_MS,
            )
        logging.debug("Deactivated note=%s pin=%s", note, pin)

    async def _start_cooldown(self, note: int, pin: int, state: PadState) -> None:
        if state.timer is not None:
            state.timer.cancel()
            state.timer = None
        GPIO.output(pin, GPIO.HIGH)
        await self._client.publish(f"{MQTT_POOFER_TOPIC}/{pin}", 0, qos=0, retain=False)
        state.opened_at = None
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
    controller.run()


if __name__ == "__main__":
    main()
