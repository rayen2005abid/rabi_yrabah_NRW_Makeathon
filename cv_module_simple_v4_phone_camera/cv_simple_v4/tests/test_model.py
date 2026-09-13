import torch

from src.models import build_model, freeze_backbone, unfreeze_final_backbone_fraction


def test_model_output_shape_and_probability_sum() -> None:
    model = build_model("resnet18", num_classes=5, pretrained=False, dropout=0.1)
    model.eval()
    with torch.no_grad():
        logits = model(torch.randn(2, 3, 64, 64))
        probabilities = torch.softmax(logits, dim=1)
    assert logits.shape == (2, 5)
    assert probabilities.shape == (2, 5)
    assert torch.allclose(probabilities.sum(dim=1), torch.ones(2), atol=1e-5)


def test_freeze_and_partial_unfreeze() -> None:
    model = build_model("resnet18", num_classes=5, pretrained=False)
    freeze_backbone(model, "resnet18")
    assert any(parameter.requires_grad for parameter in model.fc.parameters())
    assert not all(parameter.requires_grad for parameter in model.parameters())
    unfreeze_final_backbone_fraction(model, "resnet18", 0.3)
    assert sum(parameter.requires_grad for parameter in model.parameters()) > sum(
        parameter.requires_grad for parameter in model.fc.parameters()
    )


def test_efficientnet_b2_output_shape_without_pretrained_download() -> None:
    model = build_model("efficientnet_b2", num_classes=5, pretrained=False, dropout=0.2)
    model.eval()
    with torch.no_grad():
        logits = model(torch.randn(1, 3, 96, 96))
    assert logits.shape == (1, 5)
