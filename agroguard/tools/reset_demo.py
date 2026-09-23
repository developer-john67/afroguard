import os
import sqlite3
import json
from pathlib import Path

DB_PATH = os.getenv("DATABASE_PATH", "agroguard.db")
KB_DIR = Path(__file__).parent.parent / "kb"


def reset_demo():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    import server.db
    server.db.init_db()

    with sqlite3.connect(DB_PATH) as conn:
        diseases = json.load(open(KB_DIR / "diseases.json"))
        products = json.load(open(KB_DIR / "products.json"))

        manufacturers = {}
        for p in products:
            manufacturers[p["manufacturer_id"]] = p["manufacturer"]

        for mfr_id, mfr_name in manufacturers.items():
            conn.execute(
                "INSERT OR IGNORE INTO manufacturers (manufacturer_id, name, public_key) VALUES (?, ?, ?)",
                (mfr_id, mfr_name, "PLACEHOLDER_KEY_WILL_BE_SET_BY_ISSUER"),
            )

        for p in products:
            conn.execute(
                "INSERT OR IGNORE INTO products (product_id, manufacturer_id, name, active_ingredient_class, batch, expiry, registration_number) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (p["product_id"], p["manufacturer_id"], p["name"], p["active_ingredient_class"], p["batch"], p["expiry"], p.get("registration_number")),
            )

        conn.commit()

    print("Demo database reset complete.")
    print("Run tools/issuer.py to generate keys and issue QR codes for each product.")


if __name__ == "__main__":
    reset_demo()