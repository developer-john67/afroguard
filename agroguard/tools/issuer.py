import json
import base64
import secrets
import os
import argparse
from pathlib import Path

from nacl.signing import SigningKey, VerifyKey

from server.provenance import build_qr_code
from server.schemas import ProvenancePayload
from server.db import init_db, get_conn, register_product_code

KEYS_DIR = Path(__file__).parent.parent / "keys"
KEYS_DIR.mkdir(exist_ok=True)


def generate_keypair(manufacturer_id: str) -> tuple[str, str]:
    signing_key = SigningKey.generate()
    private_b64 = base64.urlsafe_b64encode(signing_key.encode()).decode().rstrip("=")
    public_b64 = base64.urlsafe_b64encode(signing_key.verify_key.encode()).decode().rstrip("=")

    (KEYS_DIR / f"{manufacturer_id}_private.key").write_text(private_b64)
    (KEYS_DIR / f"{manufacturer_id}_public.key").write_text(public_b64)

    return private_b64, public_b64


def load_keys(manufacturer_id: str) -> tuple[str, str]:
    private_path = KEYS_DIR / f"{manufacturer_id}_private.key"
    public_path = KEYS_DIR / f"{manufacturer_id}_public.key"
    if not private_path.exists() or not public_path.exists():
        return generate_keypair(manufacturer_id)
    return private_path.read_text().strip(), public_path.read_text().strip()


def issue_codes(
    manufacturer_id: str,
    manufacturer_name: str,
    product_id: str,
    product_name: str,
    batch: str,
    expiry: str,
    active_ingredient_class: str,
    registration_number: str,
    count: int,
    host: str,
):
    private_key, public_key = load_keys(manufacturer_id)

    with get_conn() as conn:
        conn.execute(
            "INSERT INTO manufacturers (manufacturer_id, name, public_key) VALUES (?, ?, ?) "
            "ON CONFLICT(manufacturer_id) DO UPDATE SET name=excluded.name, public_key=excluded.public_key",
            (manufacturer_id, manufacturer_name, public_key),
        )
        conn.execute(
            "INSERT OR IGNORE INTO products (product_id, manufacturer_id, name, active_ingredient_class, batch, expiry, registration_number) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (product_id, manufacturer_id, product_name, active_ingredient_class, batch, expiry, registration_number),
        )

    print(f"Manufacturer: {manufacturer_name} ({manufacturer_id})")
    print(f"Product: {product_name} ({product_id})")
    print(f"Batch: {batch}, Expiry: {expiry}")
    print(f"Public Key: {public_key}")
    print()

    for i in range(count):
        serial = secrets.token_urlsafe(12)
        payload = ProvenancePayload(
            manufacturer_id=manufacturer_id, product_id=product_id,
            batch=batch, expiry=expiry, serial=serial,
        )
        code = build_qr_code(host, payload, private_key)
        register_product_code(payload.model_dump())
        print(code)

    print()
    print(f"Issued {count} codes. Private key saved to {KEYS_DIR}/{manufacturer_id}_private.key")


def generate_printable_sheet(
    manufacturer_id: str,
    manufacturer_name: str,
    product_id: str,
    product_name: str,
    batch: str,
    expiry: str,
    codes: list[str],
    output_path: str,
):
    import qrcode
    from PIL import Image, ImageDraw, ImageFont

    codes_per_row = 3
    code_size = 300
    margin = 40
    label_height = 80

    rows = (len(codes) + codes_per_row - 1) // codes_per_row
    sheet_width = codes_per_row * code_size + (codes_per_row + 1) * margin
    sheet_height = rows * (code_size + label_height) + (rows + 1) * margin

    img = Image.new("RGB", (sheet_width, sheet_height), "white")
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("arial.ttf", 20)
        small_font = ImageFont.truetype("arial.ttf", 14)
    except:
        font = ImageFont.load_default()
        small_font = ImageFont.load_default()

    for idx, code in enumerate(codes):
        row = idx // codes_per_row
        col = idx % codes_per_row
        x = margin + col * (code_size + margin)
        y = margin + row * (code_size + label_height + margin)

        qr = qrcode.QRCode(version=5, box_size=6, border=2)
        qr.add_data(code)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white").resize((code_size, code_size))
        img.paste(qr_img, (x, y))

        draw.text((x + code_size // 2, y + code_size + 10), f"{product_name}", fill="black", font=font, anchor="mt")
        draw.text((x + code_size // 2, y + code_size + 35), f"Batch: {batch}  Expiry: {expiry}", fill="black", font=small_font, anchor="mt")
        draw.text((x + code_size // 2, y + code_size + 55), f"Serial: {code.split('.')[-1][:12]}...", fill="black", font=small_font, anchor="mt")

    img.save(output_path, dpi=(300, 300))
    print(f"Printable sheet saved to {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Issue signed QR codes for agro-input products")
    parser.add_argument("--manufacturer-id", required=True)
    parser.add_argument("--manufacturer-name", required=True)
    parser.add_argument("--product-id", required=True)
    parser.add_argument("--product-name", required=True)
    parser.add_argument("--batch", required=True)
    parser.add_argument("--expiry", required=True)
    parser.add_argument("--active-ingredient-class", required=True)
    parser.add_argument("--registration-number", required=True)
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--host", default=os.getenv("HOST", "https://agroguard.example.com"))
    parser.add_argument("--output", help="Output printable sheet (PNG)")

    args = parser.parse_args()

    init_db()

    private_key, public_key = load_keys(args.manufacturer_id)

    with get_conn() as conn:
        conn.execute(
            "INSERT INTO manufacturers (manufacturer_id, name, public_key) VALUES (?, ?, ?) "
            "ON CONFLICT(manufacturer_id) DO UPDATE SET name=excluded.name, public_key=excluded.public_key",
            (args.manufacturer_id, args.manufacturer_name, public_key),
        )
        conn.execute(
            "INSERT OR IGNORE INTO products (product_id, manufacturer_id, name, active_ingredient_class, batch, expiry, registration_number) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (args.product_id, args.manufacturer_id, args.product_name, args.active_ingredient_class, args.batch, args.expiry, args.registration_number),
        )

    codes = []
    for i in range(args.count):
        serial = secrets.token_urlsafe(12)
        payload = ProvenancePayload(
            manufacturer_id=args.manufacturer_id, product_id=args.product_id,
            batch=args.batch, expiry=args.expiry, serial=serial,
        )
        code = build_qr_code(args.host, payload, private_key)
        register_product_code(payload.model_dump())
        codes.append(code)
        print(code)

    if args.output:
        generate_printable_sheet(
            args.manufacturer_id, args.manufacturer_name, args.product_id,
            args.product_name, args.batch, args.expiry, codes, args.output
        )