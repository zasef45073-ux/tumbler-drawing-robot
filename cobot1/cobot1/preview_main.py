import argparse
import json
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np


# ============================================================
# preview_main.py
#
# 역할:
# - 알고리즘 팀 원본 main.py는 건드리지 않고,
#   이미지 처리 / 경로 생성 / 좌표 변환 결과만 확인하는 preview 실행 파일
#
# 중요:
# - rclpy import 안 함
# - DR_init import 안 함
# - robot_state import 안 함
# - ik_solver.draw_path() 호출 안 함
# - DSR_ROBOT2 / movel / movej 호출 안 함
#
# 실행:
#   python3 preview_main.py
#
# 입력 이미지 지정:
#   python3 preview_main.py --image _input/test.png
#
# 출력 폴더 지정:
#   python3 preview_main.py --output _input/preview_output
# ============================================================


# 현재 파일 위치: cobot1/cobot1/preview_main.py 라고 가정
_ROOT = Path(__file__).resolve().parent

# 기존 팀 코드 import 방식과 맞추기 위한 path 설정
for _p in [
    _ROOT,
    _ROOT / "_input",
    _ROOT / "_stroke",
    _ROOT / "_path_opt",
    _ROOT / "_kinematics",
]:
    _p_str = str(_p)
    if _p_str not in sys.path:
        sys.path.insert(0, _p_str)


# 기존 알고리즘 모듈 import
from _stroke.contour_extractor import (
    filter_contours_by_area,
    build_color_masks_from_contours,
)
from _stroke.bezier_fitter import (
    BezierFitResult,
    fit_contour,
    draw_bezier_fit_results,
    deduplicate_fit_results,
    filter_and_order_fit_results,
    split_on_gaps,
)
from _path_opt.greedy_order import (
    greedy_nearest,
    total_pen_up_distance,
    draw_greedy_order,
)
from _path_opt.two_opt import two_opt
from _kinematics.coord_transform import pixel_to_xyz_batch
from _fill.color_fill import raster_scan_grouped


# ============================================================
# 이미지 로드 / 전처리
# ============================================================

def load_image_as_rgb(image_path: Path) -> np.ndarray:
    """
    입력 이미지를 RGB numpy 배열로 로드한다.

    새 main.py가 RGB 이미지 기반으로 바뀌었으므로 preview도 동일하게 맞춤.

    처리:
    - png alpha 채널이 있으면 흰 배경에 합성
    - grayscale이면 BGR로 변환
    """

    if not image_path.exists():
        raise FileNotFoundError(f"이미지를 찾을 수 없습니다: {image_path}")

    img = cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED)

    if img is None:
        raise RuntimeError(f"이미지 로드 실패: {image_path}")

    # 4채널 PNG 등 alpha 이미지 처리
    if len(img.shape) == 3 and img.shape[2] == 4:
        alpha = img[:, :, 3] / 255.0
        rgb = img[:, :, :3]
        white_bg = np.ones_like(rgb, dtype=np.uint8) * 255
        img = (
            rgb * alpha[..., np.newaxis]
            + white_bg * (1 - alpha[..., np.newaxis])
        ).astype(np.uint8)

    # grayscale → BGR
    if len(img.shape) == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

    return img


def detect_edges(img: np.ndarray) -> np.ndarray:
    """
    이미지에 EdgeDetector를 적용해 엣지를 검출한다.
    EdgeDetector가 내부에서 BGR → grayscale 변환을 처리하므로
    RGB/BGR 이미지를 그대로 전달해도 된다.
    """
    from _input.edge_detector import EdgeDetector
    return EdgeDetector().detect(img)


# ============================================================
# JSON 저장 유틸
# ============================================================

def to_float_list(points: list[tuple[float, float, float]]) -> list[list[float]]:
    """
    tuple/np.float 값을 JSON 저장 가능한 float list로 변환한다.
    """

    result = []

    for x, y, z in points:
        result.append([
            round(float(x), 4),
            round(float(y), 4),
            round(float(z), 4),
        ])

    return result


def to_int_list(points: list[tuple[int, int]]) -> list[list[int]]:
    """
    pixel tuple을 JSON 저장 가능한 int list로 변환한다.
    """

    return [[int(u), int(v)] for u, v in points]


def sample_pixels_compat(stroke, min_dist_px: float = 2.8) -> list[tuple[int, int]]:
    """
    main.py와 동일하게 stroke.sample_pixels(min_dist_px=2.8) 기준으로 샘플링한다.

    greedy_order.py 버전 차이가 있을 수 있으므로 아래 순서대로 시도한다.
    1. sample_pixels(min_dist_px=...)
    2. sample_pixels(samples_per_curve=20, min_dist_px=...)
    3. sample_pixels()
    """

    try:
        return stroke.sample_pixels(min_dist_px=min_dist_px)
    except TypeError:
        pass

    try:
        return stroke.sample_pixels(samples_per_curve=20, min_dist_px=min_dist_px)
    except TypeError:
        pass

    return stroke.sample_pixels()


