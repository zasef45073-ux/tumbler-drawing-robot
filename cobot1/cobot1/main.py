import sys
import os
import json
import time
from pathlib import Path

_ROOT = os.path.dirname(os.path.abspath(__file__))
for _p in [_ROOT, os.path.join(_ROOT, "_stroke"), os.path.join(_ROOT, "_path_opt")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# _input
from _input.image_loader_debug import ImageLoader
from _input.edge_detector import EdgeDetector

# _stroke  (bare 이름 — greedy_order/two_opt 내부 import와 모듈 캐시 공유)
from _stroke.contour_extractor import filter_contours_by_area, build_color_masks_from_contours
from _fill.color_fill import raster_scan_grouped
from _stroke.bezier_fitter import (
    BezierFitResult,
    fit_contour,
    deduplicate_fit_results,
    filter_and_order_fit_results,
    split_on_gaps,
)

# _path_opt  (bare 이름 — 내부 상호 import와 일치)
from _path_opt.greedy_order import greedy_nearest, OrderedStroke
from _path_opt.two_opt import two_opt

# _kinematics
from _kinematics.coord_transform import pixel_to_xyz_batch
from _kinematics.ik_solver import (
    configure_drawing_progress,
    finish_drawing_progress,
)

# robot
import rclpy
import DR_init


_PEN_BGR = {
    "black": (0, 0, 0),
    "red": (0, 0, 255),
}


def bgr_to_pen_color(bgr: tuple) -> str:
    """BGR 튜플을 가장 가까운 펜 색상 이름으로 변환."""
    b, g, r = bgr
    return min(
        _PEN_BGR,
        key=lambda n: (b - _PEN_BGR[n][0]) ** 2
        + (g - _PEN_BGR[n][1]) ** 2
        + (r - _PEN_BGR[n][2]) ** 2,
    )


def _to_int_points(points):
    result = []
    for point in points or []:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        result.append([int(point[0]), int(point[1])])
    return result


def _to_float_xyz(points):
    result = []
    for point in points or []:
        if not isinstance(point, (list, tuple)) or len(point) < 3:
            continue
        result.append([
            round(float(point[0]), 4),
            round(float(point[1]), 4),
            round(float(point[2]), 4),
        ])
    return result


def _make_path_stroke(
    *,
    phase,
    color,
    pixels,
    xyz_points,
    source_index,
    extra=None,
):
    extra = extra or {}
    return {
        "phase": phase,
        "color": color,
        "source_index": int(source_index),
        "point_count": int(len(xyz_points or [])),
        "pixels": _to_int_points(pixels),
        "xyz_points": _to_float_xyz(xyz_points),
        **extra,
    }


def save_actual_drawing_path_json(
    *,
    json_path,
    job_id,
    source_image,
    image_width,
    image_height,
    image_size_px,
    outline_strokes,
    fill_strokes,
):
    """
    실제 main.py가 draw_path()에 넘길 순서 그대로 UI용 경로 JSON을 저장한다.

    핵심:
    - preview_main.py가 다시 계산한 경로가 아니라, 이 main.py가 실제로 그릴 리스트를 저장한다.
    - dashboard.js는 strokes[].pixels를 보고 canvas에 그린다.
    - point_count/summary는 ik_solver 진행률의 total point 기준과 맞춘다.
    """

    json_path = Path(json_path).expanduser().resolve()
    json_path.parent.mkdir(parents=True, exist_ok=True)

    strokes = []
    for stroke in outline_strokes:
        strokes.append(dict(stroke))
    for stroke in fill_strokes:
        strokes.append(dict(stroke))

    for index, stroke in enumerate(strokes):
        stroke["stroke_index"] = index

    outline_point_count = sum(int(stroke.get("point_count") or 0) for stroke in outline_strokes)
    fill_point_count = sum(int(stroke.get("point_count") or 0) for stroke in fill_strokes)
    total_point_count = outline_point_count + fill_point_count

    data = {
        "source": "main.py",
        "pathSource": "actual_main_pipeline",
        "jobId": str(job_id or ""),
        "source_image": str(source_image or ""),
        "image_width_px": int(image_width),
        "image_height_px": int(image_height),
        "image_size_px": int(image_size_px),
        "summary": {
            "outline_stroke_count": int(len(outline_strokes)),
            "fill_stroke_count": int(len(fill_strokes)),
            "total_stroke_count": int(len(strokes)),
            "outline_point_count": int(outline_point_count),
            "fill_point_count": int(fill_point_count),
            "total_point_count": int(total_point_count),
        },
        "strokes": strokes,
        "createdAt": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    tmp_path = json_path.with_suffix(json_path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp_path.replace(json_path)

    print("=" * 60)
    print("[ActualDrawingPath] 실제 main.py 경로 JSON 저장 완료")
    print(f"[ActualDrawingPath] path                 : {json_path}")
    print(f"[ActualDrawingPath] outline_stroke_count : {len(outline_strokes)}")
    print(f"[ActualDrawingPath] fill_stroke_count    : {len(fill_strokes)}")
    print(f"[ActualDrawingPath] total_point_count    : {total_point_count}")
    print("=" * 60)

    return str(json_path)


def _get_float_env(name, default):
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return float(default)


def main(args=None):
    # ------------------------------------------------------------------
    # 1. 이미지 로드
    # ------------------------------------------------------------------
    loader = ImageLoader()
    rgb_img = loader.load()
    if rgb_img is None:
        print("[오류] 이미지 로드 실패")
        return

    h, w, c = rgb_img.shape
    image_size_px = max(h, w)
    print(f"[1] 이미지 로드 완료: {w}x{h}")

    # ------------------------------------------------------------------
    # 2. 엣지 검출
    # ------------------------------------------------------------------
    detector = EdgeDetector()
    edges = detector.detect(rgb_img)
    print("[2] 엣지 검출 완료")

    # ------------------------------------------------------------------
    # 3. 윤곽선 추출 및 소면적 노이즈 제거 + 색깔 마스크 추출
    # ------------------------------------------------------------------
    contours = filter_contours_by_area(edges, min_area=1)
    print(f"[3] 윤곽선 수: {len(contours)}")
    if not contours:
        print("[오류] 윤곽선 없음 — 종료")
        return

    # ------------------------------------------------------------------
    # 4. 윤곽선 → 3차 베지어 곡선 피팅
    # ------------------------------------------------------------------
    fit_results: list[BezierFitResult] = []
    for i, contour in enumerate(contours):
        curves = fit_contour(contour)
        if curves:
            fit_results.append(BezierFitResult(curves=curves, contour_index=i))

    fit_results = deduplicate_fit_results(fit_results, 3, 32)
    fit_results = filter_and_order_fit_results(fit_results, (h, w))
    fit_results = split_on_gaps(fit_results)
    if not fit_results:
        print("[오류] 피팅 결과 없음 — 종료")
        return

    # ------------------------------------------------------------------
    # 5. Greedy Nearest Neighbor 경로 최적화
    # ------------------------------------------------------------------
    ordered = greedy_nearest(fit_results)

    # ------------------------------------------------------------------
    # 6. 2-opt 경로 개선
    # ------------------------------------------------------------------
    optimized = two_opt(ordered)

    # ------------------------------------------------------------------
    # 7. 역기구학 — 실제 draw_path에 넘길 stroke를 먼저 확정
    # ------------------------------------------------------------------
    ROBOT_ID = "dsr01"
    ROBOT_MODEL = "m0609"
    DR_init.__dsr__id = ROBOT_ID
    DR_init.__dsr__model = ROBOT_MODEL

    print(f"\n[7] === 역기구학 출력 ({len(optimized)} 스트로크) ===")

    # --------------------------------------------------------------
    # 7-1. 실제 로봇이 그릴 outline/fill 경로를 draw_path 실행 전에 모두 확정한다.
    #      이 리스트가 곧 UI canvas가 따라갈 실제 경로다.
    # --------------------------------------------------------------
    outline_strokes = []

    for idx, stroke in enumerate(optimized):
        pixels = stroke.sample_pixels(min_dist_px=2.8)
        xyz_points = pixel_to_xyz_batch(pixels, 0.0, 0.0, image_size_px)

        if xyz_points:
            outline_strokes.append(
                _make_path_stroke(
                    phase="outline",
                    color="black",
                    pixels=pixels,
                    xyz_points=xyz_points,
                    source_index=idx,
                    extra={
                        "contour_index": int(getattr(stroke, "contour_index", idx)),
                        "is_reversed": bool(getattr(stroke, "is_reversed", False)),
                    },
                )
            )
    
    LINE_SPACING = 5
    color_masks = build_color_masks_from_contours(rgb_img, contours)
    fill_strokes = []
    if color_masks is None:
        pass
    else:    
        for color_idx, (detected_bgr, mask) in enumerate(color_masks.items()):
            detected_pen_color = bgr_to_pen_color(detected_bgr)
            fill_paths = raster_scan_grouped(mask, LINE_SPACING)

            print(
                f"[색상 {color_idx}] BGR={detected_bgr} "
                f"→ detected_pen={detected_pen_color}, actual_pen=red, 경로 수={len(fill_paths)}"
            )

            for path_idx, path in enumerate(fill_paths):
                xyz_points = pixel_to_xyz_batch(path, 0.0, 0.0, image_size_px)
                if xyz_points:
                    fill_strokes.append(
                        _make_path_stroke(
                            phase="fill",
                            # 현재 실제 main.py는 change_pen 이후 fill 전체를 red로 그린다.
                            # UI도 실제 로봇 펜 색상 기준으로 맞춘다.
                            color="red",
                            pixels=path,
                            xyz_points=xyz_points,
                            source_index=path_idx,
                            extra={
                                "color_group_index": int(color_idx),
                                "detected_bgr": [int(v) for v in detected_bgr],
                                "detected_pen_color": detected_pen_color,
                                "line_spacing": int(LINE_SPACING),
                            },
                        )
                    )

        total_points = (
            sum(int(stroke["point_count"]) for stroke in outline_strokes)
            + sum(int(stroke["point_count"]) for stroke in fill_strokes)
        )

        print("=" * 60)
        print(f"[DrawingProgress] 전체 outline stroke 수 : {len(outline_strokes)}")
        print(f"[DrawingProgress] 전체 fill stroke 수    : {len(fill_strokes)}")
        print(f"[DrawingProgress] 전체 drawing point 수  : {total_points}")
        print("=" * 60)

        if total_points <= 0:
            print("[오류] 변환된 drawing point가 없습니다 — 종료")
            return
    
    # --------------------------------------------------------------
    # 7-2. 실제 main.py 경로 JSON 저장
    #      adapter가 이 파일을 서버로 업로드하면 dashboard canvas가 preview 경로가 아니라
    #      실제 로봇 실행 경로를 따라간다.
    # --------------------------------------------------------------
    progress_job_id = os.getenv("COBOT1_DRAWING_JOB_ID", "").strip()
    progress_file = os.getenv("COBOT1_DRAWING_PROGRESS_FILE", "").strip()
    actual_path_file = os.getenv("COBOT1_DRAWING_PATH_FILE", "").strip()

    if actual_path_file:
        source_image_for_json = getattr(loader, "image_path", "")
        save_actual_drawing_path_json(
            json_path=actual_path_file,
            job_id=progress_job_id,
            source_image=source_image_for_json,
            image_width=w,
            image_height=h,
            image_size_px=image_size_px,
            outline_strokes=outline_strokes,
            fill_strokes=fill_strokes,
        )

        # adapter가 JSON을 업로드해 Firebase drawingPathJsonUrl을 바꿀 시간을 잠깐 준다.
        # 너무 길면 로봇 시작이 늦어지므로 기본 1초.
        wait_sec = _get_float_env("COBOT1_DRAWING_PATH_READY_WAIT_SEC", 1.0)
        if wait_sec > 0:
            print(f"[ActualDrawingPath] adapter 업로드 대기 {wait_sec:.1f}초")
            time.sleep(wait_sec)

    # --------------------------------------------------------------
    # 7-3. 진행률 기록 설정
    # --------------------------------------------------------------
    configure_drawing_progress(
        total_points=total_points,
        job_id=progress_job_id,
        progress_file=progress_file,
    )

    # --------------------------------------------------------------
    # 7-4. 실제 로봇 드로잉 실행
    # --------------------------------------------------------------
    rclpy.init(args=args)
    node = rclpy.create_node("drawing_node", namespace=ROBOT_ID)
    DR_init.__dsr__node = node

    # DSR_ROBOT2 uses DR_init.__dsr__node at import time, so import only after node is ready
    from _kinematics.ik_solver import draw_path, change_pen, pick_up_pen, release_pen

    drawing_success = False

    try:
        pick_up_pen("black")
        COLOR_NOW = "black"

        # 윤곽선 그리기 — JSON에 저장한 outline_strokes와 동일한 순서/좌표 사용
        for idx, stroke in enumerate(outline_strokes):
            xyz_points = [tuple(point) for point in stroke["xyz_points"]]
            print(f"\n  [윤곽선 {idx + 1}/{len(outline_strokes)}] 점 수: {len(xyz_points)}")
            draw_path(xyz_points=xyz_points, color=COLOR_NOW)

        change_pen("black", "red")
        COLOR_NOW = "red"

        # 색칠 그리기 — JSON에 저장한 fill_strokes와 동일한 순서/좌표 사용
        print(f"\n[색칠] 감지된 색상 수: {len(color_masks)}")
        for idx, stroke in enumerate(fill_strokes):
            xyz_points = [tuple(point) for point in stroke["xyz_points"]]
            detected_bgr = stroke.get("detected_bgr", [])
            print(
                f"    [색칠 경로 {idx + 1}/{len(fill_strokes)}] "
                f"BGR={detected_bgr} 점 수: {len(xyz_points)}"
            )
            draw_path(xyz_points=xyz_points, color=COLOR_NOW)

        release_pen("red")
        drawing_success = True
        finish_drawing_progress(success=True)

    except KeyboardInterrupt:
        print("\nNode interrupted by user. Shutting down...")
        finish_drawing_progress(success=False)
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        finish_drawing_progress(success=False)
    finally:
        rclpy.shutdown()

    if drawing_success:
        print("\n=== 파이프라인 완료 ===")
    else:
        print("\n=== 파이프라인 비정상 종료 ===")


if __name__ == "__main__":
    main()
