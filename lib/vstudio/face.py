"""MediaPipe FaceLandmarker helpers (478-point mesh + blendshapes) and landmark index sets."""
import os
import warnings

import numpy as np

warnings.filterwarnings("ignore")
os.environ.setdefault("GLOG_minloglevel", "3")

LEFT_EYE_RING = [33, 246, 161, 160, 159, 158, 157, 173, 133, 155, 154, 153, 145, 144, 163, 7]
RIGHT_EYE_RING = [263, 466, 388, 387, 386, 385, 384, 398, 362, 382, 381, 380, 374, 373, 390, 249]
LEFT_EAR = [33, 160, 158, 133, 153, 144]
RIGHT_EAR = [362, 385, 387, 263, 373, 380]
FACE_OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400,
             377, 152, 148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109]
BROW_L = [70, 63, 105, 66, 107, 55, 65, 52, 53, 46]
BROW_R = [300, 293, 334, 296, 336, 285, 295, 282, 283, 276]
LIPS_OUT = [61, 185, 40, 39, 37, 0, 267, 269, 270, 409, 291, 375, 321, 405, 314, 17, 84, 181, 91, 146]
LIPS_IN = [78, 191, 80, 81, 82, 13, 312, 311, 310, 415, 308, 324, 318, 402, 317, 14, 87, 178, 88, 95]
JAW_SLIM = [132, 58, 172, 136, 150, 149, 176, 148, 377, 400, 378, 379, 365, 397, 288, 361]
CHEEK_WIDE = [234, 454, 93, 323, 132, 361]
ANCHORS_FACE = [10, 9, 151, 8, 168, 6, 1, 2, 0, 17, 152, 200, 199, 61, 291, 78, 308]
BROW_ANCHORS = [70, 63, 105, 66, 107, 300, 293, 334, 296, 336]
CHEEK_APPLE_L = [50, 101, 118, 117, 123]
CHEEK_APPLE_R = [280, 330, 347, 346, 352]


def landmarker(num_faces: int = 1, video: bool = False):
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision
    from .config import model
    opts = vision.FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=model("face_landmarker")),
        output_face_blendshapes=True, num_faces=num_faces,
        min_face_detection_confidence=0.4, min_face_presence_confidence=0.4,
        running_mode=vision.RunningMode.VIDEO if video else vision.RunningMode.IMAGE)
    return vision.FaceLandmarker.create_from_options(opts)


def detect(lm, bgr, ts_ms: int = None):
    """List of faces: {"pts": (478,2) pixel coords, "blend": {name: score}}. Pass ts_ms in VIDEO mode."""
    import cv2
    import mediapipe as mp
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    res = lm.detect_for_video(img, ts_ms) if ts_ms is not None else lm.detect(img)
    h, w = bgr.shape[:2]
    out = []
    for i, f in enumerate(res.face_landmarks):
        pts = np.array([[p.x * w, p.y * h] for p in f], np.float32)
        blend = {c.category_name: c.score for c in res.face_blendshapes[i]} if res.face_blendshapes else {}
        out.append({"pts": pts, "blend": blend})
    return out


def ear(pts, idx):
    p1, p2, p3, p4, p5, p6 = pts[idx]
    return float((np.linalg.norm(p2 - p6) + np.linalg.norm(p3 - p5)) / (2 * np.linalg.norm(p1 - p4) + 1e-6))


def main_face(faces, min_area_frac: float = 0.0, shape=None):
    """Largest face (optionally ignoring tiny background faces)."""
    best, area = None, 0
    for f in faces:
        p = f["pts"]; a = np.ptp(p[:, 0]) * np.ptp(p[:, 1])
        if shape is not None and a / (shape[0] * shape[1]) < min_area_frac:
            continue
        if a > area:
            best, area = f, a
    return best
