import os
from typing import List
from uuid import uuid4
from pydantic import BaseModel

from server.prompts import EXPLANATION_SYSTEM, EXPLANATION_USER
from server.schemas import DiagnoseResponse
from server.kb_loader import get_disease_entry
from server.plant_model import CONFIDENCE_THRESHOLD, predict
from server.crop_model import predict_crop

GENERATE_EXPLANATION = os.getenv("GENERATE_EXPLANATION", "1") == "1"

CLASS_TO_CONDITION = {
    "Corn_(maize)___Cercospora_leaf_spot Gray_leaf_spot": "gray_leaf_spot",
    "Corn_(maize)___Common_rust_": "common_rust",
    "Corn_(maize)___Northern_Leaf_Blight": "northern_leaf_blight",
    "Tomato___Bacterial_spot": "bacterial_spot",
    "Tomato___Early_blight": "early_blight",
    "Tomato___Late_blight": "late_blight",
    "Tomato___Spider_mites Two-spotted_spider_mite": "spider_mite",
    "Tomato___Tomato_Yellow_Leaf_Curl_Virus": "tomato_yellow_leaf_curl",
}

SUPPORTED_CROPS = {"Corn_(maize)": "maize", "Tomato": "tomato"}


def diagnose_image(image_bytes: bytes, lang: str = "en") -> DiagnoseResponse:
    crop_prediction = predict_crop(image_bytes)
    if crop_prediction.confidence < CONFIDENCE_THRESHOLD:
        return DiagnoseResponse(
            status="uncertain",
            retake_reason=f"The crop model is only {crop_prediction.confidence:.0%} confident. Try a clearer photo of one leaf.",
            crop=crop_prediction.crop.lower(),
            differential=[],
            diagnosis_id=uuid4(),
        )

    crop_name = {"Corn": "maize", "Tomato": "tomato"}.get(crop_prediction.crop)
    if not crop_name:
        return DiagnoseResponse(
            status="uncertain",
            retake_reason=f"{crop_prediction.crop} was recognized, but a disease classifier for this crop is not installed yet.",
            crop=crop_prediction.crop.lower(),
            differential=[{"condition": "crop_recognized", "agreement": crop_prediction.confidence, "visible_evidence": []}],
            diagnosis_id=uuid4(),
        )

    prediction = predict(image_bytes)
    raw_crop, _, _ = prediction.class_name.partition("___")
    crop = crop_name
    condition = _condition_from_class(prediction.class_name)

    if raw_crop != ("Corn_(maize)" if crop_name == "maize" else "Tomato"):
        return DiagnoseResponse(
            status="uncertain",
            retake_reason="The crop and disease classifiers disagree. Try a clear photo of one leaf.",
            crop=crop,
            diagnosis_id=uuid4(),
        )

    confidence = prediction.confidence
    status = "ok" if confidence >= CONFIDENCE_THRESHOLD else "uncertain"
    retake_reason = None if status == "ok" else f"Low confidence ({confidence:.0%}). Try a clearer photo of one affected leaf."
    differential = [{
        "condition": condition,
        "agreement": round(confidence, 2),
        "visible_evidence": [prediction.class_name.replace("___", ": ")],
    }]
    differential.extend({
        "condition": _condition_from_class(item["class_name"]),
        "agreement": item["confidence"],
        "visible_evidence": [],
    } for item in prediction.alternatives)

    top_condition = condition
    disease_entry = get_disease_entry(top_condition) if status == "ok" else None
    recommended_classes = disease_entry.get("recommended_ingredient_classes", []) if disease_entry else []
    cultural_controls = disease_entry.get("cultural_controls", []) if disease_entry else []
    consult_ext = disease_entry.get("consult_extension_officer", False) if disease_entry else False

    explanation = ""
    if disease_entry and GENERATE_EXPLANATION:
        explanation = _generate_explanation(
            crop, top_condition, differential[0]["visible_evidence"] if differential else [],
            recommended_classes, cultural_controls, consult_ext, lang
        )

    if not explanation and disease_entry:
        explanation = _build_kb_explanation(disease_entry, confidence)
    elif not explanation and status == "ok":
        if condition == "healthy":
            explanation = (
                f"The image is most consistent with a healthy {crop} leaf "
                f"({confidence:.0%} classifier confidence). No disease was identified, "
                "so pesticide treatment is not recommended from this result."
            )
        else:
            label = prediction.class_name.partition("___")[2].replace("_", " ").strip()
            explanation = (
                f"The image is most consistent with {label} "
                f"({confidence:.0%} classifier confidence), but AgroGuard has no reviewed "
                "treatment guidance for this class. Do not select a pesticide from this "
                "screening result; ask a local extension officer to confirm the problem."
            )

    return DiagnoseResponse(
        status=status,
        retake_reason=retake_reason,
        crop=crop,
        differential=differential,
        top_condition=top_condition if top_condition != "other_or_none" else None,
        recommended_ingredient_classes=recommended_classes,
        consult_extension_officer=consult_ext,
        explanation_localized=explanation,
        diagnosis_id=uuid4(),
    )


def _condition_from_class(class_name: str) -> str:
    mapped = CLASS_TO_CONDITION.get(class_name)
    if mapped:
        return mapped
    _, separator, label = class_name.partition("___")
    if not separator:
        return "unmapped_condition"
    if label.lower() == "healthy":
        return "healthy"
    return label.lower().replace(" ", "_").replace("(", "").replace(")", "")


def _build_kb_explanation(entry: dict, confidence: float) -> str:
    symptoms = ", ".join(entry.get("symptoms", [])[:4]) or "the visible symptoms in the image"
    controls = "; ".join(entry.get("cultural_controls", [])[:4]) or "good field hygiene and regular crop scouting"
    classes = ", ".join(entry.get("recommended_ingredient_classes", []))
    recommendation = (
        f"Approved ingredient classes to discuss with a local advisor: {classes}."
        if classes
        else "No specific ingredient class is listed for this condition; focus on cultural controls and expert advice."
    )
    officer = " Consult a local extension officer before treatment, especially if symptoms spread or the crop is valuable." if entry.get("consult_extension_officer") else ""
    return (
        f"The image is most consistent with {entry.get('name', 'this condition')} "
        f"({confidence:.0%} classifier confidence). Look for {symptoms}. "
        f"Helpful non-chemical steps include {controls}. {recommendation}{officer} "
        "This is a screening result, not a laboratory confirmation; compare the symptoms with nearby plants and retake the photo if the condition changes."
    )


def _generate_explanation(
    crop: str,
    condition: str,
    evidence: List[str],
    classes: List[str],
    controls: List[str],
    consult: bool,
    lang: str,
) -> str:
    from server.vlm import vlm_json
    from server.schemas import VLMDiagnoseResponse

    prompt = EXPLANATION_USER.format(
        crop=crop,
        condition=condition,
        evidence=", ".join(evidence) if evidence else "general symptoms",
        classes=", ".join(classes) if classes else "none specific",
        controls=", ".join(controls) if controls else "good field hygiene",
        consult="yes" if consult else "no",
        lang=lang,
    )

    class ExplanationResponse(BaseModel):
        explanation: str

    try:
        result = vlm_json(
            [],
            EXPLANATION_SYSTEM.format(lang=lang) + "\n\n" + prompt,
            ExplanationResponse,
            timeout_seconds=10,
        )
    except Exception:
        result = None
    return result.explanation if result else f"Diagnosis: {condition}. Recommended: {', '.join(classes) or 'consult expert'}."
