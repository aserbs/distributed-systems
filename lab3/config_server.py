import json
import logging
from fastapi import FastAPI, HTTPException
import uvicorn
from pathlib import Path

app = FastAPI()
CONFIG_FILE = Path("config.json")
SERVICE_CONFIG = {}

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

def load_config():
    global SERVICE_CONFIG
    if not CONFIG_FILE.exists():
        logger.error(f"Configuration file {CONFIG_FILE} not found.")
        SERVICE_CONFIG = {}
        return

    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as f:
            SERVICE_CONFIG = json.load(f)
        logger.info(f"Configuration loaded from {CONFIG_FILE}: {SERVICE_CONFIG}")
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON from {CONFIG_FILE}: {e}")
        SERVICE_CONFIG = {}

@app.on_event("startup")
async def on_startup():
    load_config()

@app.get("/services/{service_name}")
async def get_service_addresses(service_name: str):
    if not SERVICE_CONFIG:
        load_config()

    service_info = SERVICE_CONFIG.get(service_name)
    if not service_info or "addresses" not in service_info:
        logger.warning(f"Service '{service_name}' not found or addresses missing.")
        raise HTTPException(
            status_code=404,
            detail=f"Service '{service_name}' not found or not configured properly."
        )

    addresses = service_info["addresses"]
    logger.info(f"Returning addresses for service '{service_name}': {addresses}")
    return {"service_name": service_name, "addresses": addresses}

if __name__ == "__main__":
    load_config()
    uvicorn.run(app, host="0.0.0.0", port=8000)