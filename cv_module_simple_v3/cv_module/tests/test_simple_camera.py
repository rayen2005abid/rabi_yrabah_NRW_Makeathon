from collections import deque

import numpy as np

from src.simple_camera import average_probabilities, camera_decision


def test_average_probabilities_normalizes():
    history = deque([np.array([0.2, 0.8]), np.array([0.4, 0.6])], maxlen=4)
    result = average_probabilities(history)
    assert np.isclose(result.sum(), 1.0)
    assert np.allclose(result, [0.3, 0.7])


def test_empty_decision():
    state, label, confidence, _ = camera_decision(
        np.array([0.70, 0.10, 0.10, 0.05, 0.03, 0.02]),
        ["EMPTY", "A", "B", "C", "D", "E"],
        "EMPTY",
        0.60,
        0.65,
        0.08,
    )
    assert state == "EMPTY"
    assert label == "EMPTY"
    assert confidence == 0.70


def test_piece_decision():
    state, label, confidence, margin = camera_decision(
        np.array([0.05, 0.75, 0.08, 0.05, 0.04, 0.03]),
        ["EMPTY", "A", "B", "C", "D", "E"],
        "EMPTY",
        0.60,
        0.65,
        0.08,
    )
    assert state == "PIECE"
    assert label == "A"
    assert confidence == 0.75
    assert margin > 0.60


def test_uncertain_when_types_close():
    state, _, _, _ = camera_decision(
        np.array([0.02, 0.46, 0.43, 0.04, 0.03, 0.02]),
        ["EMPTY", "A", "B", "C", "D", "E"],
        "EMPTY",
        0.60,
        0.40,
        0.08,
    )
    assert state == "UNCERTAIN"
