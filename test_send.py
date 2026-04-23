import asyncio
import websockets
import json

SERVER = "ws://176.159.207.97:8080"

async def test():
    async with websockets.connect(SERVER) as ws:
        print("Connecté au serveur")
        await ws.send(json.dumps({"op": "PLAY", "from": "pc_b"}))
        print("PLAY envoyé — regarde les logs sur PC A")
        await asyncio.sleep(3)
        await ws.send(json.dumps({"op": "STOP", "from": "pc_b"}))
        print("STOP envoyé")
        await asyncio.sleep(2)

asyncio.run(test())
