"""Retouch v2 on SYNTHETIC images / landmarks (no personal media, no network)."""
import pathlib
import sys

import numpy as np
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "lib"))

cv2 = pytest.importorskip("cv2")
from vstudio import face as F  # noqa: E402
from vstudio import retouch as R  # noqa: E402


def synth_face(w=640, h=720, cx=320, cy=360, fw=300):
    """(478, 2) landmark array whose named groups have plausible geometry (an upright face of width fw)."""
    rng = np.random.default_rng(0)
    fh = fw * 1.3
    pts = np.zeros((478, 2), np.float32)
    ang = rng.uniform(0, 2 * np.pi, 478); rad = np.sqrt(rng.uniform(0, 1, 478)) * .35
    pts[:, 0] = cx + np.cos(ang) * rad * fw; pts[:, 1] = cy + np.sin(ang) * rad * fh

    def ring(idx, c, rx, ry, a0=0.0):
        t = a0 + np.linspace(0, 2 * np.pi, len(idx), endpoint=False)
        pts[idx] = np.stack([c[0] + rx * np.cos(t), c[1] + ry * np.sin(t)], 1)

    def arc(idx, p0, p1, bulge):
        t = np.linspace(0, 1, len(idx))[:, None]
        p = np.array(p0) * (1 - t) + np.array(p1) * t
        p[:, 1] -= bulge * np.sin(np.pi * t[:, 0])
        pts[idx] = p
    ring(F.FACE_OVAL, (cx, cy), fw / 2, fh / 2, -np.pi / 2)
    pts[10] = (cx, cy - fh / 2); pts[152] = (cx, cy + fh / 2)
    pts[234] = (cx - fw / 2, cy - .05 * fh); pts[454] = (cx + fw / 2, cy - .05 * fh)
    pts[127] = (cx - fw * .48, cy - .2 * fh); pts[356] = (cx + fw * .48, cy - .2 * fh)
    pts[93] = (cx - fw * .48, cy + .05 * fh); pts[323] = (cx + fw * .48, cy + .05 * fh)
    pts[132] = (cx - fw * .45, cy + .15 * fh); pts[361] = (cx + fw * .45, cy + .15 * fh)
    pts[172] = (cx - fw * .38, cy + .3 * fh); pts[397] = (cx + fw * .38, cy + .3 * fh)
    ex = fw * .2; ey = cy - .08 * fh
    for sgn, upper, lower, ringi, brow, low in ((-1, F.UPPER_LID_L, F.LOWER_LID_L, F.LEFT_EYE_RING, F.BROW_L, F.BROW_LOW_L),
                                                (1, F.UPPER_LID_R, F.LOWER_LID_R, F.RIGHT_EYE_RING, F.BROW_R, F.BROW_LOW_R)):
        outer, inner = (cx + sgn * ex * 1.6, ey), (cx + sgn * ex * .45, ey)
        ring(ringi, (cx + sgn * ex, ey), ex * .55, fw * .035)
        arc(upper, outer, inner, fw * .035); arc(lower, outer, inner, -fw * .03)
        top = [(cx + sgn * ex * s, ey - fw * .13 - fw * .02 * np.sin(np.pi * (s - .4) / 1.4)) for s in np.linspace(1.8, .4, 5)]
        bot = [(x, y + fw * .035) for x, y in top]
        pts[brow] = np.array(top + bot[::-1], np.float32)
        pts[low] = np.array(bot, np.float32)
    ring(F.LIPS_OUT, (cx, cy + .25 * fh), fw * .16, fw * .055)
    ring(F.LIPS_IN, (cx, cy + .25 * fh), fw * .12, fw * .012)
    pts[61] = (cx - fw * .16, cy + .25 * fh); pts[291] = (cx + fw * .16, cy + .25 * fh)
    pts[13] = (cx, cy + .25 * fh - 2); pts[14] = (cx, cy + .25 * fh + 2)
    for i, idx in enumerate(F.NOSE_BRIDGE):
        pts[idx] = (cx, ey + i * fw * .06)
    pts[1] = pts[4] = (cx, cy + .08 * fh); pts[9] = (cx, ey - fw * .12); pts[151] = (cx, cy - .38 * fh)
    pts[129] = (cx - fw * .07, cy + .08 * fh); pts[358] = (cx + fw * .07, cy + .08 * fh)
    for apple, sgn in ((F.CHEEK_APPLE_L, -1), (F.CHEEK_APPLE_R, 1)):
        ring(apple, (cx + sgn * fw * .25, cy + .06 * fh), fw * .05, fw * .04)
    return pts


