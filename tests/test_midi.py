import mido

def select_port() -> str:
    ports = mido.get_input_names()
    if not ports:
        raise RuntimeError("No MIDI input ports found.")
    if len(ports) == 1:
        return ports[0]
    for i, p in enumerate(ports):
        print(f"  [{i}] {p}")
    return ports[int(input("Select port: "))]

if __name__ == "__main__":
    port_name = select_port()
    print(f"Listening on: {port_name}\n")
    collectedNotes = []
    try:
        with mido.open_input(port_name) as port:
            for msg in port:
                if msg.note not in collectedNotes:
                    collectedNotes.append(msg.note)
                print(msg)
    except KeyboardInterrupt:
        print("\nExiting.")
        print(f"Collected notes: {collectedNotes}")