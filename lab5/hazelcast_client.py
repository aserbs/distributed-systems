from consul_client import kv_json
import hazelcast

_hz = None

async def get_client():
    global _hz
    if _hz:
        return _hz
    cfg = kv_json("hazelcast/config", {})
    _hz = await hazelcast.HazelcastClient(
        cluster_name=cfg.get("cluster_name", "lab5"),
        cluster_members=cfg.get("members", ["hz1", "hz2", "hz3"])
    ).start()
    return _hz