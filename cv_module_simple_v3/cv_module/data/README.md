# Dataset layout for Simple V3

Simple V3 intentionally uses one extra operational class named `EMPTY`.
It is not a core type; it means there is no piece inside the fixed green camera ROI.

Your dataset must therefore contain six folders:

```text
data/raw/
  EMPTY/
  <CORE_TYPE_1>/
  <CORE_TYPE_2>/
  <CORE_TYPE_3>/
  <CORE_TYPE_4>/
  <CORE_TYPE_5>/
```

Do not rename your five real core classes to generic names. The folder names become the model labels.

For the best live-camera accuracy, capture new images with `python -m src.capture_roi_dataset` so training images and live inference use the exact same green region and camera perspective.
