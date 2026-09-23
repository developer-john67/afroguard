import base64
import json
from typing import Optional, Tuple, Dict, Any
from datetime import datetime

from pydantic import BaseModel
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError

from server.schemas import ProvenancePayload
from server.db import get_conn


def parse_code(code: str) -> Optional[ProvenancePayload]:
    if not (code.startswith("https://") or code.startswith("http://localhost")):
        return None
    try:
        path = code.split("/v/")[-1]
        payload_b64, sig_b64 = path.split(".", 1)
        payload_json = base64.urlsafe_b64decode(payload_b64 + "==").decode()
        data = json.loads(payload_json)
        if not isinstance(data, list) or len(data) != 5:
            return None
        return ProvenancePayload(
            manufacturer_id=data[0],
            product_id=data[1],
            batch=data[2],
            expiry=data[3],
            serial=data[4],
            signature=sig_b64,
        )
    except Exception:
        return None


def verify_signature(payload: ProvenancePayload, public_key_b64: str) -> bool:
    try:
        verify_key = VerifyKey(base64.urlsafe_b64decode(public_key_b64 + "=="))
        payload_bytes = json.dumps([
            payload.manufacturer_id,
            payload.product_id,
            payload.batch,
            payload.expiry,
            payload.serial,
        ], separators=(",", ":")).encode()
        if not payload.signature:
            return False
        sig_bytes = base64.urlsafe_b64decode(payload.signature + "==")
        verify_key.verify(payload_bytes, sig_bytes)
        return True
    except (BadSignatureError, Exception):
        return False


def verify_signature_with_sig(payload: ProvenancePayload, public_key_b64: str, sig_b64: str) -> bool:
    try:
        verify_key = VerifyKey(base64.urlsafe_b64decode(public_key_b64 + "=="))
        payload_bytes = json.dumps([
            payload.manufacturer_id,
            payload.product_id,
            payload.batch,
            payload.expiry,
            payload.serial,
        ], separators=(",", ":")).encode()
        sig_bytes = base64.urlsafe_b64decode(sig_b64 + "==")
        verify_key.verify(payload_bytes, sig_bytes)
        return True
    except (BadSignatureError, Exception):
        return False


def compute_verdict(
    payload: ProvenancePayload,
    sig_valid: bool,
    product_row: Dict[str, Any],
    scan_history: list,
    distinct_clients: int,
    client_id: str,
    clone_threshold: int = 2,
) -> Tuple[str, str, str]:
    if not sig_valid:
        return "FORGED", "SIG_INVALID", "The QR code signature is invalid. This code is forged."

    with get_conn() as conn:
        key_row = conn.execute(
            "SELECT * FROM manufacturers WHERE manufacturer_id = ?", (payload.manufacturer_id,)
        ).fetchone()
        if not key_row:
            return "FORGED", "UNKNOWN_KEY", "The manufacturer key is not recognized."

    if product_row.get("recalled"):
        return "FORGED", "RECALLED", "This batch has been RECALLED. Do not use this product."

    try:
        exp_date = datetime.strptime(product_row["expiry"], "%Y-%m-%d")
        if exp_date < datetime.utcnow():
            return "SUSPICIOUS", "EXPIRED", "This product has expired."
    except Exception:
        pass

    if not scan_history:
        return "GENUINE", "FIRST_SCAN", "First scan recorded. This product appears genuine."

    same_client_scans = [s for s in scan_history if s["client_id"] == client_id]
    if same_client_scans:
        return "GENUINE", "REPEAT_SAME_CLIENT", "You have scanned this product before. It appears genuine."

    return "SUSPICIOUS", "CLONE_SUSPECTED", "This single-use code was already redeemed by another client. Possible clone detected."


def build_qr_code(host: str, payload: ProvenancePayload, private_key_b64: str) -> str:
    from nacl.signing import SigningKey
    signing_key = SigningKey(base64.urlsafe_b64decode(private_key_b64 + "=="))
    payload_bytes = json.dumps([
        payload.manufacturer_id,
        payload.product_id,
        payload.batch,
        payload.expiry,
        payload.serial,
    ], separators=(",", ":")).encode()
    signed = signing_key.sign(payload_bytes)
    payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode().rstrip("=")
    sig_b64 = base64.urlsafe_b64encode(signed.signature).decode().rstrip("=")
    return f"{host}/v/{payload_b64}.{sig_b64}"