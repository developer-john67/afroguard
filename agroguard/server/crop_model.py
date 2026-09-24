import json
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
WEIGHTS_PATH = Path(os.getenv("CROP_MODEL_WEIGHTS", PROJECT_DIR / "models" / "crop_model_weights.pth"))
CLASS_NAMES_PATH = Path(os.getenv("CROP_MODEL_CLASSES", PROJECT_DIR / "models" / "crop_classes.json"))

_transform = transforms.Compose([
    transforms.Resize(256),
    transforms.CenterCrop(224),
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
])


@dataclass
class CropPrediction:
    crop: str
    confidence: float
    alternatives: List[dict]


@lru_cache(maxsize=1)
def _load_model():
    class_names = json.loads(CLASS_NAMES_PATH.read_text(encoding="utf-8"))
    model = models.resnet18(weights=None)
    model.fc = torch.nn.Linear(model.fc.in_features, len(class_names))
    model.load_state_dict(torch.load(WEIGHTS_PATH, map_location="cpu", weights_only=True))
    model.eval()
    return model, class_names


def predict_crop(image_bytes: bytes) -> CropPrediction:
    model, class_names = _load_model()
    with Image.open(BytesIO(image_bytes)) as image:
        tensor = _transform(image.convert("RGB")).unsqueeze(0)
    with torch.inference_mode():
        probabilities = torch.softmax(model(tensor), dim=1)[0]
        values, indices = torch.topk(probabilities, k=min(3, len(class_names)))
    predictions = [
        {"crop": class_names[int(index)], "confidence": round(float(value), 4)}
        for value, index in zip(values, indices)
    ]
    return CropPrediction(
        crop=predictions[0]["crop"],
        confidence=predictions[0]["confidence"],
        alternatives=predictions[1:],
    )
