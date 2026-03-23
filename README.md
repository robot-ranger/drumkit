# drumkit

## Setup (Linux / Raspberry Pi)

Install OS packages required to build the MIDI backend:

```bash
sudo apt-get update
sudo apt-get install -y libasound2-dev python3-dev
```

Install Python dependencies in your virtual environment:

```bash
python -m pip install -r requirements.txt
```

Run the MIDI input test:

```bash
python tests/test_midi.py
```