def synth_image(w=640, h=720, pts=None):
    img = np.full((h, w, 3), (70, 80, 90), np.uint8)
    if pts is not None:
        cv2.fillPoly(img, [pts[F.FACE_OVAL].astype(np.int32)], (150, 170, 205))
        rng = np.random.default_rng(1)
        noise = rng.normal(0, 4, img.shape).astype(np.float32)
        img = np.clip(img + noise, 0, 255).astype(np.uint8)
        cv2.fillPoly(img, [pts[F.LIPS_OUT].astype(np.int32)], (110, 110, 190))
        for b in (F.BROW_L, F.BROW_R):
            cv2.fillPoly(img, [pts[b].astype(np.int32)], (40, 45, 55))
    return img


def test_no_face_is_a_noop():
    img = synth_image()
    out = R.retouch(img, f=[])                                # explicit "no faces"
    assert out is img
    try:
        lm = F.landmarker(1)
    except FileNotFoundError:
        return                                                 # model not installed: covered by f=[]
    out = R.retouch(img, lm=lm, preset="glam")
    assert np.array_equal(out, img)


def test_mask_functions_shapes():
    pts = synth_face(); img = synth_image(pts=pts)
    shp = img.shape[:2]
    sk = R.landmark_skin_mask(shp, pts)
    assert sk.shape == shp and sk.dtype == np.float32 and 0 <= sk.min() and sk.max() <= 1
    eye_c = pts[F.LEFT_EYE_RING].mean(0).astype(int); lip_c = pts[F.LIPS_OUT].mean(0).astype(int)
    cheek = pts[F.CHEEK_APPLE_L].mean(0).astype(int)
    assert sk[eye_c[1], eye_c[0]] < .05 and sk[lip_c[1], lip_c[0]] < .05 and sk[cheek[1], cheek[0]] > .9
    assert sk[5, 5] == 0
    ue = R.undereye_mask(shp, pts)
    assert ue.shape == shp and ue.max() > .3 and ue[5, 5] == 0
    frames, thick = R.glasses_mask(img, pts)
    assert frames.shape == shp and thick == 0.0              # no glasses on the synthetic face
    face, neck = R.skin_mask(img, pts, R._opts(), seg=None, frames=frames)
    assert face.shape == shp and neck.shape == shp and float(neck.max()) == 0.0


def test_skin_and_makeup_landmark_fallback_stays_on_face():
    pts = synth_face(); img = synth_image(pts=pts)
    f = {"pts": pts, "blend": {}}
    out = R.retouch(img, f=f, skin_seg=False, preset="daily", makeup=.5)
    assert out.shape == img.shape and out.dtype == np.uint8
    assert np.abs(out[:20, :60].astype(int) - img[:20, :60]).max() <= 1   # far from the face: untouched
    lip_c = pts[F.LIPS_OUT].mean(0).astype(int); y, x = lip_c[1], lip_c[0]
    assert np.abs(out[y - 3:y + 4, x - 30:x - 20].astype(int) - img[y - 3:y + 4, x - 30:x - 20]).mean() > 1
    cheek = pts[F.CHEEK_APPLE_L].mean(0).astype(int)
    def patch(a):
        return cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)[cheek[1] - 10:cheek[1] + 10, cheek[0] - 10:cheek[0] + 10].astype(np.float32)
    assert patch(out).std() < .95 * patch(img).std()         # smoothed (noise attenuated) ...
    assert patch(out).std() > .3 * patch(img).std()          # ... but texture kept


def test_guided_filter_flat_and_edges():
    I = np.zeros((64, 64), np.float32); I[:, 32:] = 1
    out = R.guided_filter(I, I, 4, 1e-4)
    assert np.allclose(out[:, :28], 0, atol=1e-3) and np.allclose(out[:, 36:], 1, atol=1e-3)
    flat = np.full((32, 32), .4, np.float32)
    assert np.allclose(R.guided_filter(flat, flat, 3, .01), .4, atol=1e-5)


