import os
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import List

import torch
from PIL import Image
from torchvision import models, transforms


PROJECT_DIR = Path(__file__).resolve().parent.parent
WEIGHTS_PATH = Path(os.getenv("PLANT_MODEL_WEIGHTS", PROJECT_DIR / "plantvillage_model_weights.pth"))
CLASS_NAMES_PATH = Path(os.getenv("PLANT_MODEL_CLASSES", PROJECT_DIR / "models" / "plantvillage_classes.json"))
CONFIDENCE_THRESHOLD = float(os.getenv("PLANT_MODEL_CONFIDENCE", "0.70"))


@dataclass
class PlantPrediction:
    class_name: str
    confidence: float
    alternatives: List[dict]


@lru_cache(maxsize=1)
def _load_model():
    if not WEIGHTS_PATH.exists():
        raise FileNotFoundError(f"Plant model weights not found: {WEIGHTS_PATH}")
    if not CLASS_NAMES_PATH.exists():
        raise FileNotFoundError(f"Plant model class list not found: {CLASS_NAMES_PATH}")

    import json
    class_names = json.loads(CLASS_NAMES_PATH.read_text(encoding="utf-8"))
    model = models.resnet18(weights=None)
    model.fc = torch.nn.Linear(model.fc.in_features, len(class_names))
    checkpoint = torch.load(WEIGHTS_PATH, map_location="cpu", weights_only=True)
    model.load_state_dict(checkpoint)
    model.eval()
    return model, class_names


_transform = transforms.Compose([
    transforms.Resize(256),
    transforms.CenterCrop(224),
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
])


def predict(image_bytes: bytes) -> PlantPrediction:
    model, class_names = _load_model()
    with Image.open(BytesIO(image_bytes)) as image:
        image = image.convert("RGB")
        tensor = _transform(image).unsqueeze(0)

    with torch.inference_mode():
        probabilities = torch.softmax(model(tensor), dim=1)[0]
        values, indices = torch.topk(probabilities, k=min(3, len(class_names)))

    predictions = [
        {"class_name": class_names[int(index)], "confidence": round(float(value), 4)}
        for value, index in zip(values, indices)
    ]
    top = predictions[0]
    return PlantPrediction(
        class_name=top["class_name"],
        confidence=top["confidence"],
        alternatives=predictions[1:],
    )
