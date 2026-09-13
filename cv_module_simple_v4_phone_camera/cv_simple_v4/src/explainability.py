from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
import torch
import torch.nn.functional as F
from torch import nn


@dataclass
class AttentionRegion:
    """One high-attention rectangular region in image coordinates."""

    x: int
    y: int
    width: int
    height: int
    strength: float


class GradCAM:
    """Small Grad-CAM implementation used to visualize class-specific evidence."""

    def __init__(self, model: nn.Module, target_layer: nn.Module) -> None:
        self.model = model
        self.target_layer = target_layer
        self._activations: torch.Tensor | None = None
        self._gradients: torch.Tensor | None = None
        self._handle = target_layer.register_forward_hook(self._forward_hook)

    def _forward_hook(self, _module: nn.Module, _inputs: tuple, output: torch.Tensor) -> None:
        self._activations = output
        if output.requires_grad:
            output.register_hook(self._save_gradient)

    def _save_gradient(self, gradient: torch.Tensor) -> None:
        self._gradients = gradient

    def close(self) -> None:
        self._handle.remove()

    def generate(self, inputs: torch.Tensor, class_index: int | None = None) -> tuple[np.ndarray, int, torch.Tensor]:
        """Return normalized CAM, target class index, and logits for one input image."""
        if inputs.ndim != 4 or inputs.shape[0] != 1:
            raise ValueError("GradCAM expects a single BCHW input tensor")
        self._activations = None
        self._gradients = None
        self.model.zero_grad(set_to_none=True)
        logits = self.model(inputs)
        target = int(logits.argmax(dim=1).item()) if class_index is None else int(class_index)
        logits[0, target].backward()
        if self._activations is None or self._gradients is None:
            raise RuntimeError("Could not capture Grad-CAM activations/gradients")

        activations = self._activations.detach()
        gradients = self._gradients.detach()
        weights = gradients.mean(dim=(2, 3), keepdim=True)
        raw_cam = (weights * activations).sum(dim=1, keepdim=True)
        cam = torch.relu(raw_cam)
        # Very weak/random checkpoints can occasionally have only negative class
        # contributions at the final feature block. For operator diagnostics, use
        # absolute contribution as a fallback instead of displaying an empty map.
        if float(cam.max()) <= 1e-12:
            cam = raw_cam.abs()
        cam = F.interpolate(cam, size=inputs.shape[-2:], mode="bilinear", align_corners=False)
        cam = cam[0, 0]
        cam -= cam.min()
        maximum = cam.max()
        if float(maximum) > 1e-12:
            cam = cam / maximum
        return cam.cpu().numpy().astype(np.float32), target, logits.detach()



def attention_to_original_geometry(attention: np.ndarray, image_width: int, image_height: int) -> np.ndarray:
    """Undo PadToSquare geometry, then resize attention to the original crop.

    Validation/inference first pad the shorter side to a square. Grad-CAM therefore
    lives in square-input coordinates. Removing that padding before display keeps
    the green detail boxes aligned with the actual camera crop.
    """
    heat = attention.astype(np.float32)
    side_h, side_w = heat.shape[:2]
    if image_width > image_height:
        content_fraction = image_height / max(image_width, 1)
        content_h = max(1, int(round(side_h * content_fraction)))
        y1 = max(0, (side_h - content_h) // 2)
        heat = heat[y1 : y1 + content_h, :]
    elif image_height > image_width:
        content_fraction = image_width / max(image_height, 1)
        content_w = max(1, int(round(side_w * content_fraction)))
        x1 = max(0, (side_w - content_w) // 2)
        heat = heat[:, x1 : x1 + content_w]
    return cv2.resize(heat, (int(image_width), int(image_height)), interpolation=cv2.INTER_LINEAR)


def resize_attention(attention: np.ndarray, width: int, height: int) -> np.ndarray:
    """Resize a normalized attention map to display-image dimensions."""
    resized = cv2.resize(attention.astype(np.float32), (int(width), int(height)), interpolation=cv2.INTER_LINEAR)
    return np.clip(resized, 0.0, 1.0)


def green_attention_overlay(
    image_bgr: np.ndarray,
    attention: np.ndarray,
    threshold: float = 0.55,
    alpha: float = 0.42,
) -> np.ndarray:
    """Overlay only high-evidence regions in green, keeping the original image visible."""
    if image_bgr.size == 0:
        return image_bgr.copy()
    height, width = image_bgr.shape[:2]
    heat = attention_to_original_geometry(attention, width, height)
    strength = np.clip((heat - float(threshold)) / max(1e-6, 1.0 - float(threshold)), 0.0, 1.0)
    overlay = image_bgr.astype(np.float32).copy()
    green = np.zeros_like(overlay)
    green[..., 1] = 255.0
    mix = (float(alpha) * strength)[..., None]
    overlay = overlay * (1.0 - mix) + green * mix
    return np.clip(overlay, 0, 255).astype(np.uint8)


def salient_regions(
    attention: np.ndarray,
    image_width: int,
    image_height: int,
    threshold: float = 0.62,
    min_area_ratio: float = 0.008,
    max_regions: int = 3,
) -> list[AttentionRegion]:
    """Extract a few strongest connected evidence regions from a Grad-CAM map."""
    heat = attention_to_original_geometry(attention, image_width, image_height)
    mask = np.where(heat >= float(threshold), 255, 0).astype(np.uint8)
    kernel = np.ones((5, 5), dtype=np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    total_area = float(image_width * image_height)
    candidates: list[AttentionRegion] = []
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area / max(total_area, 1.0) < float(min_area_ratio):
            continue
        x, y, width, height = cv2.boundingRect(contour)
        roi = heat[y : y + height, x : x + width]
        strength = float(roi.mean()) if roi.size else 0.0
        candidates.append(AttentionRegion(x, y, width, height, strength))
    candidates.sort(key=lambda item: item.strength * item.width * item.height, reverse=True)
    return candidates[: max(1, int(max_regions))]


def draw_salient_regions(image_bgr: np.ndarray, regions: list[AttentionRegion]) -> np.ndarray:
    """Draw the model's strongest class-specific details using green rectangles."""
    output = image_bgr.copy()
    for index, region in enumerate(regions, start=1):
        x1, y1 = region.x, region.y
        x2, y2 = x1 + region.width, y1 + region.height
        cv2.rectangle(output, (x1, y1), (x2, y2), (40, 235, 40), 2)
        cv2.putText(
            output,
            f"detail {index}",
            (x1, max(18, y1 - 5)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            (40, 235, 40),
            1,
            cv2.LINE_AA,
        )
    return output
