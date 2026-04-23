import sys
sys.stdout.reconfigure(encoding='utf-8')
import mido
import asyncio
import websockets
import json
import threading
import socket
import time

SERVER = "ws://176.159.207.97:8080"
MY_ID = "pc_b"
MIDI_IN = "FL Out 1"
MIDI_OUT = "FL In 1"
UDP_PORT = 9999

apply_until = 0.0
clock_slave_until = 0.0

current_generated_bpm = None
clock_task = None
midi_out_port = None

event_queue = asyncio.Queue()

async def run_clock_generator():
    global current_generated_bpm
    while True:
        bpm = current_generated_bpm
        if bpm is None:
            break
        midi_out_port.send(mido.Message.from_bytes([0xF8]))
        await asyncio.sleep(60.0 / (bpm * 24))

async def websocket_handler():
    global apply_until, clock_slave_until, current_generated_bpm, clock_task
    while True:
        try:
            async with websockets.connect(SERVER) as ws:
                print("Connecté au serveur ✓")

                async def sender():
                    while True:
                        msg = await event_queue.get()
                        if isinstance(msg, tuple) and msg[0] == "BPM":
                            payload = {"op": "BPM", "bpm": msg[1], "from": MY_ID}
                            print(f"\nEnvoyé BPM : {msg[1]}")
                        else:
                            payload = {"op": msg, "from": MY_ID}
                            print(f"\nEnvoyé : {msg}")
                        await ws.send(json.dumps(payload))

                async def receiver():
                    global apply_until, clock_slave_until, current_generated_bpm, clock_task
                    async for raw in ws:
                        event = json.loads(raw)
                        if event.get("from") == MY_ID:
                            continue
                        op = event.get("op")
                        if op == "BPM":
                            bpm = event["bpm"]
                            print(f"\nReçu BPM : {bpm} — génération clock MIDI")
                            clock_slave_until = time.time() + 3.0
                            current_generated_bpm = bpm
                            if clock_task is None or clock_task.done():
                                clock_task = asyncio.create_task(run_clock_generator())
                        elif op in ("PLAY", "STOP"):
                            print(f"\nReçu : {op} — blocage MIDI 1s")
                            apply_until = time.time() + 1.0
                            if op == "PLAY":
                                midi_out_port.send(mido.Message.from_bytes([0xFA]))
                            else:
                                midi_out_port.send(mido.Message.from_bytes([0xFC]))

                await asyncio.gather(sender(), receiver())
        except Exception as e:
            print(f"Déconnecté ({e}) — reconnexion dans 3s...")
            await asyncio.sleep(3)

def udp_bpm_listener(loop):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('127.0.0.1', UDP_PORT))
    print(f"Écoute BPM sur UDP :{UDP_PORT}...")
    while True:
        try:
            data, _ = sock.recvfrom(64)
            if time.time() < clock_slave_until:
                continue
            bpm = round(float(data.decode()), 1)
            print(f"\rBPM : {bpm}    ", end="", flush=True)
            asyncio.run_coroutine_threadsafe(event_queue.put(("BPM", bpm)), loop)
        except Exception:
            pass

def midi_listener(loop):
    last = None
    with mido.open_input(MIDI_IN) as port:
        print(f"Écoute MIDI {MIDI_IN}...")
        for msg in port:
            if time.time() < apply_until:
                print(f"[bloqué] {msg.type} ignoré (anti-boucle)")
                continue
            if msg.type == "start" and last != "start":
                print("PLAY détecté !")
                asyncio.run_coroutine_threadsafe(event_queue.put("PLAY"), loop)
                last = "start"
            elif msg.type == "stop" and last != "stop":
                print("STOP détecté !")
                asyncio.run_coroutine_threadsafe(event_queue.put("STOP"), loop)
                last = "stop"

async def main():
    global midi_out_port
    midi_out_port = mido.open_output(MIDI_OUT)
    loop = asyncio.get_event_loop()
    threading.Thread(target=udp_bpm_listener, args=(loop,), daemon=True).start()
    threading.Thread(target=midi_listener, args=(loop,), daemon=True).start()
    try:
        await websocket_handler()
    finally:
        midi_out_port.close()

asyncio.run(main())
