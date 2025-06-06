import os
import sys
import socket
import uuid
import json
import random
import base64
import atexit
import requests
import asyncio

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from aiokafka import AIOKafkaProducer
from contextlib import asynccontextmanager
import uvicorn

SERVICE_NAME = "facade-service"
SERVICE_PORT = int(os.getenv("FACADE_PORT", 8000))
CONSUL_ADDRESS = os.getenv("CONSUL_ADDRESS", "http://localhost:8500")
SERVICE_ID = f"{SERVICE_NAME}-{uuid.uuid4()}"

producer = None
kafka_topic = "messages"

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
    print(f"[Facade] Зареєстровано в Consul з ID={SERVICE_ID} ({ip}:{SERVICE_PORT})")

def deregister_from_consul():
    url = f"{CONSUL_ADDRESS}/v1/agent/service/deregister/{SERVICE_ID}"
    try:
        r = requests.put(url, timeout=3)
        r.raise_for_status()
        print(f"[Facade] Відреєстровано з Consul: ID={SERVICE_ID}")
    except:
        pass

def load_kafka_config():
    url = f"{CONSUL_ADDRESS}/v1/kv/kafka/config"
    r = requests.get(url, timeout=3)
    r.raise_for_status()
    data = r.json()
    raw = data[0]["Value"]
    return json.loads(base64.b64decode(raw).decode("utf-8"))

def get_healthy_instances(service_name: str):
    url = f"{CONSUL_ADDRESS}/v1/health/service/{service_name}?passing=true"
    r = requests.get(url, timeout=3)
    r.raise_for_status()
    entries = r.json()
    result = []
    for entry in entries:
        svc = entry.get("Service", {})
        addr = svc.get("Address")
        port = svc.get("Port")
        if addr and port:
            result.append(f"http://{addr}:{port}")
    return result

class IncomingMessage(BaseModel):
    msg: str

app = FastAPI()

@app.get("/health")
async def health():
    return {"status": "UP"}

@app.post("/message")
async def post_message(body: IncomingMessage):
    global producer, kafka_topic
    message_id = str(uuid.uuid4())
    payload = {"id": message_id, "msg": body.msg}
    try:
        await producer.send_and_wait(kafka_topic, payload)
        print(f"[Facade] Відправлено повідомлення до Kafka: {payload}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Kafka publish error: {e}")

    # 1) Знаходимо усі «живі» екземпляри logging-service
    log_instances = get_healthy_instances("logging-service")
    if not log_instances:
        raise HTTPException(status_code=503, detail="No healthy logging-service instances")

    # 2) Надсилаємо логи в одне з них (випадково, для балансування)
    last_err = None
    for inst_url in random.sample(log_instances, len(log_instances)):
        try:
            r = requests.post(f"{inst_url}/log", json=payload, timeout=3)
            r.raise_for_status()
            print(f"[Facade] Лог придоставлено до {inst_url}")
            break
        except Exception as e:
            last_err = e
    else:
        raise HTTPException(status_code=500, detail=f"Cannot log to any logging-service: {last_err}")

    return {"message_id": message_id, "msg": body.msg}

@app.get("/message")
async def get_message():
    # --- Отримання логів з одного з logging-service ---
    logs = "Error getting logs"
    log_instances = get_healthy_instances("logging-service")
    if log_instances:
        for inst_url in random.sample(log_instances, len(log_instances)):
            try:
                r = requests.get(f"{inst_url}/logs", timeout=5)
                r.raise_for_status()
                logs = r.json()
                break
            except:
                continue

    # --- Отримання повідомлень з одного з messages-service ---
    msgs = "Error getting messages"
    msg_instances = get_healthy_instances("messages-service")
    if msg_instances:
        for inst_url in random.sample(msg_instances, len(msg_instances)):
            try:
                r = requests.get(f"{inst_url}/messages", timeout=5)
                r.raise_for_status()
                msgs = r.json()
                break
            except:
                continue

    return {"logging": logs, "messages": msgs}

@asynccontextmanager
async def lifespan(app: FastAPI):
    global producer, kafka_topic
    # 1) Реєструємося в Consul
    try:
        register_in_consul()
    except Exception as e:
        print(f"[Facade][Error] Не вдалося зареєструватись у Consul: {e}")
        sys.exit(1)

    # 2) Завантажуємо конфігурацію Kafka з Consul
    try:
        kc = load_kafka_config()
    except Exception as e:
        print(f"[Facade][Error] Не вдалося завантажити конфігурацію Kafka: {e}")
        deregister_from_consul()
        sys.exit(1)

    bootstrap_servers = kc.get("bootstrap_servers", [])
    kafka_topic = kc.get("topic", "messages")
    if not bootstrap_servers:
        print("[Facade][Error] Не знайдено bootstrap_servers у конфігурації Kafka")
        deregister_from_consul()
        sys.exit(1)

    # 3) Ініціалізуємо та запускаємо AIOKafkaProducer
    producer = AIOKafkaProducer(
        bootstrap_servers=bootstrap_servers,
        value_serializer=lambda m: json.dumps(m).encode("utf-8")
    )
    try:
        await producer.start()
    except Exception as e:
        print(f"[Facade][Error] Помилка старту KafkaProducer: {e}")
        deregister_from_consul()
        sys.exit(1)

    atexit.register(deregister_from_consul)
    yield
    # 4) Після зупинки програми – зупиняємо продюсера і відписуємося
    if producer:
        await producer.stop()
    deregister_from_consul()

app.router.lifespan_context = lifespan

if __name__ == "__main__":
    uvicorn.run("facade_service:app", host="0.0.0.0", port=SERVICE_PORT, reload=False)