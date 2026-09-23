import sqlite3
import hashlib
import json
import os
from contextlib import contextmanager
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path

DB_PATH = os.getenv("DATABASE_PATH", "agroguard.db")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db():
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS manufacturers (
            manufacturer_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            public_key TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS products (
            product_id TEXT PRIMARY KEY,
            manufacturer_id TEXT NOT NULL,
            name TEXT NOT NULL,
            active_ingredient_class TEXT NOT NULL,
            batch TEXT NOT NULL,
            expiry TEXT NOT NULL,
            registration_number TEXT,
            recalled BOOLEAN DEFAULT FALSE,
            FOREIGN KEY (manufacturer_id) REFERENCES manufacturers(manufacturer_id)
        );

        CREATE TABLE IF NOT EXISTS scan_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            serial TEXT NOT NULL,
            client_id TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            verdict TEXT NOT NULL,
            reason_code TEXT NOT NULL,
            diagnosis_id TEXT,
            prev_hash TEXT NOT NULL,
            hash TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS product_codes (
            serial TEXT PRIMARY KEY,
            manufacturer_id TEXT NOT NULL,
            product_id TEXT NOT NULL,
            batch TEXT NOT NULL,
            expiry TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'ISSUED',
            redeemed_at TIMESTAMP,
            first_client_id TEXT
        );

        CREATE TABLE IF NOT EXISTS vlm_calls (
            id TEXT PRIMARY KEY,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            endpoint TEXT NOT NULL,
            model TEXT NOT NULL,
            latency_ms INTEGER NOT NULL,
            success BOOLEAN NOT NULL,
            error TEXT
        );

        CREATE TABLE IF NOT EXISTS diagnoses (
            diagnosis_id TEXT PRIMARY KEY,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            crop TEXT,
            top_condition TEXT,
            recommended_ingredient_classes TEXT,
            status TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_scan_serial ON scan_events(serial);
        CREATE INDEX IF NOT EXISTS idx_scan_client ON scan_events(client_id);
        """)


def get_last_hash(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT hash FROM scan_events ORDER BY id DESC LIMIT 1").fetchone()
    return row["hash"] if row else "0" * 64


def compute_hash(prev_hash: str, event_json: str) -> str:
    return hashlib.sha256((prev_hash + event_json).encode()).hexdigest()


def record_scan_event(
    serial: str,
    client_id: str,
    verdict: str,
    reason_code: str,
    diagnosis_id: Optional[str] = None
) -> Dict[str, Any]:
    with db() as conn:
        prev_hash = get_last_hash(conn)
        event_data = {
            "serial": serial,
            "client_id": client_id,
            "timestamp": datetime.utcnow().isoformat(),
            "verdict": verdict,
            "reason_code": reason_code,
            "diagnosis_id": diagnosis_id,
        }
        event_json = json.dumps(event_data, sort_keys=True)
        hash_val = compute_hash(prev_hash, event_json)
        conn.execute(
            "INSERT INTO scan_events (serial, client_id, verdict, reason_code, diagnosis_id, prev_hash, hash) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (serial, client_id, verdict, reason_code, diagnosis_id, prev_hash, hash_val),
        )
        return {**event_data, "prev_hash": prev_hash, "hash": hash_val}


def get_scan_history(serial: str) -> List[Dict[str, Any]]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM scan_events WHERE serial = ? ORDER BY id", (serial,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_distinct_clients_for_serial(serial: str) -> int:
    with db() as conn:
        row = conn.execute(
            "SELECT COUNT(DISTINCT client_id) as cnt FROM scan_events WHERE serial = ?",
            (serial,),
        ).fetchone()
        return row["cnt"] if row else 0


def register_product_code(payload: Dict[str, Any]) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO product_codes (serial, manufacturer_id, product_id, batch, expiry) VALUES (?, ?, ?, ?, ?)",
            (payload["serial"], payload["manufacturer_id"], payload["product_id"], payload["batch"], payload["expiry"]),
        )


def claim_product_code(serial: str, client_id: str) -> bool:
    with db() as conn:
        cursor = conn.execute(
            "UPDATE product_codes SET status = 'REDEEMED', redeemed_at = CURRENT_TIMESTAMP, first_client_id = ? WHERE serial = ? AND status = 'ISSUED'",
            (client_id, serial),
        )
        return cursor.rowcount == 1


def verify_chain() -> bool:
    with db() as conn:
        rows = conn.execute("SELECT * FROM scan_events ORDER BY id").fetchall()
        prev_hash = "0" * 64
        for row in rows:
            event_data = {
                "serial": row["serial"],
                "client_id": row["client_id"],
                "timestamp": row["timestamp"],
                "verdict": row["verdict"],
                "reason_code": row["reason_code"],
                "diagnosis_id": row["diagnosis_id"],
            }
            event_json = json.dumps(event_data, sort_keys=True)
            expected_hash = compute_hash(prev_hash, event_json)
            if row["hash"] != expected_hash or row["prev_hash"] != prev_hash:
                return False
            prev_hash = row["hash"]
        return True


def log_vlm_call(call_id: str, endpoint: str, model: str, latency_ms: int, success: bool, error: Optional[str] = None):
    with db() as conn:
        conn.execute(
            "INSERT INTO vlm_calls (id, endpoint, model, latency_ms, success, error) VALUES (?, ?, ?, ?, ?, ?)",
            (call_id, endpoint, model, latency_ms, success, error),
        )


def save_diagnosis(diagnosis_id: str, crop: str, top_condition: str, recommended_ingredient_classes: List[str], status: str):
    with db() as conn:
        conn.execute(
            "INSERT INTO diagnoses (diagnosis_id, crop, top_condition, recommended_ingredient_classes, status) VALUES (?, ?, ?, ?, ?)",
            (diagnosis_id, crop, top_condition, json.dumps(recommended_ingredient_classes), status),
        )


def get_diagnosis(diagnosis_id: str) -> Optional[Dict[str, Any]]:
    with db() as conn:
        row = conn.execute("SELECT * FROM diagnoses WHERE diagnosis_id = ?", (diagnosis_id,)).fetchone()
        if row:
            d = dict(row)
            d["recommended_ingredient_classes"] = json.loads(d["recommended_ingredient_classes"])
            return d
        return None