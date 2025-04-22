import grpc
from concurrent import futures
import logging_pb2 as logging_service_pb2
import logging_pb2_grpc as logging_service_pb2_grpc

logs = {}

class LoggingService(logging_service_pb2_grpc.LoggingServiceServicer):
    def LogMessage(self, request, context):
        if request.id not in logs:
            logs[request.id] = request.msg
            print(f"[LOGGED] {request.id} -> {request.msg}")
        else:
            print(f"[DUPLICATE] {request.id}")
        return logging_service_pb2.LogResponse(detail="logged")

    def GetLogs(self, request, context):
        return logging_service_pb2.LogList(logs=list(logs.values()))

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    logging_service_pb2_grpc.add_LoggingServiceServicer_to_server(LoggingService(), server)
    server.add_insecure_port('[::]:50051')
    server.start()
    print("Logging gRPC service running on port 50051")
    server.wait_for_termination()

if __name__ == '__main__':
    serve()