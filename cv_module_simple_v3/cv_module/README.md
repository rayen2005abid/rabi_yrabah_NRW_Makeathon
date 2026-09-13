# Smart Core Warehouse — CV Module Simple V3

This version deliberately removes the fragile automatic foreground detector and background calibration.
For a fixed industrial camera, the simplest reliable workflow is usually a **fixed working area**.

## Simple idea

The camera always draws one green rectangle. Put one core completely inside it.
The same classifier predicts six labels:

- your five real core types;
- `EMPTY` = no piece is present in the green rectangle.

So there is no separate object-detection model, no background calibration, and no moving bounding box.

```text
camera
  -> fixed green ROI
  -> classifier
      -> EMPTY       => NO PIECE
      -> TYPE_1..5   => PIECE + TYPE
```

This is easier to debug and is often more reliable than trying to detect arbitrary objects with only ~50 real photographs.

## 1. Python

Use Python 3.12 on Windows.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 2. Capture EMPTY images

Keep the green rectangle empty and save genuinely different examples:

```powershell
.\.venv\Scripts\python.exe -m src.capture_roi_dataset --class-name EMPTY
```

Press `SPACE` or `S` to save. Aim for about 30-50 useful EMPTY images at first.

## 3. Capture each real core type with the SAME camera

Example:

```powershell
.\.venv\Scripts\python.exe -m src.capture_roi_dataset --class-name "YOUR_REAL_TYPE_A"
```

Repeat for all five type-folder names. Move/rotate the physical piece between captures. Do not create 50 nearly identical consecutive frames.

A practical first target is **30-50 genuine camera images per class**. More is better, especially for currently underrepresented classes.

## 4. Dataset structure

```text
data/raw/
  EMPTY/
  YOUR_REAL_TYPE_A/
  YOUR_REAL_TYPE_B/
  YOUR_REAL_TYPE_C/
  YOUR_REAL_TYPE_D/
  YOUR_REAL_TYPE_E/
```

`EMPTY` is the only reserved folder name. The five real type names are still discovered automatically.

## 5. Inspect

```powershell
.\.venv\Scripts\python.exe -m src.inspect_dataset --config configs/default.yaml
```

The simple model expects six folders: five core types + `EMPTY`.

## 6. Preview augmentation

```powershell
.\.venv\Scripts\python.exe -m src.augmentations --preview --config configs/default.yaml --variants 6
```

The augmentation is intentionally moderate. Camera/data consistency is more valuable here than making synthetic transformations extremely strong.

## 7. Split and train

```powershell
.\.venv\Scripts\python.exe -m src.split_dataset --config configs/default.yaml --evaluation-mode split
.\.venv\Scripts\python.exe -m src.train --config configs/default.yaml
```

The new artifact is:


```text
artifacts/core_classifier_simple_v3/model.pt
```

The default model is EfficientNet-B0 at 224x224. It is smaller than the previous B2 model on purpose: the real dataset is tiny, so a huge model is not the main solution.

## 8. Evaluate

```powershell
.\.venv\Scripts\python.exe -m src.evaluate --artifact artifacts/core_classifier_simple_v3
```

Do not judge quality from training accuracy. Look at untouched test originals, confusion matrix, and live camera behavior.

## 9. Run the simple camera

```powershell
.\run_camera.bat
```

or:

```powershell
.\.venv\Scripts\python.exe -m src.simple_camera --artifact artifacts/core_classifier_simple_v3 --config configs/default.yaml
```

The display has only three operational states:

- `NO PIECE`
- `PIECE FOUND — Type: ...`
- `UNCERTAIN — HOLD PIECE STILL`

Controls:

- `S`: save the current ROI crop
- `Q` / `ESC`: quit

## Why this is easier

The previous versions were trying to solve two difficult problems simultaneously: localize an arbitrary piece and classify its type. With a fixed camera station, that complexity is unnecessary.

Simple V3 fixes the camera geometry instead. It also uses `EMPTY` as a learned negative class, which makes presence detection part of the same classification task.

The most important improvement is not stronger augmentation. It is collecting training examples from the **same camera, same ROI, same distance range, same background, and realistic lighting** used during deployment.
