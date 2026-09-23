import json
from typing import Dict, Any, Optional

from server.vlm import vlm_json
from server.prompts import LABEL_EXTRACTION_SYSTEM, LABEL_EXTRACTION_USER
from server.schemas import VLMFieldExtraction, VerifyLabelResponse
from server.db import get_conn


def verify_label_image(image_bytes: bytes) -> VerifyLabelResponse:
    extracted = vlm_json([image_bytes], LABEL_EXTRACTION_SYSTEM, VLMFieldExtraction)
    if not extracted:
        return VerifyLabelResponse(
            verdict="UNVERIFIABLE",
            reason_human="Could not extract label information. Try a clearer photo.",
            extracted_fields=VLMFieldExtraction(),
            anomalies=["Vision model unavailable"],
        )

    match = None
    anomalies = list(extracted.visual_anomalies)

    if extracted.product_name and extracted.manufacturer and extracted.batch:
        with get_conn() as conn:
            row = conn.execute("""
                SELECT p.*, m.name as manufacturer_name
                FROM products p
                JOIN manufacturers m ON p.manufacturer_id = m.manufacturer_id
                WHERE p.name = ? AND m.name = ? AND p.batch = ?
            """, (extracted.product_name, extracted.manufacturer, extracted.batch)).fetchone()

            if row:
                match = dict(row)
                if extracted.expiry and extracted.expiry != row["expiry"]:
                    anomalies.append(f"Expiry mismatch: label says {extracted.expiry}, registry has {row['expiry']}")
                if extracted.active_ingredient and extracted.active_ingredient.lower() not in row["active_ingredient_class"].lower():
                    anomalies.append(f"Active ingredient mismatch: label says {extracted.active_ingredient}, registry class is {row['active_ingredient_class']}")
                if extracted.registration_number and extracted.registration_number != row.get("registration_number"):
                    anomalies.append(f"Registration number mismatch")
            else:
                anomalies.append("Product not found in registry (name/manufacturer/batch combination)")

    verdict = "SUSPICIOUS" if anomalies else "UNVERIFIABLE"
    reason = "Label has anomalies worth a closer look." if anomalies else "Label extracted but no matching registry entry. A label alone cannot prove authenticity."

    return VerifyLabelResponse(
        verdict=verdict,
        reason_human=reason,
        extracted_fields=extracted,
        registry_match=match,
        anomalies=anomalies,
    )