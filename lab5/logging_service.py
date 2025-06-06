import os
import sys
import socket
import uuid
import atexit
import json
import base64
import requests
import hazelcast

from fastapi import FastAPI
from pydantic import BaseModel
from contextlib import asynccontextmanager
import uvicorn

SERVICE_NAME = "logging-service"
SERVICE_PORT = int(os.getenv("LOGGING_PORT", 8001))
CONSUL_ADDRESS = os.getenv("CONSUL_ADDRESS", "http://localhost:8500")
SERVICE_ID = f"{SERVICE_NAME}-{uuid.uuid4()}"

hz_client = None
messages_map = None

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except:
        return "127.0.0.1"
    finally:
        s.close()

def register_in_consul():
    ip = get_local_ip()
    url = f"{CONSUL_ADDRESS}/v1/agent/service/register"
    payload = {
        "Name": SERVICE_NAME,
        "ID": SERVICE_ID,
        "Address": ip,
        "Port": SERVICE_PORT,
        "Check": {
            "HTTP": f"http://{ip}:{SERVICE_PORT}/health",
            "Interval": "10s",
            "Timeout": "3s"
        }
    }
    r = requests.put(url, json=payload, timeout=3)
    r.raise_for_status()
    print(f"[Logging] Зареєстровано в Consul з ID={SERVICE_ID} ({ip}:{SERVICE_PORT})")

def deregister_from_consul():
    url = f"{CONSUL_ADDRESS}/v1/agent/service/deregister/{SERVICE_ID}"
    try:
        r = requests.put(url, timeout=3)
        r.raise_for_status()
        print(f"[Logging] Відреєстровано з Consul: ID={SERVICE_ID}")
    except:
        pass

def load_hazelcast_config():
    url = f"{CONSUL_ADDRESS}/v1/kv/hazelcast/config"
    r = requests.get(url, timeout=3)
    r.raise_for_status()
    data = r.json()
    raw = data[0]["Value"]
    return json.loads(base64.b64decode(raw).decode("utf-8"))

app = FastAPI()

class LogMessage(BaseModel):
    id: str
    msg: str

@app.get("/health")
async def health():
    return {"status": "UP"}

@app.post("/log")
async def log_message(log_msg: LogMessage):
    existing = messages_map.get(log_msg.id)
    if existing is not None:
        return {"status": "ok", "id": log_msg.id, "note": "Ігнорування дупліката"}
    messages_map.put(log_msg.id, log_msg.msg)
    print(f"[Logging] Збережено у Hazelcast: id={log_msg.id}, msg=\"{log_msg.msg}\"")
    return {"detail": "Повідомлення успішно збережено"}

@app.get("/logs")
async def get_logs():
    all_msgs = []
    for key in messages_map.key_set():
        val = messages_map.get(key)
        all_msgs.append(f"{key}: {val}")
    print(f"[Logging] Повертаємо {len(all_msgs)} записів")
    return all_msgs

@asynccontextmanager
async def lifespan(app: FastAPI):
    global hz_client, messages_map
    # 1) Реєструємося в Consul
    try:
        register_in_consul()
    except Exception as e:
        print(f"[Logging][Error] Не вдалося зареєструватись у Consul: {e}")
        sys.exit(1)

    # 2) Завантажуємо конфігурацію Hazelcast з Consul
    try:
        hc = load_hazelcast_config()
    except Exception as e:
        print(f"[Logging][Error] Не вдалося завантажити конфігурацію Hazelcast: {e}")
        deregister_from_consul()
        sys.exit(1)

    hosts = hc.get("hosts", [])
    cluster_name = hc.get("cluster_name")
    if not hosts or not cluster_name:
        print("[Logging][Error] Неповні налаштування для Hazelcast")
        deregister_from_consul()
        sys.exit(1)

    # 3) Підключаємося до Hazelcast
    try:
        hz_client = hazelcast.HazelcastClient(cluster_members=hosts, cluster_name=cluster_name)
        messages_map = hz_client.get_map("messages_map").blocking()
        print(f"[Logging] Підключено до Hazelcast: {hosts}, cluster_name={cluster_name}")
    except Exception as e:
        print(f"[Logging][Error] Неможливо підключитись до Hazelcast: {e}")
        deregister_from_consul()
        sys.exit(1)

    atexit.register(deregister_from_consul)
    yield
    # 4) Після завершення – зупиняємо Hazelcast і відписуємося
    if hz_client:
        hz_client.shutdown()
    deregister_from_consul()

app.router.lifespan_context = lifespan

if __name__ == "__main__":
    uvicorn.run("logging_service:app", host="0.0.0.0", port=SERVICE_PORT, reload=False)