def save_path_json(
    json_path: Path,
    *,
    image_path: Path,
    image_width: int,
    image_height: int,
    image_size_px: int,
    min_area: float,
    sample_step_px: float,
    contour_count: int,
    fitted_stroke_count: int,
    bezier_segment_count: int,
    greedy_pen_up_distance_px: float,
    optimized_pen_up_distance_px: float,
    optimized_strokes: list[Any],
    rgb_img: np.ndarray,
    contours: list[np.ndarray],
    line_spacing: int = 4,
) -> None:
    """
    main.py의 실제 실행 순서와 맞춰 preview_robot_path.json을 저장한다.

    저장 순서:
    1. 윤곽선 outline stroke
       - main.py와 동일하게 optimized stroke를 sample_pixels(min_dist_px=2.8)로 샘플링
    2. 색칠 fill stroke
       - main.py와 동일하게 build_color_masks_from_contours() + raster_scan_grouped() 사용

    dashboard.js는 현재 strokes[].pixels를 읽어서 canvas에 그리므로,
    fill stroke도 같은 strokes 배열에 넣어주면 색칠 구간까지 UI에 표시된다.
    """

    strokes_data = []
    outline_point_count = 0
    fill_point_count = 0

    safe_image_size_px = max(1, int(image_size_px or 0))
    safe_sample_min_dist_px = float(sample_step_px or 2.8)

    print(
        f"[DEBUG] save_path_json image_size_px={image_size_px} "
        f"safe={safe_image_size_px} sample_min_dist_px={safe_sample_min_dist_px}"
    )

    # ------------------------------------------------------------
    # 1. 윤곽선 stroke 저장 — 실제 main.py의 optimized draw 순서와 동일
    # ------------------------------------------------------------
    for idx, stroke in enumerate(optimized_strokes):
        pixels = sample_pixels_compat(
            stroke,
            min_dist_px=safe_sample_min_dist_px,
        )

        print(
            f"[DEBUG][outline] stroke {idx} "
            f"pixels 수={len(pixels)} 첫번째={pixels[0] if pixels else 'EMPTY'}"
        )

        for i, p in enumerate(pixels):
            if not (isinstance(p, (tuple, list)) and len(p) == 2):
                print(
                    f"[DEBUG][ERROR] outline stroke {idx} pixel {i} "
                    f"형태 이상: {p} type={type(p)}"
                )
                break

        xyz_points = pixel_to_xyz_batch(
            pixels,
            0.0,
            0.0,
            safe_image_size_px,
        )

        outline_point_count += len(xyz_points)

        strokes_data.append({
            "stroke_index": len(strokes_data),
            "source_stroke_index": idx,
            "phase": "outline",
            "color": "black",
            "contour_index": int(stroke.contour_index),
            "is_reversed": bool(stroke.is_reversed),
            "pen_up_dist_px": round(float(stroke.pen_up_dist), 4),
            "point_count": len(xyz_points),
            "pixels": to_int_list(pixels),
            "xyz_points": to_float_list(xyz_points),
        })

    # ------------------------------------------------------------
    # 2. 색칠 stroke 저장 — 실제 main.py의 fill 실행 순서와 동일
    # ------------------------------------------------------------
    color_masks = build_color_masks_from_contours(rgb_img, contours)

    print(f"[DEBUG][fill] 감지된 색상 수={len(color_masks)}")

    fill_stroke_index = 0

    for color_idx, (color, mask) in enumerate(color_masks.items()):
        fill_paths = raster_scan_grouped(mask, line_spacing)

        print(
            f"[DEBUG][fill] color {color_idx} BGR={color} "
            f"fill_paths 수={len(fill_paths)}"
        )

        for path_idx, path in enumerate(fill_paths):
            pixels = [(int(u), int(v)) for u, v in path]

            if len(pixels) < 2:
                continue

            xyz_points = pixel_to_xyz_batch(
                pixels,
                0.0,
                0.0,
                safe_image_size_px,
            )

            fill_point_count += len(xyz_points)

            b, g, r = color

            strokes_data.append({
                "stroke_index": len(strokes_data),
                "source_stroke_index": fill_stroke_index,
                "phase": "fill",
                "color": "red",
                "detected_bgr": [int(b), int(g), int(r)],
                "color_index": int(color_idx),
                "fill_path_index": int(path_idx),
                "contour_index": -1,
                "is_reversed": False,
                "pen_up_dist_px": 0.0,
                "point_count": len(xyz_points),
                "pixels": to_int_list(pixels),
                "xyz_points": to_float_list(xyz_points),
            })

            fill_stroke_index += 1

    total_points = outline_point_count + fill_point_count

    data = {
        "source_image": str(image_path),
        "image_width_px": int(image_width),
        "image_height_px": int(image_height),
        "image_size_px": int(image_size_px),
        "parameters": {
            "min_contour_area": float(min_area),
            "sample_step_px": float(sample_step_px),
            "sample_min_dist_px": float(sample_step_px),
            "line_spacing": int(line_spacing),
        },
        "summary": {
            "contour_count": int(contour_count),
            "fitted_stroke_count": int(fitted_stroke_count),
            "bezier_segment_count": int(bezier_segment_count),
            "greedy_pen_up_distance_px": round(float(greedy_pen_up_distance_px), 4),
            "optimized_pen_up_distance_px": round(float(optimized_pen_up_distance_px), 4),
            "outline_stroke_count": int(len(optimized_strokes)),
            "fill_stroke_count": int(fill_stroke_index),
            "outline_point_count": int(outline_point_count),
            "fill_point_count": int(fill_point_count),
            "total_point_count": int(total_points),
        },
        "strokes": strokes_data,
    }

    json_path.parent.mkdir(parents=True, exist_ok=True)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("=" * 70)
    print("[Preview][JSON] 저장 완료")
    print(f"[Preview][JSON] outline points : {outline_point_count}")
    print(f"[Preview][JSON] fill points    : {fill_point_count}")
    print(f"[Preview][JSON] total points   : {total_points}")
    print(f"[Preview][JSON] path           : {json_path}")
    print("=" * 70)


