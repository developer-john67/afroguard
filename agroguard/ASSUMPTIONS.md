# Assumptions

1. **Qwen Endpoint**: OpenAI-compatible `/v1/chat/completions` with vision support. Model name via `QWEN_VL_MODEL` env var.
2. **Crops**: Three crops — maize, tomato, cassava (standard FAO/CABI coverage).
3. **Host URL**: `HOST` env var is the public HTTPS URL (e.g., `https://agroguard.example.com`) used in QR codes.
4. **QR Payload**: Compact JSON array `[manufacturer_id, product_id, batch, expiry, serial]` → base64url encoded. Signature is Ed25519 over the payload bytes, also base64url. Full code: `https://<HOST>/v/<payload>.<sig>`.
5. **Clone Threshold**: `CLONE_DISTINCT_CLIENTS=2` (configurable). A serial scanned by ≥2 distinct `client_id`s triggers `CLONE_SUSPECTED`.
6. **No Auth**: No user accounts, no admin UI beyond `DEMO_MODE=1` reset endpoint.
7. **Client-side Verification**: Vendored `tweetnacl.min.js` for Ed25519 signature verification in browser. Public keys from `/registry/public-keys`.
8. **Languages**: English (en), Swahili (sw), French (fr), Hindi (hi) for UI strings and Qwen-written explanations.
9. **Image Handling**: Client resizes to max 1024px JPEG before upload. Server validates: type, size ≤8MB, decodable.
10. **VLM Timeout**: 20s per call. At 20s, friendly failure state shown to user.
11. **Database**: SQLite (stdlib `sqlite3`), single file `agroguard.db`.
12. **Hash Chain**: `scan_events` table with `prev_hash` and `hash = sha256(prev_hash || event_json)`. `verify_chain()` validates integrity.
13. **KB Source**: `kb/diseases.json` and `kb/products.json` are curated from public FAO/CABI Plantwise knowledge. Every disease entry has `"needs_expert_review": true`.
14. **Fictional Brands Only**: All manufacturers and product names are fictional.
15. **REPLAY_MODE**: When `REPLAY_MODE=1`, VLM calls serve cached responses from `eval/replay/` keyed by image SHA256. Logged loudly.
16. **QR Code Libraries**: `BarcodeDetector` API (native) with `jsQR` fallback (vendored locally).
17. **Deployment**: Docker + Caddy for HTTPS, or ngrok tunnel for demo.