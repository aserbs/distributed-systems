import grpc
from concurrent import futures
import time
import logging_pb2
import logging_pb2_grpc
import hazelcast
import logging
import argparse

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(port)s - %(message)s'
)

class HazelcastClientWrapper:
    def __init__(self, cluster_members, cluster_name, map_name, port):
        self.client = None
        self.map = None
        self.cluster_members = cluster_members
        self.cluster_name = cluster_name
        self.map_name = map_name
        self.port = port

    def connect(self):
        try:
            self.client = hazelcast.HazelcastClient(
                cluster_members=self.cluster_members,
                cluster_name=self.cluster_name
            )
            self.map = self.client.get_map(self.map_name).blocking()
            logger.info(f"Hazelcast client connected and map '{self.map_name}' obtained. Running on port {self.port}", extra={'port': str(self.port)})
        except Exception as e:
            logger.error(f"Не вдалося підключитися до Hazelcast або отримати карту: {e}", extra={'port': str(self.port)})

    def put_message(self, key, value):
        if self.map is None:
            raise RuntimeError("Hazelcast map not initialized")
        self.map.put(key, value)

    def get_all_messages(self):
        if self.map is None:
            raise RuntimeError("Hazelcast map not initialized")
        return list(self.map.values())

    def shutdown(self):
        if self.client:
            self.client.shutdown()
            logger.info("Hazelcast client вимкнено.", extra={'port': str(self.port)})

class LoggingService(logging_pb2_grpc.LoggingServiceServicer):
    def __init__(self, hz_client_wrapper):
        self.hz_client_wrapper = hz_client_wrapper

    def Log(self, request, context):
        if self.hz_client_wrapper.map is None:
            logger.error("Hazelcast logs_map is not initialized.")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("Hazelcast logs_map is not initialized.")
            return logging_pb2.LogResponse(status="Error: Hazelcast not initialized")

        try:
            self.hz_client_wrapper.put_message(request.uuid, request.msg)
            current_port = context.peer().split(':')[-1]
            logger.info(f"Повідомлення збережено в Hazelcast: {request.uuid} -> {request.msg}", extra={'port': current_port})
            return logging_pb2.LogResponse(status="OK")
        except Exception as e:
            logger.error(f"Помилка при збереженні в Hazelcast: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Помилка Hazelcast: {str(e)}")
            return logging_pb2.LogResponse(status=f"Error: {str(e)}")

    def GetLogs(self, request, context):
        if self.hz_client_wrapper.map is None:
            logger.error("Hazelcast logs_map is not initialized.")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("Hazelcast logs_map is not initialized.")
            return logging_pb2.LogsResponse(messages=[])

        try:
            messages = self.hz_client_wrapper.get_all_messages()
            current_port = context.peer().split(':')[-1]
            logger.info(f"Витягнуто {len(messages)} повідомлень з Hazelcast.", extra={'port': current_port})
            return logging_pb2.LogsResponse(messages=messages)
        except Exception as e:
            logger.error(f"Помилка при читанні з Hazelcast: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Помилка Hazelcast: {str(e)}")
            return logging_pb2.LogsResponse(messages=[])

def serve(port: int):
    cluster_members = [
        "127.0.0.1:5701",
        "127.0.0.1:5702",
        "127.0.0.1:5703"
    ]
    cluster_name = "dev"
    map_name = "logging_service_map"

    hz_client_wrapper = HazelcastClientWrapper(cluster_members, cluster_name, map_name, port)
    hz_client_wrapper.connect()

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    logging_pb2_grpc.add_LoggingServiceServicer_to_server(LoggingService(hz_client_wrapper), server)
    server.add_insecure_port(f'[::]:{port}')
    server.start()
    logger.info(f"Logging Service gRPC сервер запущено на порту {port}", extra={'port': str(port)})

    try:
        while True:
            time.sleep(86400)
    except KeyboardInterrupt:
        logger.info("Зупинка сервера...", extra={'port': str(port)})
        server.stop(0)
        hz_client_wrapper.shutdown()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Logging Service with Hazelcast")
    parser.add_argument('--port', type=int, required=True, help='Port for the gRPC server')
    args = parser.parse_args()

    serve(args.port)