# ============================================================
# Preview Pipeline
# ============================================================

def run_preview_pipeline(
    image_path: Path,
    output_dir: Path,
    min_area: float = 1,
    sample_step_px: float = 2.8,
) -> dict[str, Any]:
    """
    로봇을 움직이지 않고 이미지 처리/경로 생성/좌표 변환까지만 수행한다.

    Returns:
        {
            "success": True,
            "image_path": "...",
            "edges_path": "...",
            "bezier_path": "...",
            "greedy_path": "...",
            "two_opt_path": "...",
            "json_path": "...",
            "stroke_count": int,
            "total_segments": int,
        }
    """

    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("[Preview] 이미지 처리 preview 시작")
    print(f"[Preview] image_path : {image_path}")
    print(f"[Preview] output_dir : {output_dir}")
    print("=" * 70)

    # ------------------------------------------------------------------
    # 1. 이미지 로드
    # ------------------------------------------------------------------
    rgb_img = load_image_as_rgb(image_path)

    h, w = rgb_img.shape[:2]
    image_size_px = max(h, w)

    print(f"[1] 이미지 로드 완료: {w}x{h}")

    # ------------------------------------------------------------------
    # 2. 엣지 검출
    # ------------------------------------------------------------------
    edges = detect_edges(rgb_img)

    edges_path = output_dir / "preview_edges.png"
    cv2.imwrite(str(edges_path), edges)

    print(f"[2] 엣지 검출 완료: {edges_path}")

    # ------------------------------------------------------------------
    # 3. 윤곽선 추출 및 필터링
    # ------------------------------------------------------------------
    contours = filter_contours_by_area(edges, min_area=min_area)

    print(f"[3] 윤곽선 수: {len(contours)}")

    if not contours:
        raise RuntimeError(
            "윤곽선이 없습니다. 입력 이미지 또는 Canny/면적 기준을 확인하세요."
        )

    # ------------------------------------------------------------------
    # 4. Bezier 피팅
    # ------------------------------------------------------------------
    fit_results: list[BezierFitResult] = []

    for i, contour in enumerate(contours):
        curves = fit_contour(contour)

        if curves:
            fit_results.append(
                BezierFitResult(
                    curves=curves,
                    contour_index=i,
                )
            )

    total_segments = sum(len(result.curves) for result in fit_results)

    print(
        f"[4] Bezier 피팅 완료: "
        f"{len(fit_results)} 스트로크, {total_segments} 세그먼트"
    )

    fit_results = deduplicate_fit_results(fit_results, 3, 32)
    fit_results = filter_and_order_fit_results(fit_results, (h, w))
    fit_results = split_on_gaps(fit_results)

    if not fit_results:
        raise RuntimeError("Bezier 피팅 결과가 없습니다.")

    canvas = rgb_img.copy()

    bezier_vis = draw_bezier_fit_results(
        canvas,
        fit_results,
    )

    bezier_path = output_dir / "preview_bezier_fit.png"
    cv2.imwrite(str(bezier_path), bezier_vis)

    print(f"[4] Bezier 시각화 저장: {bezier_path}")

    # ------------------------------------------------------------------
    # 5. Greedy Nearest 순서 최적화
    # ------------------------------------------------------------------
    ordered = greedy_nearest(fit_results)
    greedy_distance = total_pen_up_distance(ordered)

    greedy_vis = draw_greedy_order(
        rgb_img.copy(),
        ordered,
    )

    greedy_path = output_dir / "preview_greedy_order.png"
    cv2.imwrite(str(greedy_path), greedy_vis)

    print(f"[5] Greedy 펜-업 총 거리: {greedy_distance:.1f} px")
    print(f"[5] Greedy 시각화 저장: {greedy_path}")

    # ------------------------------------------------------------------
    # 6. 2-opt 개선
    # ------------------------------------------------------------------
    optimized = two_opt(ordered)
    optimized_distance = total_pen_up_distance(optimized)

    improvement = (
        (greedy_distance - optimized_distance)
        / max(greedy_distance, 1.0)
        * 100.0
    )

    opt_vis = draw_greedy_order(
        rgb_img.copy(),
        optimized,
    )

    two_opt_path = output_dir / "preview_two_opt.png"
    cv2.imwrite(str(two_opt_path), opt_vis)

    print(
        f"[6] 2-opt 펜-업 총 거리: {optimized_distance:.1f} px "
        f"(개선: {improvement:.1f}%)"
    )
    print(f"[6] 2-opt 시각화 저장: {two_opt_path}")

    # ------------------------------------------------------------------
    # 7. pixel → robot XYZ 좌표 변환 결과 JSON 저장
    # ------------------------------------------------------------------
    json_path = output_dir / "preview_robot_path.json"

    save_path_json(
        json_path,
        image_path=image_path,
        image_width=w,
        image_height=h,
        image_size_px=image_size_px,
        min_area=min_area,
        sample_step_px=sample_step_px,
        contour_count=len(contours),
        fitted_stroke_count=len(fit_results),
        bezier_segment_count=total_segments,
        greedy_pen_up_distance_px=greedy_distance,
        optimized_pen_up_distance_px=optimized_distance,
        optimized_strokes=optimized,
        rgb_img=rgb_img,
        contours=contours,
        line_spacing=4,
    )

    print(f"[7] 좌표 JSON 저장: {json_path}")
    print("[7] 로봇 실행은 하지 않았습니다.")
    print("=" * 70)
    print("[Preview] 완료")
    print("=" * 70)

    return {
        "success": True,
        "image_path": str(image_path),
        "edges_path": str(edges_path),
        "bezier_path": str(bezier_path),
        "greedy_path": str(greedy_path),
        "two_opt_path": str(two_opt_path),
        "json_path": str(json_path),
        "stroke_count": len(fit_results),
        "total_segments": total_segments,
        "greedy_pen_up_distance_px": greedy_distance,
        "optimized_pen_up_distance_px": optimized_distance,
    }


