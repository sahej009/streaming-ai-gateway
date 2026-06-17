import grpc
import asyncio

# We can import the generated files from your app folder locally!
from app.grpc import chat_pb2
from app.grpc import chat_pb2_grpc

async def run_client():
    print ("🔌 Connecting to gRPC Server at localhost:50051...")
    
    # 1. Open an asynchronous, unencrypted channel to the server
    async with grpc.aio.insecure_channel('localhost:50051') as channel:
        
        # 2. Create the "Stub" (This is your client interface)
        stub = chat_pb2_grpc.ChatServiceStub(channel)
        
        # 3. Create the exact Protobuf message payload defined in your schema
        request = chat_pb2.ChatRequest(
            message="Explain Quantum Computing in exactly one short sentence.",
            session_id="grpc-test-session",
            prompt_version="v2"
        )
        
        print("🚀 Sending request. Waiting for stream...\n")
        
        # 4. Call the StreamChat endpoint and iterate over the chunks as they arrive!
        try:
            async for chunk in stub.StreamChat(request):
                if chunk.done:
                    print("\n\n✅ [STREAM COMPLETE]")
                    break
                
                # Print the tokens directly to the terminal without newlines
                print(chunk.token, end="", flush=True)
                
        except grpc.RpcError as e:
            print(f"❌ gRPC Error: {e.code()} - {e.details()}")

if __name__ == "__main__":
    asyncio.run(run_client())
import asyncio

# We can import the generated files from your app folder locally!
from app.grpc import chat_pb2
from app.grpc import chat_pb2_grpc

async def run_client():
    print("🔌 Connecting to gRPC Server at localhost:50051...")
    
    # 1. Open an asynchronous, unencrypted channel to the server
    async with grpc.aio.insecure_channel('localhost:50051') as channel:
        
        # 2. Create the "Stub" (This is your client interface)
        stub = chat_pb2_grpc.ChatServiceStub(channel)
        
        # 3. Create the exact Protobuf message payload defined in your schema
        request = chat_pb2.ChatRequest(
            message="Explain Quantum Computing in exactly one short sentence.",
            session_id="grpc-test-session",
            prompt_version="v2"
        )
        
        print("🚀 Sending request. Waiting for stream...\n")
        
        # 4. Call the StreamChat endpoint and iterate over the chunks as they arrive!
        try:
            async for chunk in stub.StreamChat(request):
                if chunk.done:
                    print("\n\n✅ [STREAM COMPLETE]")
                    break
                
                # Print the tokens directly to the terminal without newlines
                print(chunk.token, end="", flush=True)
                
        except grpc.RpcError as e:
            print(f"❌ gRPC Error: {e.code()} - {e.details()}")

if __name__ == "__main__":
    asyncio.run(run_client())