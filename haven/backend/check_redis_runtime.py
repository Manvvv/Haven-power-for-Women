from pathlib import Path
import os
import sys
import uuid
from index_catalog import validate_configured_redis_target

# Load the nearest project environment file if available.
# Existing process-level environment variables take precedence.
try:
    from dotenv import load_dotenv

    here = Path(__file__).resolve().parent
    repo_root = here.parent

    for env_file in (here / ".env", repo_root / ".env"):
        if env_file.is_file():
            load_dotenv(env_file, override=False)
            print(f"Environment file found: {env_file.name}")
            break
except ImportError:
    print("python-dotenv unavailable; using process environment only")

enabled = os.getenv("REDIS_ENABLED", "false").strip().lower()
required = os.getenv("REDIS_REQUIRED_IN_PRODUCTION", "false").strip().lower()
url = os.getenv("REDIS_URL")

print(f"REDIS_ENABLED={enabled}")
print(f"REDIS_REQUIRED_IN_PRODUCTION={required}")
print(f"REDIS_URL configured={bool(url)}")

target = validate_configured_redis_target(url or "")
if not target.approved:
    print(f"FAIL: staging Redis target rejected: {target.reason}")
    print("No Redis connection or temporary write was attempted.")
    sys.exit(1)

print(f"Approved Redis target: {target.target_id}; database={target.database_name}")

try:
    import redis
except ImportError:
    print("FAIL: Python package 'redis' is not installed in this interpreter.")
    sys.exit(1)

client = None
key = f"haven:redis-diagnostic:{uuid.uuid4().hex}"

try:
    client = redis.Redis.from_url(
        url,
        socket_connect_timeout=3,
        socket_timeout=3,
        decode_responses=True,
    )

    if client.ping() is not True:
        raise RuntimeError("Redis PING did not return success")

    print("Redis PING: PASS")

    # Check the basic commands needed for safe temporary coordination.
    if client.set(key, "ok", nx=True, ex=30) is not True:
        raise RuntimeError("Temporary SET operation did not succeed")

    if client.get(key) != "ok":
        raise RuntimeError("Temporary GET operation did not return expected data")

    print("Redis SET/GET: PASS")

    client.delete(key)
    print("Redis DELETE: PASS")
    print("RESULT: Redis connection and basic read/write operations passed.")

except Exception as exc:
    # Print only the exception class; do not expose credentials or URL.
    print(f"FAIL: {type(exc).__name__}")
    print("Check service availability, network access, authentication, and TLS settings.")
    sys.exit(1)

finally:
    if client is not None:
        try:
            client.delete(key)
        except Exception:
            pass

        client.close()