def test_landmark_smoother_continuous_across_chunk_overlap():
    rng = np.random.default_rng(3)
    base = synth_face().astype(np.float64)
    n, seam, warm, fps = 120, 60, R_WARMUP, 30.0
    seq = [base + np.array([40 * np.sin(i / 15), 10 * np.cos(i / 9)]) + rng.normal(0, .8, base.shape)
           for i in range(n)]
    full = F.LandmarkSmoother()
    ref = [full(p, i / fps) for i, p in enumerate(seq)]
    chunk = F.LandmarkSmoother()
    got = [chunk(seq[i], i / fps) for i in range(seam - warm, n)][warm:]
    fw = np.ptp(base[F.FACE_OVAL, 0])
    err = np.abs(np.array(got[0]) - ref[seam]).max() / fw
    assert err < .01, err                                     # < 1% face width at the seam
    later = np.abs(np.array(got[10]) - ref[seam + 10]).max() / fw
    assert later < err + 1e-9
    jitter_raw = np.mean([np.abs(seq[i + 1] - seq[i]).mean() for i in range(n - 1)])
    jitter_sm = np.mean([np.abs(ref[i + 1] - ref[i]).mean() for i in range(n - 1)])
    assert jitter_sm < jitter_raw


R_WARMUP = 15


def test_preset_parameter_validation():
    nat = R.makeup_params("natural")
    assert nat["lip"] == pytest.approx(R.PRESETS["natural"]["lip"]) and nat["liner"] == 0
    none = R.makeup_params("none", 1.0)
    assert all(none[c] == 0 for c in R.COMPONENTS)
    glam = R.makeup_params("glam", 1.0)
    assert all(0 <= glam[c] <= 1 for c in R.COMPONENTS)
    assert R.makeup_params("daily", .5, lip=.2)["lip"] == pytest.approx(.2)
    assert len(R.makeup_params("natural", lip_shade="#b03050")["lip_shade"]) == 3
    with pytest.raises(ValueError):
        R.makeup_params("smoky")
    with pytest.raises(ValueError):
        R.makeup_params("natural", lip_shade="chartreuse-ish")
    with pytest.raises(ValueError):
        R.makeup_params("natural", 3.0)
    with pytest.raises(ValueError):
        R.makeup_params("natural", lip=-1)
    with pytest.raises(ValueError):
        R.retouch(synth_image(), f=[], preset="smoky")


def test_reshape_cap_and_identity_guard():
    pts = synth_face(); img = synth_image(pts=pts)
    f = {"pts": pts, "blend": {}}
    _, moved_wild = R._warp(img, f, R._opts(slim=.4, eye=.3, natural_cap=0, identity_guard=0, grid=120))
    _, moved_guard = R._warp(img, f, R._opts(slim=.4, eye=.3, natural_cap=0, identity_guard=.1, grid=120))
    assert R.identity_drift(pts, moved_wild) > .1
    assert R.identity_drift(pts, moved_guard) <= .1 + 1e-3
    out, moved = R._warp(img, f, R._opts(slim=0, eye=0))
    assert out is img and np.allclose(moved, pts)


def test_video_state_reuses_warp_field():
    pts = synth_face(); img = synth_image(pts=pts)
    st = R.RetouchState(video=True)
    o = R._opts(grid=120)
    R._warp(img, {"pts": pts, "blend": {}}, o, st)
    field = st.warp[3]
    R._warp(img, {"pts": pts + .05, "blend": {}}, o, st)
    assert st.warp[3] is field                                # barely moved: field reused
    R._warp(img, {"pts": pts + 6, "blend": {}}, o, st)
    assert st.warp[3] is not field


def test_multi_face_strength():
    a = synth_face(1000, 600, 260, 300, 260); b = synth_face(1000, 600, 760, 300, 200)
    img = synth_image(1000, 600, a)
    cv2.fillPoly(img, [b[F.FACE_OVAL].astype(np.int32)], (150, 170, 205))
    faces = [{"pts": a, "blend": {}}, {"pts": b, "blend": {}}]
    main = R.retouch(img, f=faces, skin_seg=False)
    both = R.retouch(img, f=faces, skin_seg=False, faces="all", face_strength=[1, .5])
    cb = b[F.FACE_OVAL].mean(0).astype(int)
    sl = (slice(cb[1] - 60, cb[1] + 60), slice(cb[0] - 60, cb[0] + 60))
    assert np.array_equal(main[sl], img[sl])                  # default: main face only
    assert not np.array_equal(both[sl], img[sl])
