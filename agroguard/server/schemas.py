from pydantic import BaseModel, Field, HttpUrl
from typing import List, Optional, Literal, Dict, Any
from uuid import UUID, uuid4
from datetime import datetime
import base64


class VLMGateResponse(BaseModel):
    is_plant: bool
    crop: Optional[Literal["maize", "tomato", "cassava"]] = None
    usable: bool
    retake_reason: Optional[str] = None
    quality_issues: List[str] = Field(default_factory=list)


class VLMDiagnoseItem(BaseModel):
    condition: str
    agreement: float = Field(ge=0.0, le=1.0)
    visible_evidence: List[str] = Field(default_factory=list)


class VLMDiagnoseResponse(BaseModel):
    differential: List[VLMDiagnoseItem] = Field(min_length=1, max_length=3)
    top_condition: str
    explanation: str


class VLMFieldExtraction(BaseModel):
    product_name: Optional[str] = None
    manufacturer: Optional[str] = None
    batch: Optional[str] = None
    expiry: Optional[str] = None
    registration_number: Optional[str] = None
    active_ingredient: Optional[str] = None
    visual_anomalies: List[str] = Field(default_factory=list)


class DiagnoseRequest(BaseModel):
    lang: str = "en"


class DiagnoseResponse(BaseModel):
    status: Literal["ok", "retake", "out_of_scope", "uncertain"]
    retake_reason: Optional[str] = None
    crop: Optional[str] = None
    differential: List[Dict[str, Any]] = Field(default_factory=list)
    top_condition: Optional[str] = None
    recommended_ingredient_classes: List[str] = Field(default_factory=list)
    consult_extension_officer: bool = False
    explanation_localized: Optional[str] = None
    diagnosis_id: UUID = Field(default_factory=uuid4)


class VerifyCodeRequest(BaseModel):
    code: str
    client_id: str
    diagnosis_id: Optional[UUID] = None


class IssueDemoCodeRequest(BaseModel):
    product_id: str
    count: int = Field(default=1, ge=1, le=10)


class IssueDemoCodeResponse(BaseModel):
    codes: List[str]
    qr_images: List[str] = Field(default_factory=list)


class DecodeQrResponse(BaseModel):
    code: str


class ProductInfo(BaseModel):
    name: str
    manufacturer: str
    batch: str
    expiry: str
    active_ingredient_class: str


class VerifyCodeResponse(BaseModel):
    verdict: Literal["GENUINE", "SUSPICIOUS", "FORGED", "UNVERIFIABLE"]
    reason_code: Literal[
        "SIG_INVALID", "UNKNOWN_KEY", "RECALLED", "EXPIRED",
        "FIRST_SCAN", "REPEAT_SAME_CLIENT", "CLONE_SUSPECTED", "MALFORMED"
    ]
    reason_human: str
    product: ProductInfo
    scan_count: int
    matches_diagnosis: bool
    diagnosis_match_note: str


class VerifyLabelRequest(BaseModel):
    pass


class VerifyLabelResponse(BaseModel):
    verdict: Literal["SUSPICIOUS", "UNVERIFIABLE"]
    reason_human: str
    extracted_fields: VLMFieldExtraction
    registry_match: Optional[Dict[str, Any]] = None
    anomalies: List[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"


class PublicKeyEntry(BaseModel):
    manufacturer_id: str
    public_key: str


class PublicKeysResponse(BaseModel):
    keys: List[PublicKeyEntry]


class DiseaseKBEntry(BaseModel):
    id: str
    crop: Literal["maize", "tomato", "cassava"]
    name: str
    category: Literal["disease", "pest", "nutrient", "abiotic"]
    symptoms: List[str]
    look_alikes: List[str] = Field(default_factory=list)
    recommended_ingredient_classes: List[str]
    cultural_controls: List[str] = Field(default_factory=list)
    consult_extension_officer: bool = False
    source_note: str
    needs_expert_review: bool = True


class ProductKBEntry(BaseModel):
    product_id: str
    name: str
    manufacturer: str
    manufacturer_id: str
    active_ingredient_class: str
    batch: str
    expiry: str
    registration_number: str


class ProvenancePayload(BaseModel):
    manufacturer_id: str
    product_id: str
    batch: str
    expiry: str
    serial: str
    signature: Optional[str] = None


class ScanEvent(BaseModel):
    serial: str
    client_id: str
    timestamp: datetime
    verdict: str
    reason_code: str


class VLMCallLog(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    endpoint: str
    model: str
    latency_ms: int
    success: bool
    error: Optional[str] = None