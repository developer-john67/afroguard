import os
import uuid
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException, Depends, Form, File, UploadFile
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

from server.db import (
    init_db, verify_chain, get_scan_history, get_distinct_clients_for_serial,
    log_vlm_call, save_diagnosis, get_diagnosis, record_scan_event,
    claim_product_code, register_product_code, get_conn,
)
from server.schemas import (
    HealthResponse, PublicKeysResponse, PublicKeyEntry,
    DiagnoseResponse, VerifyCodeRequest, VerifyCodeResponse, ProductInfo,
    VerifyLabelResponse, VLMFieldExtraction,
    IssueDemoCodeRequest, IssueDemoCodeResponse, DecodeQrResponse,
)
from server.provenance import parse_code, verify_signature, compute_verdict, ProvenancePayload, build_qr_code
from server.diagnose import diagnose_image
from server.label_check import verify_label_image
from server.vlm import vlm_json

DEMO_MODE = os.getenv("DEMO_MODE", "0") == "1"
HOST = os.getenv("HOST", "https://agroguard.example.com")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="AgroGuard", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

WEB_DIR = Path(__file__).parent.parent / "web"
app.mount("/app", StaticFiles(directory=WEB_DIR, html=True), name="web")


@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse()


@app.get("/registry/public-keys", response_model=PublicKeysResponse)
async def public_keys():
    import sqlite3
    from server.db import get_conn
    with get_conn() as conn:
        rows = conn.execute("SELECT manufacturer_id, public_key FROM manufacturers").fetchall()
        return PublicKeysResponse(keys=[PublicKeyEntry(manufacturer_id=r["manufacturer_id"], public_key=r["public_key"]) for r in rows])


@app.post("/diagnose", response_model=DiagnoseResponse)
async def diagnose(
    image: UploadFile = File(...),
    lang: str = Form("en"),
):
    if image.size and image.size > 8 * 1024 * 1024:
        raise HTTPException(413, "Image too large (max 8MB)")
    content = await image.read()
    try:
        result = await run_in_threadpool(diagnose_image, content, lang)
        save_diagnosis(
            str(result.diagnosis_id),
            result.crop or "",
            result.top_condition or "",
            result.recommended_ingredient_classes,
            result.status,
        )
        return result
    except Exception as e:
        raise HTTPException(500, f"Diagnosis failed: {e}")


@app.post("/verify-code", response_model=VerifyCodeResponse)
async def verify_code(req: VerifyCodeRequest):
    parsed = parse_code(req.code)
    if not parsed:
        return VerifyCodeResponse(
            verdict="UNVERIFIABLE",
            reason_code="MALFORMED",
            reason_human="The QR code format is invalid.",
            product=ProductInfo(name="", manufacturer="", batch="", expiry="", active_ingredient_class=""),
            scan_count=0,
            matches_diagnosis=False,
            diagnosis_match_note="",
        )
    import sqlite3
    from server.db import get_conn
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM manufacturers WHERE manufacturer_id = ?", (parsed.manufacturer_id,)
        ).fetchone()
        if not row:
            return VerifyCodeResponse(
                verdict="FORGED",
                reason_code="UNKNOWN_KEY",
                reason_human="The manufacturer key is not recognized.",
                product=ProductInfo(name="", manufacturer="", batch="", expiry="", active_ingredient_class=""),
                scan_count=0,
                matches_diagnosis=False,
                diagnosis_match_note="",
            )
        public_key = row["public_key"]
        manufacturer_name = row["name"]

        prod_row = conn.execute(
            "SELECT * FROM products WHERE product_id = ?", (parsed.product_id,)
        ).fetchone()
        if not prod_row:
            return VerifyCodeResponse(
                verdict="UNVERIFIABLE",
                reason_code="MALFORMED",
                reason_human="Product not found in registry.",
                product=ProductInfo(name="", manufacturer="", batch="", expiry="", active_ingredient_class=""),
                scan_count=0,
                matches_diagnosis=False,
                diagnosis_match_note="",
            )

    sig_valid = verify_signature(parsed, public_key)
    scans = get_scan_history(parsed.serial)
    distinct_clients = get_distinct_clients_for_serial(parsed.serial)

    first_claim = False
    if sig_valid and prod_row:
        first_claim = claim_product_code(parsed.serial, req.client_id)
        if not first_claim and not scans:
            scans = [{"client_id": "another-client"}]
            distinct_clients = max(distinct_clients, 1)

    verdict, reason_code, reason_human = compute_verdict(
        parsed, sig_valid, dict(prod_row), scans, distinct_clients, req.client_id
    )

    record = record_scan_event(parsed.serial, req.client_id, verdict, reason_code, str(req.diagnosis_id) if req.diagnosis_id else None)

    match_diag = False
    match_note = ""
    if req.diagnosis_id:
        diag = get_diagnosis(str(req.diagnosis_id))
        if diag:
            recommended = diag["recommended_ingredient_classes"]
            product_class = prod_row["active_ingredient_class"]
            match_diag = product_class in recommended
            if match_diag:
                match_note = f"Genuine product. The {product_class} class matches the recommended treatment for {diag['top_condition']}."
            else:
                match_note = f"Genuine product, but this is a {product_class} and your crop shows signs of {diag['top_condition']} (recommended: {', '.join(recommended)})."

    return VerifyCodeResponse(
        verdict=verdict,
        reason_code=reason_code,
        reason_human=reason_human,
        product=ProductInfo(
            name=prod_row["name"],
            manufacturer=manufacturer_name,
            batch=prod_row["batch"],
            expiry=prod_row["expiry"],
            active_ingredient_class=prod_row["active_ingredient_class"],
        ),
        scan_count=len(scans) + 1,
        matches_diagnosis=match_diag,
        diagnosis_match_note=match_note,
    )


