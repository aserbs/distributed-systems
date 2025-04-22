from fastapi import FastAPI, HTTPException, Body
from pydantic import BaseModel
import uuid
import time
import requests
import grpc
import httpx
import logging_pb2 as logging_service_pb2
import logging_pb2_grpc as logging_service_pb2_grpc
app = FastAPI()

LOGGING_SERVICE_URL = "http://localhost:8001"
MESSAGES_SERVICE_URL = "http://localhost:8002"
GRPC_LOGGING_SERVICE_ADDRESS = "localhost:50051" 

class Message(BaseModel):
    msg: str

@app.post("/message")
async def send_message(message: Message):
    message_id = str(uuid.uuid4())
    payload = {"id": message_id, "msg": message.msg}

    try:
        async with httpx.AsyncClient() as client:
            await client.post(f"{LOGGING_SERVICE_URL}/log", json=payload)
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="Logging service unavailable")

    return payload

@app.get("/message")
async def get_combined_messages():
    try:
        async with httpx.AsyncClient() as client:
            # Запит до logging-service
            log_response = await client.get(f"{LOGGING_SERVICE_URL}/log")
            log_data = log_response.json()
            log_messages = list(log_data.values()) 
            log_text = "\n".join(log_messages)

            # Запит до messages-service
            msg_response = await client.get(f"{MESSAGES_SERVICE_URL}/message")
            static_msg = msg_response.json().get("msg", "")

            return {"response": f"{log_text}\n{static_msg}"}
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail="One or more services unavailable")
    



@app.post("/grpc_message")
def grpc_post_message(message: Message):

    msg = message.msg
    message_id = str(123)
    request_proto = logging_service_pb2.LogRequest(id=message_id, msg=msg)
    
    retries = 5
    for attempt in range(retries):
        try:
            channel = grpc.insecure_channel(GRPC_LOGGING_SERVICE_ADDRESS)
            stub = logging_service_pb2_grpc.LoggingServiceStub(channel)
            response = stub.LogMessage(request_proto, timeout=5)
            print(f"gRPC POST: Відповідь від logging-service: {response.detail}")
            channel.close()
           
        except Exception as e:
            print(f"gRPC POST: Спроба {attempt+1} не вдалася: {e}")
            if attempt == retries - 1:
                raise HTTPException(
                    status_code=500,
                    detail="gRPC POST: Не вдалося надіслати повідомлення до logging-service після декількох спроб"
                )
            time.sleep(2)
            
    return {"message_id": message_id, "message": msg}

@app.get("/grpc_message")
def grpc_get_message():

    try:
        resp_messages = requests.get(f"{MESSAGES_SERVICE_URL}/message", timeout=5)
        resp_messages.raise_for_status()
        static_msg = resp_messages.text
    except Exception as e:
        static_msg = f"Помилка при отриманні даних від messages-service: {e}"
    
    retries = 5
    for attempt in range(retries):
        try:
            channel = grpc.insecure_channel(GRPC_LOGGING_SERVICE_ADDRESS)
            stub = logging_service_pb2_grpc.LoggingServiceStub(channel)
            response = stub.GetLogs(logging_service_pb2.Empty(), timeout=5)
            logs = list(response.logs)
            channel.close()
            combined = ' '.join(logs) + ' ' + static_msg
            return {"combined": combined}
        except Exception as e:
            print(f"gRPC GET: Спроба {attempt+1} не вдалася: {e}")
            if attempt == retries - 1:
                raise HTTPException(
                    status_code=500,
                    detail=f"gRPC GET: Помилка виклику logging-service через gRPC: {e}"
                )
            time.sleep(2)

