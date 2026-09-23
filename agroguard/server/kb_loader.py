import json
import os
from typing import Any, Dict, List, Optional

KB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "kb")


def load_diseases() -> List[Dict[str, Any]]:
    path = os.path.join(KB_DIR, "diseases.json")
    with open(path) as f:
        return json.load(f)


def load_products() -> List[Dict[str, Any]]:
    path = os.path.join(KB_DIR, "products.json")
    with open(path) as f:
        return json.load(f)


def get_disease_entry(condition_id: str) -> Optional[Dict[str, Any]]:
    diseases = load_diseases()
    for d in diseases:
        if d["id"] == condition_id:
            return d
    return None


def get_recommended_classes(condition_id: str) -> List[str]:
    entry = get_disease_entry(condition_id)
    return entry.get("recommended_ingredient_classes", []) if entry else []