@app.post("/admin/issue-demo-codes", response_model=IssueDemoCodeResponse)
async def issue_demo_codes(req: IssueDemoCodeRequest):
    if not DEMO_MODE:
        raise HTTPException(403, "Demo issuance is disabled")

    with get_conn() as conn:
        row = conn.execute(
            "SELECT p.*, m.name as manufacturer_name FROM products p JOIN manufacturers m ON p.manufacturer_id = m.manufacturer_id WHERE p.product_id = ?",
            (req.product_id,),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Product not found in registry")

    private_path = Path(__file__).parent.parent / "keys" / f"{row['manufacturer_id']}_private.key"
    if not private_path.exists():
        raise HTTPException(500, "Manufacturer signing key is not available")

    private_key = private_path.read_text(encoding="utf-8").strip()
    codes = []
    qr_images = []
    import base64
    import io
    import qrcode
    for _ in range(req.count):
        payload = ProvenancePayload(
            manufacturer_id=row["manufacturer_id"],
            product_id=row["product_id"],
            batch=row["batch"],
            expiry=row["expiry"],
            serial=secrets.token_urlsafe(12),
        )
        register_product_code(payload.model_dump())
        code = build_qr_code(HOST.rstrip("/"), payload, private_key)
        codes.append(code)
        qr = qrcode.make(code)
        output = io.BytesIO()
        qr.save(output, format="PNG")
        qr_images.append("data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii"))
    return IssueDemoCodeResponse(codes=codes, qr_images=qr_images)


@app.post("/verify-label", response_model=VerifyLabelResponse)
async def verify_label(image: UploadFile = File(...)):
    if image.size and image.size > 8 * 1024 * 1024:
        raise HTTPException(413, "Image too large (max 8MB)")
    content = await image.read()
    result = await run_in_threadpool(verify_label_image, content)
    return result


@app.post("/decode-qr", response_model=DecodeQrResponse)
async def decode_qr(image: UploadFile = File(...)):
    content = await image.read()
    try:
        import cv2
        import numpy as np
        array = np.frombuffer(content, dtype=np.uint8)
        decoded, _, _ = cv2.QRCodeDetector().detectAndDecode(cv2.imdecode(array, cv2.IMREAD_COLOR))
    except Exception as exc:
        raise HTTPException(422, f"QR image could not be processed: {exc}")
    if not decoded:
        raise HTTPException(422, "No QR code found. Upload a clear, tightly cropped QR image.")
    return DecodeQrResponse(code=decoded)


@app.post("/admin/reset-demo")
async def reset_demo(request: Request):
    if not DEMO_MODE:
        raise HTTPException(403, "Demo mode not enabled")
    from tools.reset_demo import reset_demo
    reset_demo()
    return {"status": "ok", "message": "Demo state reset"}


@app.get("/", response_class=HTMLResponse)
async def root():
    return HTMLResponse(content=(WEB_DIR / "index.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))