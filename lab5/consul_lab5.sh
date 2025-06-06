#!/bin/sh

# Чекаємо, доки Consul підніметься
sleep 5

# 1) Записуємо налаштування Hazelcast у KV Consul
curl --request PUT \
     --data '{
  "hosts": ["hazelcast1:5701", "hazelcast2:5701", "hazelcast3:5701"],
  "cluster_name": "dev"
}' \
     http://consul:8500/v1/kv/hazelcast/config

# 2) Записуємо налаштування Kafka у KV Consul
curl --request PUT \
     --data '{
  "bootstrap_servers": ["kafka1:9092", "kafka2:9093", "kafka3:9094"],
  "topic": "messages"
}' \
     http://consul:8500/v1/kv/kafka/config