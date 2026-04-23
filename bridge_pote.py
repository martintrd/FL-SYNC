import sys
sys.stdout.reconfigure(encoding='utf-8')
import mido
import asyncio
import websockets
import json
import threading
import time

SERVER = "ws://176.159.207.97:8080"
MY_ID = "pc_b"
MIDI_IN = "FL Out 1"   # port où FL Studio envoie le clock
MIDI_OUT = "FL In 1"   # port où FL Studio reçoit les commandes

apply_until = 0.0

event_queue = asyncio.Queue()

async def websocket_handler():
    global apply_until
    async with websockets.connect(SERVER) as ws:
        print("Connecté au serveur ✓")

        async def sender():
            while True:
                op = await event_queue.get()
                await ws.send(json.dumps({"op": op, "from": MY_ID}))
                print(f"Envoyé : {op}")

        async def receiver():
            global apply_until
            async for raw in ws:
                event = json.loads(raw)
                if event.get("from") == MY_ID:
                    continue
                op = event.get("op")
                print(f"Reçu : {op} — blocage MIDI 1s")
                apply_until = time.time() + 1.0
                with mido.open_output(MIDI_OUT) as port:
                    if op == "PLAY":
                        port.send(mido.Message.from_bytes([0xFA]))
                    elif op == "STOP":
                        port.send(mido.Message.from_bytes([0xFC]))

        await asyncio.gather(sender(), receiver())

def midi_listener(loop):
    last = None
    with mido.open_input(MIDI_IN) as port:
        print(f"Écoute {MIDI_IN}...")
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
    loop = asyncio.get_event_loop()
    thread = threading.Thread(target=midi_listener, args=(loop,), daemon=True)
    thread.start()
    await websocket_handler()

asyncio.run(main())
