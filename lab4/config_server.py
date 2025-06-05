import json
import logging
from pathlib import Path
from typing import Dict, List

from fastapi import FastAPI, Depends, HTTPException
import uvicorn



CONFIG_PATH = Path("config.json")
logger = logging.getLogger("config_service")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s"
)



class ConfigLoader:
    def __init__(self, path: Path):
        self.path = path
        self._data: Dict[str, Dict[str, List[str]]] = {}

    def reload(self) -> None:
        """Читає файл JSON і зберігає дані в пам'яті."""
        if not self.path.exists():
            logger.error(f"Файл конфігурації не знайдено: {self.path}")
            self._data = {}
            return

        try:
            with self.path.open("r", encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                raise ValueError("Очікували JSON у вигляді словника")
            self._data = raw
            logger.info(f"Конфігурацію завантажено: {self.path}")
        except json.JSONDecodeError as exc:
            logger.error(f"Помилка при розборі JSON з {self.path}: {exc}")
            self._data = {}
        except Exception as exc:
            logger.error(f"Несподівана помилка читання {self.path}: {exc}")
            self._data = {}

    def get_addresses(self, service_name: str) -> List[str]:
        """Повертає список адрес для вказаного сервісу або кидає помилку."""
        entry = self._data.get(service_name)
        if not entry or not isinstance(entry.get("addresses"), list):
            raise KeyError(f"Сервіс '{service_name}' відсутній або без адрес")
        return entry["addresses"]


# ——— Створюємо FastAPI та інстанс ConfigLoader 

app = FastAPI()
config_loader = ConfigLoader(CONFIG_PATH)




@app.on_event("startup")
async def startup():
    """
    При старті завантажуємо конфігурацію один раз.
    Якщо файл зміниться, клієнт отримає найсвіжіші дані при наступному запиті,
    але для цього потрібно перезапустити сервіс.
    """
    config_loader.reload()




def get_config() -> ConfigLoader:
    """
    Залежність FastAPI, яка повертає вже завантажений ConfigLoader.
    Якщо дані порожні, пробуємо перезавантажити знову.
    """
    if not config_loader._data:
        config_loader.reload()
    return config_loader


# ——— Роутери для роботи з конфігурацією 

@app.get("/services/{service_name}")
async def read_service_addresses(
    service_name: str,
    loader: ConfigLoader = Depends(get_config)
) -> Dict[str, List[str]]:
    """
    Шукаємо у конфігурації ключ service_name та повертаємо його addresses.
    Якщо сервіс не знайдено або немає поля "addresses", повертаємо 404.
    """
    try:
        addresses = loader.get_addresses(service_name)
        logger.info(f"Повертаємо адреси для '{service_name}': {addresses}")
        return {"service_name": service_name, "addresses": addresses}
    except KeyError:
        logger.warning(f"Сервіс '{service_name}' не знайдено або без addresses.")
        raise HTTPException(
            status_code=404,
            detail=f"Service '{service_name}' not found or no addresses provided."
        )




if __name__ == "__main__":
    # Перед запуском Uvicorn впевнюємося, що конфігурація прочиталася
    config_loader.reload()
    uvicorn.run(app, host="0.0.0.0", port=8000)