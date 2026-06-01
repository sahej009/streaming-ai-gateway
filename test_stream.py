import httpx

url = "http://localhost:8000/chat/stream"
payload = {
    "message": "Explain quantum computing in one sentence.",
    "session_id": "123",
    "prompt_version": "v1"
}

print("Connecting to stream...\n")

# Connect to the FastAPI endpoint and stream the response
with httpx.stream("POST", url, json=payload, timeout=30.0) as response:
    for chunk in response.iter_text():
        # Print each chunk to the terminal exactly as it arrives
        print(chunk, end="", flush=True)
        
print("\n\nStream closed.")