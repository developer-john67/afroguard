import os
import base64
import hashlib
import json
import time
import uuid
from typing import List, Optional, Type, TypeVar
from pydantic import BaseModel, ValidationError
from PIL import Image
from io import BytesIO

import httpx
from openai import OpenAI

from server.db import log_vlm_call

T = TypeVar("T", bound=BaseModel)

QWEN_API_KEY = os.getenv("QWEN_API_KEY")
QWEN_BASE_URL = os.getenv("QWEN_BASE_URL")
QWEN_VL_MODEL = os.getenv("QWEN_VL_MODEL")
QWEN_TIMEOUT_SECONDS = float(os.getenv("QWEN_TIMEOUT_SECONDS", "120"))
DIAGNOSIS_SAMPLES = int(os.getenv("DIAGNOSIS_SAMPLES", "1"))
GENERATE_EXPLANATION = os.getenv("GENERATE_EXPLANATION", "0") == "1"
REPLAY_MODE = os.getenv("REPLAY_MODE", "0") == "1"
REPLAY_DIR = os.getenv("REPLAY_DIR", "eval/replay")
FALLBACK_TIMEOUT_SECONDS = float(os.getenv("FALLBACK_TIMEOUT_SECONDS", "30"))
TEXT_PROVIDER_ORDER = os.getenv(
    "TEXT_PROVIDER_ORDER",
    "openrouter,groq,mistral,aionlabs,primary",
).split(",")


def _configured_providers() -> List[dict]:
    providers = []
    if QWEN_API_KEY and QWEN_BASE_URL and QWEN_VL_MODEL:
        providers.append({"name": "primary", "api_key": QWEN_API_KEY, "base_url": QWEN_BASE_URL, "model": QWEN_VL_MODEL})

    provider_defaults = {
        "openrouter": "https://openrouter.ai/api/v1",
        "groq": "https://api.groq.com/openai/v1",
        "mistral": "https://api.mistral.ai/v1",
        "aionlabs": "https://api.aionlabs.ai/v1",
    }
    for name in os.getenv("REMOTE_PROVIDER_ORDER", "").split(","):
        name = name.strip().lower()
        if not name or name not in provider_defaults:
            continue
        api_key = os.getenv(f"{name.upper()}_API_KEY")
        model = os.getenv(f"{name.upper()}_MODEL")
        if api_key and model:
            providers.append({
                "name": name,
                "api_key": api_key,
                "base_url": os.getenv(f"{name.upper()}_BASE_URL", provider_defaults[name]),
                "model": model,
            })
    return providers


def _ordered_providers(providers: List[dict], text_only: bool) -> List[dict]:
    if not text_only:
        return providers
    by_name = {provider["name"]: provider for provider in providers}
    return [by_name[name.strip()] for name in TEXT_PROVIDER_ORDER if name.strip() in by_name]


def _image_hash(image_bytes: bytes) -> str:
    return hashlib.sha256(image_bytes).hexdigest()


def _replay_path(image_hash: str) -> str:
    return os.path.join(REPLAY_DIR, f"{image_hash}.json")


def _load_replay(image_hash: str) -> Optional[dict]:
    path = _replay_path(image_hash)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None


def _save_replay(image_hash: str, response: dict):
    os.makedirs(REPLAY_DIR, exist_ok=True)
    path = _replay_path(image_hash)
    with open(path, "w") as f:
        json.dump(response, f)


def _b64_image(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode()


def _prepare_image(image_bytes: bytes) -> bytes:
    with Image.open(BytesIO(image_bytes)) as image:
        image = image.convert("RGB")
        image.thumbnail((1024, 1024))
        output = BytesIO()
        image.save(output, format="JPEG", quality=78, optimize=True)
        return output.getvalue()


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def vlm_json(
    images: list[bytes],
    system: str,
    schema: Type[T],
    retries: int = 0,
    timeout_seconds: Optional[float] = None,
) -> Optional[T]:
    providers = _configured_providers()
    if not providers:
        raise RuntimeError("No VLM provider configured")

    images = [_prepare_image(img) for img in images]
    img_hashes = [_image_hash(img) for img in images]
    combined_hash = hashlib.sha256("".join(img_hashes).encode()).hexdigest()

    if REPLAY_MODE:
        cached = _load_replay(combined_hash)
        if cached:
            print(f"[REPLAY_MODE] Serving cached response for {combined_hash[:16]}...")
            try:
                return schema.model_validate(cached)
            except ValidationError as e:
                print(f"[REPLAY_MODE] Cached response failed validation: {e}")
        else:
            print(f"[REPLAY_MODE] WARNING: No cached response for {combined_hash[:16]} — calling live API")

    content = [
        {"type": "text", "text": system + "\n\nRespond ONLY with valid JSON matching the schema. No code fences, no extra text."}
    ]
    for img in images:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{_b64_image(img)}"}})

    messages = [
        {"role": "system", "content": "You are a precise agricultural vision model. Output only JSON."},
        {"role": "user", "content": content},
    ]

    last_error = None
    for provider in _ordered_providers(providers, text_only=not images):
        timeout = timeout_seconds or (QWEN_TIMEOUT_SECONDS if provider["name"] == "primary" else FALLBACK_TIMEOUT_SECONDS)
        client = OpenAI(
            api_key=provider["api_key"],
            base_url=provider["base_url"],
            timeout=httpx.Timeout(connect=15.0, read=timeout, write=30.0, pool=15.0),
            max_retries=0,
        )
        call_id = str(uuid.uuid4())
        start = time.time()
        error_msg = None
        success = False
        try:
            for attempt in range(retries + 1):
                resp = client.chat.completions.create(
                    model=provider["model"],
                    messages=messages,
                    temperature=0,
                    max_tokens=500 if not images else 2000,
                )
                raw = _strip_code_fences(resp.choices[0].message.content or "")
                try:
                    parsed = schema.model_validate_json(raw)
                    success = True
                    if REPLAY_MODE and not _load_replay(combined_hash):
                        _save_replay(combined_hash, json.loads(raw))
                    return parsed
                except ValidationError as e:
                    error_msg = str(e)
                    if attempt < retries:
                        messages.append({"role": "assistant", "content": raw})
                        messages.append({"role": "user", "content": f"JSON validation failed: {e}. Respond with corrected JSON only."})
                    else:
                        raise
        except Exception as e:
            last_error = e
            error_msg = str(e)
            print(f"[VLM] Provider {provider['name']} failed; trying next provider if configured: {e}")
        finally:
            latency = int((time.time() - start) * 1000)
            log_vlm_call(call_id, "chat/completions", f"{provider['name']}:{provider['model']}", latency, success, error_msg)

    raise RuntimeError(f"All configured VLM providers failed: {last_error}")