# ============================================================
# CLI
# ============================================================

def parse_args() -> argparse.Namespace:
    default_image_path = _ROOT / "_input" / "test.png"
    default_output_dir = _ROOT / "_input" / "preview_output"

    parser = argparse.ArgumentParser(
        description=(
            "Doosan M0609 drawing preview pipeline. "
            "로봇을 움직이지 않고 이미지 처리/좌표 생성까지만 수행합니다."
        )
    )

    parser.add_argument(
        "--image",
        default=str(default_image_path),
        help="입력 이미지 경로. 기본값: _input/test.png",
    )

    parser.add_argument(
        "--output",
        default=str(default_output_dir),
        help="결과 저장 폴더. 기본값: _input/preview_output",
    )

    parser.add_argument(
        "--low-threshold",
        type=int,
        default=50,
        help="Canny low threshold",
    )

    parser.add_argument(
        "--high-threshold",
        type=int,
        default=150,
        help="Canny high threshold",
    )

    parser.add_argument(
        "--min-area",
        type=float,
        default=1.0,
        help="contour 최소 면적",
    )

    parser.add_argument(
        "--sample-step-px",
        type=float,
        default=2.8,
        help="main.py와 동일한 stroke 샘플링 최소 간격(px). 기본값: 2.8",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    image_path = Path(args.image).expanduser().resolve()
    output_dir = Path(args.output).expanduser().resolve()

    try:
        result = run_preview_pipeline(
            image_path=image_path,
            output_dir=output_dir,

            min_area=args.min_area,
            sample_step_px=args.sample_step_px,
        )

        print("[Preview] result:")
        print(json.dumps(result, ensure_ascii=False, indent=2))

    except Exception as e:
        print(f"[Preview][ERROR] {e}")
        raise


if __name__ == "__main__":
    main()