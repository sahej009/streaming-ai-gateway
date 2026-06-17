import grpc
import uuid
from app.grpc import chat_pb2
from app.grpc import chat_pb2_grpc

# Import the exact same LLM streaming function your REST API uses!
from app.services.llm import stream_llm_tokens 

class ChatServicer(chat_pb2_grpc.ChatServiceServicer):
    async def StreamChat(self, request, context):
        """
        This is the gRPC equivalent of your POST /chat/stream REST endpoint.
        """
        # 1. Extract the data from the incoming Protobuf request
        user_message = request.message
        session_id = request.session_id
        prompt_version = request.prompt_version or "v1"
        
        # Generate a unique request ID for tracking
        req_id = str(uuid.uuid4())

        try:
            # 2. Call your existing AI streaming logic
            async for token in stream_llm_tokens(prompt=user_message,version=prompt_version):
                # 3. Yield each chunk as a ChatChunk Protobuf message 
                yield chat_pb2.ChatChunk(
                    token=token,
                    done=False,
                    request_id=req_id
                )
            
            # 4. Yield the final "done" message
            yield chat_pb2.ChatChunk(
                token="",
                done=True,
                request_id=req_id
            )
            
        except Exception as e:
            # Handle errors cleanly in gRPC
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"An error occurred: {str(e)}")
            raise