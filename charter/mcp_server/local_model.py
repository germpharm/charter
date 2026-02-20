"""Local Model MCP Tool — expose local LLM inference through Charter governance.

Every call is logged to the immutable hash chain. The tool calls the local
mlx-lm server (OpenAI-compatible) and returns the response.
"""

import hashlib
import json
import os
import ssl
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from charter.identity import append_to_chain

# SSL context for HTTPS tunnel endpoints
try:
    import certifi
    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CONTEXT = ssl.create_default_context()
    cert_path = "/etc/ssl/cert.pem"
    if os.path.exists(cert_path):
        _SSL_CONTEXT.load_verify_locations(cert_path)

# Default local endpoint (Mini)
DEFAULT_URL = os.environ.get("LOCAL_MODEL_URL", "http://localhost:8000/v1")
DEFAULT_MODEL = os.environ.get(
    "LOCAL_MODEL_NAME", "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit"
)


def call_local_model(prompt, system=None, max_tokens=2048, temperature=0.3):
    """Call the local model server and log to Charter chain.

    Returns dict with text, model, usage, duration_ms.
    """
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": DEFAULT_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    url = f"{DEFAULT_URL}/chat/completions"
    start = time.time()

    req = Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    ctx = _SSL_CONTEXT if url.startswith("https") else None

    try:
        with urlopen(req, context=ctx, timeout=180) as resp:
            result = json.loads(resp.read())
    except (HTTPError, URLError, ConnectionRefusedError, TimeoutError) as e:
        # Log failure to chain
        append_to_chain("local_inference_failed", {
            "error": str(e),
            "model": DEFAULT_MODEL,
            "prompt_hash": hashlib.sha256(prompt.encode()).hexdigest()[:16],
        })
        raise ConnectionError(f"Local model server unreachable at {url}: {e}")

    duration_ms = int((time.time() - start) * 1000)
    text = result["choices"][0]["message"]["content"]
    usage = result.get("usage", {})

    # Log to Charter chain
    append_to_chain("local_inference", {
        "model": result.get("model", DEFAULT_MODEL),
        "prompt_hash": hashlib.sha256(prompt.encode()).hexdigest()[:16],
        "response_length": len(text),
        "tokens": usage,
        "duration_ms": duration_ms,
    })

    return {
        "text": text,
        "model": result.get("model", DEFAULT_MODEL),
        "usage": usage,
        "duration_ms": duration_ms,
    }
