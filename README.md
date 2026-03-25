# drumkit

drumkit is a interactive propane poofer art project. The user enjoys interacting with the poofers via the drum pad. There is a MIDI drumpad device connected to a raspberry pi5 via usb. When the user taps on the drum pad, that MIDI note's associated poofer valve is opened for a time scaled from the velocity of the impact. 

## Architecture
### `drumkit.py`
This script consumes the MIDI signal from the drumpad, scales each impact's velocity into ms, and publishes to discrete mqtt topics, one for each MIDI note. This script is merely a publisher and not dependent on any other script. 

This script publishes scaled velocity to ``/{MQTT_BASE}/pad/...` for each respective pad.

Settings are published to `/{MQTT_BASE}/pad` and can be reconfigured during runtime by publishing to `/{MQTT_BASE}/pad` since the script is subscribed to `/{MQTT_BASE}/pad` at start.

### `gpio_controller.py`
This script subscribes to the topics that `drumkit.py` publishes and is responsible for activating the mapped gpio pin for the given time. This script is merely a subscriber listening to `/{MQTT_BASE}/pad/+`

## Setup (Linux / Raspberry Pi)

Install OS packages required to build the MIDI backend:

```bash
sudo apt-get update
sudo apt-get install -y libasound2-dev python3-dev swig build-essential liblgpio-dev
```

Install Python dependencies in your virtual environment:

```bash
python -m pip install -r requirements.txt
```

For one-command setup (system deps + venv + Python deps), run `./bootstrap.sh` from the project root.

Run the MIDI input test:

```bash
python tests/test_midi.py
```

## Runtime

Start the MIDI publisher (publishes pad events to MQTT):

```bash
python drumkit.py
```

Start the GPIO relay subscriber (acts on MQTT pad events):

```bash
python gpio_controller.py
```