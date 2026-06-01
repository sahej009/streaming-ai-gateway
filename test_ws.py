import asyncio
import websockets
import json

async def test_websocket():
    uri = "ws://localhost:8000/ws/chat"
    
    # Open the connection
    async with websockets.connect(uri) as websocket:
        print("✅ Connected to WebSocket!")
        
        payload = {
            "message": "Explain how gravity works",
            "session_id": "ws-123",
            "prompt_version": "v1"
        }
        
        print("📤 Sending message...")
        await websocket.send(json.dumps(payload))

        print("📥 Receiving stream:\n")
        while True:
            try:
                response = await websocket.recv()
                print(response, end="", flush=True)
                
                if "data: [DONE]" in response:
                    break
            except websockets.exceptions.ConnectionClosed:
                break
                
        print("\n\n🔌 Stream closed.")

# Run the async test
asyncio.run(test_websocket())