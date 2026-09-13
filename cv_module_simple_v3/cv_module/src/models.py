from __future__ import annotations

import math

import torch
import torch.nn as nn
import torch.nn.functional as F
from torchvision import models

SUPPORTED_ARCHITECTURES = {
    "mobilenet_v3_large",
    "mobilenet_v3_small",
    "efficientnet_b0",
    "efficientnet_b2",
    "resnet18",
}


def build_model(
    architecture: str,
    num_classes: int,
    pretrained: bool = True,
    dropout: float = 0.2,
) -> nn.Module:
    """Build a supported torchvision classifier with a task-specific output head."""
    architecture = architecture.lower()
    if architecture not in SUPPORTED_ARCHITECTURES:
        raise ValueError(
            f"Unsupported architecture '{architecture}'. Supported: {sorted(SUPPORTED_ARCHITECTURES)}"
        )

    if architecture == "mobilenet_v3_large":
        weights = models.MobileNet_V3_Large_Weights.DEFAULT if pretrained else None
        model = models.mobilenet_v3_large(weights=weights)
        in_features = model.classifier[-1].in_features
        model.classifier[2] = nn.Dropout(p=dropout, inplace=True)
        model.classifier[-1] = nn.Linear(in_features, num_classes)
    elif architecture == "mobilenet_v3_small":
        weights = models.MobileNet_V3_Small_Weights.DEFAULT if pretrained else None
        model = models.mobilenet_v3_small(weights=weights)
        in_features = model.classifier[-1].in_features
        model.classifier[2] = nn.Dropout(p=dropout, inplace=True)
        model.classifier[-1] = nn.Linear(in_features, num_classes)
    elif architecture == "efficientnet_b0":
        weights = models.EfficientNet_B0_Weights.DEFAULT if pretrained else None
        model = models.efficientnet_b0(weights=weights)
        in_features = model.classifier[-1].in_features
        model.classifier[0] = nn.Dropout(p=dropout, inplace=True)
        model.classifier[-1] = nn.Linear(in_features, num_classes)
    elif architecture == "efficientnet_b2":
        weights = models.EfficientNet_B2_Weights.DEFAULT if pretrained else None
        model = models.efficientnet_b2(weights=weights)
        in_features = model.classifier[-1].in_features
        model.classifier[0] = nn.Dropout(p=dropout, inplace=True)
        model.classifier[-1] = nn.Linear(in_features, num_classes)
    else:
        weights = models.ResNet18_Weights.DEFAULT if pretrained else None
        model = models.resnet18(weights=weights)
        in_features = model.fc.in_features
        model.fc = nn.Sequential(nn.Dropout(p=dropout), nn.Linear(in_features, num_classes))
    return model


def _head_modules(model: nn.Module, architecture: str) -> list[nn.Module]:
    if architecture.startswith("mobilenet_v3") or architecture.startswith("efficientnet_b"):
        return [model.classifier]
    if architecture == "resnet18":
        return [model.fc]
    raise ValueError(architecture)


def _backbone_blocks(model: nn.Module, architecture: str) -> list[nn.Module]:
    if architecture.startswith("mobilenet_v3") or architecture.startswith("efficientnet_b"):
        return list(model.features.children())
    if architecture == "resnet18":
        return [model.conv1, model.bn1, model.layer1, model.layer2, model.layer3, model.layer4]
    raise ValueError(architecture)


def freeze_backbone(model: nn.Module, architecture: str) -> None:
    """Freeze all model parameters, then make only the classification head trainable."""
    for parameter in model.parameters():
        parameter.requires_grad = False
    for module in _head_modules(model, architecture):
        for parameter in module.parameters():
            parameter.requires_grad = True


def unfreeze_final_backbone_fraction(model: nn.Module, architecture: str, fraction: float = 0.30) -> None:
    """Unfreeze only the final fraction of backbone blocks plus the classification head."""
    if not 0 < fraction <= 1:
        raise ValueError("finetune fraction must be in (0, 1]")
    freeze_backbone(model, architecture)
    blocks = _backbone_blocks(model, architecture)
    count = max(1, math.ceil(len(blocks) * fraction))
    for block in blocks[-count:]:
        for parameter in block.parameters():
            parameter.requires_grad = True


def extract_feature_embedding(model: nn.Module, architecture: str, inputs: torch.Tensor) -> torch.Tensor:
    """Return the deep feature vector immediately before the final class layer.

    These embeddings are used to construct one visual prototype per core type from
    TRAIN originals only.  Runtime prototype matching is deliberately a secondary
    signal; the main classifier remains the trained softmax head.
    """
    architecture = architecture.lower()
    if architecture.startswith("mobilenet_v3") or architecture.startswith("efficientnet_b"):
        x = model.features(inputs)
        x = model.avgpool(x)
        x = torch.flatten(x, 1)
        # Keep every classifier operation except the final class projection.
        x = model.classifier[:-1](x)
    elif architecture == "resnet18":
        x = model.conv1(inputs)
        x = model.bn1(x)
        x = model.relu(x)
        x = model.maxpool(x)
        x = model.layer1(x)
        x = model.layer2(x)
        x = model.layer3(x)
        x = model.layer4(x)
        x = model.avgpool(x)
        x = torch.flatten(x, 1)
        if isinstance(model.fc, nn.Sequential) and len(model.fc) > 1:
            x = model.fc[:-1](x)
    else:
        raise ValueError(f"Unsupported architecture for embedding extraction: {architecture}")
    return F.normalize(x, p=2, dim=1)


def gradcam_target_layer(model: nn.Module, architecture: str) -> nn.Module:
    """Return the last spatial feature block suitable for Grad-CAM."""
    architecture = architecture.lower()
    if architecture.startswith("mobilenet_v3") or architecture.startswith("efficientnet_b"):
        return model.features[-1]
    if architecture == "resnet18":
        return model.layer4[-1]
    raise ValueError(f"Unsupported architecture for Grad-CAM: {architecture}")
