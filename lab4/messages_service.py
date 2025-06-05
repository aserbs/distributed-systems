import argparse
import json
import logging
import threading
import time

from fastapi import FastAPI
from kafka import KafkaConsumer
from kafka.errors import KafkaError
import uvicorn

# ——— Конфігурація 

KAFKA_TOPIC = "lab4_messages_topic"
KAFKA_BROKERS = ["localhost:9092", "localhost:9093", "localhost:9094"]

# Вбудоване сховище повідомлень із цього екземпляру
messages_buffer: list[dict] = []

# На якому порту працює HTTP-сервіс (передається як аргумент при запуску)
service_port: int = 0


# ——— Логування

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s — %(name)s — %(levelname)s — %(message)s"
)
log = logging.getLogger("messages_service")


# ——— Сервіс Kafka Consumer 

class KafkaConsumerService:
    def __init__(self, topic: str, brokers: list[str], port: int):
        self.topic = topic
        self.brokers = brokers
        self.port = port
        self._thread = threading.Thread(target=self._run_loop, daemon=True)

    def start(self) -> None:
        """Запускаємо тред із нескінченним циклом споживача."""
        self._thread.start()
        log.info("KafkaConsumerService запущений", extra={"service_port": self.port})

    def _run_loop(self) -> None:
        """Основний нескінченний цикл: підключаємось, читаємо, обробляємо помилки."""
        while True:
            try:
                consumer = KafkaConsumer(
                    self.topic,
                    bootstrap_servers=self.brokers,
                    auto_offset_reset="earliest",
                    enable_auto_commit=True,
                    value_deserializer=lambda b: json.loads(b.decode("utf-8")),
                )
                log.info(
                    f"Підключено до Kafka: brokers={self.brokers}, topic={self.topic}",
                    extra={"service_port": self.port}
                )

                for msg in consumer:
                    entry = {
                        "partition": msg.partition,
                        "offset": msg.offset,
                        "key": msg.key,
                        "value": msg.value,
                    }
                    log.info(
                        f"Отримано: partition={msg.partition}, offset={msg.offset}, value={msg.value}",
                        extra={"service_port": self.port}
                    )
                    messages_buffer.append(msg.value)

                # Якщо consumer завершує ітерацію (наприклад, через таймаут),
                # можна перезапустити підключення.
                log.warning("KafkaConsumer припинив отримувати дані, пробуємо перепідключитись", extra={"service_port": self.port})

            except KafkaError as ke:
                log.error(f"Помилка KafkaConsumer: {ke}. Повтор через 5 секунд...", extra={"service_port": self.port})
                time.sleep(5)
            except Exception as ex:
                log.error(f"Несподівана помилка в KafkaConsumer: {ex}. Повтор через 5 секунд...", extra={"service_port": self.port})
                time.sleep(5)


# ——— REST API через FastAPI ———————————————————————————————————————

app = FastAPI()


@app.on_event("startup")
async def on_startup() -> None:
    """
    При старті FastAPI запускаємо фоновий тред із KafkaConsumerService.
    Поле service_port уже встановлено перед викликом uvicorn.run().
    """
    consumer_service = KafkaConsumerService(
        topic=KAFKA_TOPIC,
        brokers=KAFKA_BROKERS,
        port=service_port
    )
    consumer_service.start()
    log.info("HTTP-сервіс стартував, Kafka-потік запущено", extra={"service_port": service_port})


@app.get("/messages")
async def read_messages() -> dict:
    """
    Повертає всі збережені повідомлення з цього екземпляру-сервісу.
    """
    count = len(messages_buffer)
    log.info(f"GET /messages → повертаємо {count} записів", extra={"service_port": service_port})
    return {
        "instance_port": service_port,
        "messages": messages_buffer
    }




def main() -> None:
    parser = argparse.ArgumentParser(description="Messages Service з Kafka Consumer")
    parser.add_argument(
        "--port",
        type=int,
        required=True,
        help="Порт, на якому слухає HTTP-сервіс"
    )
    args = parser.parse_args()

    global service_port
    service_port = args.port

    # Запускаємо Uvicorn із FastAPI-додатком
    uvicorn.run(app, host="0.0.0.0", port=service_port)


if __name__ == "__main__":
    main()