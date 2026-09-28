import numpy as np
import cv2
import time
import json

def generate_test_scenes():
    h, w = 480, 640
    scenes = {}

    # 1. Normal outdoor high-contrast scene (Sky, mountains, foliage, border road)
    outdoor = np.zeros((h, w, 3), dtype=np.uint8)
    for y in range(h // 2):
        val = int(220 - y * 0.2)
        outdoor[y, :] = [val, val - 20, 180]
    for y in range(h // 2, h):
        val = int(60 + (y - h // 2) * 0.2)
        outdoor[y, :] = [30, val, 70]
    for x in range(50, w, 60):
        cv2.line(outdoor, (x, h // 2 - 40), (x, h), (20, 20, 20), 4)
        cv2.line(outdoor, (0, h // 2 + 30), (w, h // 2 + 30), (180, 180, 180), 2)
    noise = np.random.normal(0, 5, outdoor.shape).astype(np.int16)
    outdoor = np.clip(outdoor.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    scenes["normal_outdoor_high_contrast"] = outdoor

    # 2. Normal indoor scene (office walls, desk, whiteboard, moderate contrast)
    indoor = np.ones((h, w, 3), dtype=np.uint8) * 160
    indoor[h // 2:, :] = 90
    cv2.rectangle(indoor, (100, 50), (250, 400), (40, 40, 40), 6)
    cv2.rectangle(indoor, (350, 80), (580, 260), (230, 230, 230), -1)
    cv2.rectangle(indoor, (350, 80), (580, 260), (30, 30, 30), 3)
    noise = np.random.normal(0, 4, indoor.shape).astype(np.int16)
    indoor = np.clip(indoor.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    scenes["normal_indoor"] = indoor

    # 3. Complete blackout (lens cap on, minimal dark sensor noise)
    blackout = np.random.normal(2, 1.5, (h, w, 3))
    blackout = np.clip(blackout, 0, 255).astype(np.uint8)
    scenes["complete_blackout"] = blackout

    # 4. Hand/cloth occlusion (dark cloth covering lens, flat low variance)
    cloth = np.ones((h, w, 3), dtype=np.uint8) * 28
    noise = np.random.normal(0, 1.2, (h, w, 3)).astype(np.int16)
    cloth = np.clip(cloth.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    scenes["hand_cloth_occlusion"] = cloth

    # 5. Severe Gaussian blur on outdoor scene (vaseline/spray on lens)
    severe_blur = cv2.GaussianBlur(outdoor, (101, 101), 35.0)
    scenes["severe_gaussian_blur"] = severe_blur

    # 6. Moderate Gaussian blur on outdoor scene (minor condensation/defocus)
    moderate_blur = cv2.GaussianBlur(outdoor, (25, 25), 7.0)
    scenes["moderate_gaussian_blur"] = moderate_blur

    # 7. Partial lens obstruction (70% covered by dark cloth, 30% unobstructed outdoor scene)
    partial_obstruction = outdoor.copy()
    partial_obstruction[:, :int(w * 0.7)] = cloth[:, :int(w * 0.7)]
    scenes["partial_lens_obstruction"] = partial_obstruction

    # 8. Bright sky + dark ground (extreme dynamic contrast, horizon edge)
    split_scene = np.zeros((h, w, 3), dtype=np.uint8)
    split_scene[:h // 2, :] = [240, 240, 240]
    split_scene[h // 2:, :] = [30, 30, 30]
    cv2.line(split_scene, (0, h // 2), (w, h // 2), (0, 0, 0), 2)
    noise = np.random.normal(0, 3, split_scene.shape).astype(np.int16)
    split_scene = np.clip(split_scene.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    scenes["bright_sky_dark_ground"] = split_scene

    # 9. Low-light border scene (ambient night, mean lum ~15-20, low contrast)
    low_light = np.zeros((h, w, 3), dtype=np.uint8)
    for y in range(h):
        low_light[y, :] = int(10 + y * 0.02)
    cv2.rectangle(low_light, (200, 150), (280, 420), (5, 5, 5), -1)
    noise = np.random.normal(0, 2.5, low_light.shape).astype(np.int16)
    low_light = np.clip(low_light.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    scenes["low_light_scene"] = low_light

    return scenes

def evaluate_tamper(frame):
    t0 = time.perf_counter()
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    std_dev = float(np.std(gray))
    mean_val = float(np.mean(gray))
    lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    calc_time_ms = (time.perf_counter() - t0) * 1000

    # Current clauses in camera_manager.py
    clause_a = (mean_val < 18.0 and std_dev < 10.0)
    clause_b = (std_dev < 12.0 and lap_var < 15.0)
    clause_c = (lap_var < 6.0 and std_dev < 18.0)
    current_tampered = bool(clause_a or clause_b or clause_c)

    return {
        "mean_lum": round(mean_val, 2),
        "std_dev": round(std_dev, 2),
        "laplacian_var": round(lap_var, 2),
        "calc_time_ms": round(calc_time_ms, 3),
        "clause_a_blackout": clause_a,
        "clause_b_uniform": clause_b,
        "clause_c_edge_loss": clause_c,
        "current_tampered": current_tampered
    }

def run_investigation():
    scenes = generate_test_scenes()
    results = {}
    print(f"{'Scene Name':<32} | {'Mean':>6} | {'StdDev':>7} | {'LapVar':>8} | {'Cl_A':>5} | {'Cl_B':>5} | {'Cl_C':>5} | {'TAMPER':>6}")
    print("-" * 90)

    for name, frame in scenes.items():
        res = evaluate_tamper(frame)
        results[name] = res
        print(f"{name:<32} | {res['mean_lum']:>6.1f} | {res['std_dev']:>7.1f} | {res['laplacian_var']:>8.2f} | {str(res['clause_a_blackout']):>5} | {str(res['clause_b_uniform']):>5} | {str(res['clause_c_edge_loss']):>5} | {str(res['current_tampered']):>6}")

    with open("tests/p1_tamper_investigation_results.json", "w") as f:
        json.dump(results, f, indent=2)

if __name__ == "__main__":
    run_investigation()
