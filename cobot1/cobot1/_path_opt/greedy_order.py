"""Greedy Nearest Neighbor 경로 최적화.

BezierFitResult 목록(윤곽선 단위 스트로크)을 받아서
펜-업 이동 거리의 합이 최소가 되도록 방문 순서를 정한다.

각 스트로크는 순방향/역방향 둘 다 접근 가능하므로
현재 위치에서 각 스트로크의 시작점·끝점 중 더 가까운 쪽을 선택한다.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / "_stroke"))
from bezier_fitter import BezierCurve, BezierFitResult, _eval_cubic  # type: ignore[import]

@dataclass
class OrderedStroke:
    """방문 순서가 결정된 스트로크 하나.

    Attributes:
        curves:         순회 방향으로 정렬된 BezierCurve 목록.
        contour_index:  원본 윤곽선 인덱스.
        is_reversed:    원본 순서 대비 역방향 순회 여부.
        pen_up_dist:    이 스트로크 직전 펜-업 이동 거리 (첫 스트로크는 0).
    """

    curves: list[BezierCurve]
    contour_index: int
    is_reversed: bool
    pen_up_dist: float

    def sample_pixels(self, samples_per_curve: int = 20, min_dist_px: float = 5.0) -> list[tuple[int, int]]:
        t = np.linspace(0.0, 1.0, samples_per_curve)
        pixels: list[tuple[int, int]] = []
        last: tuple[int, int] | None = None
        for curve in self.curves:
            pts = _eval_cubic(curve.control_points, t).astype(int)
            for p in pts:
                pt = (int(p[0]), int(p[1]))
                if last is None or np.hypot(pt[0] - last[0], pt[1] - last[1]) >= min_dist_px:
                    pixels.append(pt)
                    last = pt
        return pixels


def _endpoints(result: BezierFitResult) -> tuple[np.ndarray, np.ndarray]:
    """스트로크의 시작점(P0)과 끝점(P3)을 반환한다."""
    return (
        result.curves[0].control_points[0].astype(float),
        result.curves[-1].control_points[3].astype(float),
    )


def _reverse_stroke(result: BezierFitResult) -> list[BezierCurve]:
    """스트로크를 역방향으로 뒤집어 BezierCurve 목록을 반환한다.

    곡선 순서를 뒤집고, 각 곡선의 제어점도 [P3,P2,P1,P0] 순으로 반전한다.
    """
    return [
        BezierCurve(curve.control_points[::-1].copy())
        for curve in reversed(result.curves)
    ]

# 추가 
def greedy_nearest(
    fit_results: list[BezierFitResult],
    start_pos: np.ndarray | None = None,
) -> list[OrderedStroke]:
    """Greedy Nearest Neighbor 알고리즘으로 스트로크 방문 순서를 결정한다.

    O(N^2) 시간 복잡도. 수백~수천 개 스트로크에 적합하다.

    Args:
        fit_results: bezier_fitter.fit_contours() 반환값.
        start_pos:   로봇 팔의 초기 위치 (픽셀 좌표 [x, y]).
                     None이면 첫 스트로크의 시작점을 사용한다.

    Returns:
        방문 순서대로 정렬된 OrderedStroke 리스트.
    """
    if not fit_results:
        return []

    # 미방문 스트로크 인덱스 풀 — 선택될 때마다 제거된다
    unvisited = list(range(len(fit_results)))
    ordered: list[OrderedStroke] = []

    # start_pos 미지정 시 첫 스트로크 P0을 출발점으로 사용
    if start_pos is None:
        current = fit_results[0].curves[0].control_points[0].astype(float)
    else:
        current = np.asarray(start_pos, dtype=float)

    while unvisited:
        # 현재 위치에서 가장 가까운 스트로크를 고르는 argmin 탐색
        best_i: int = unvisited[0]
        best_dist = float("inf")
        best_reversed = False

        for i in unvisited:
            p_start, p_end = _endpoints(fit_results[i])

            # 시작점·끝점 중 더 가까운 쪽을 택해 순방향/역방향 결정
            d_start = float(np.hypot(*(current - p_start)))
            d_end = float(np.hypot(*(current - p_end)))

            if d_start <= d_end:
                dist, rev = d_start, False
            else:
                dist, rev = d_end, True

            if dist < best_dist:
                best_dist = dist
                best_i = i
                best_reversed = rev

        result = fit_results[best_i]
        # 역방향 선택 시 곡선 목록과 각 제어점을 함께 반전한다
        curves = _reverse_stroke(result) if best_reversed else list(result.curves)

        ordered.append(
            OrderedStroke(
                curves=curves,
                contour_index=result.contour_index,
                is_reversed=best_reversed,
                pen_up_dist=best_dist,
            )
        )

        # 다음 탐색 기준점을 방금 방문한 스트로크의 끝점(P3)으로 전진
        current = curves[-1].control_points[3].astype(float)
        unvisited.remove(best_i)

    return ordered
def _draw_dashed_line(img, pt1, pt2, color, thickness=5, dash_len=10, gap_len=5):
    import cv2
    pt1 = np.asarray(pt1, dtype=float)
    pt2 = np.asarray(pt2, dtype=float)
    d = pt2 - pt1
    length = float(np.hypot(d[0], d[1]))
    if length < 1e-5:
        return
    step = dash_len + gap_len
    for k in range(int(length / step) + 1):
        t0 = k * step / length
        t1 = min((k * step + dash_len) / length, 1.0)
        p0 = tuple((pt1 + t0 * d).astype(np.int32))
        p1 = tuple((pt1 + t1 * d).astype(np.int32))
        cv2.line(img, p0, p1, color, thickness, cv2.LINE_AA)


def draw_greedy_order(
    canvas: np.ndarray,
    ordered: list[OrderedStroke],
) -> np.ndarray:
    """Greedy 경로 순서를 시각화한 이미지를 반환한다.

    스트로크는 파란~청록 계열 색상으로, 펜-업 이동은 빨간 점선으로 그린다.
    """
    import cv2

    out = canvas.copy()
    n = len(ordered)
    t_vals = np.linspace(0.0, 1.0, 60)

    for idx, stroke in enumerate(ordered):
        hue = int(90 + 40 * idx / max(n - 1, 1))
        color_hsv = np.array([[[hue, 230, 200]]], dtype=np.uint8)
        b, g, r = cv2.cvtColor(color_hsv, cv2.COLOR_HSV2BGR)[0, 0]
        stroke_color = (int(b), int(g), int(r))

        all_pts: list[np.ndarray] = []
        for curve in stroke.curves:
            pts = _eval_cubic(curve.control_points, t_vals).astype(np.int32)
            for j in range(len(pts) - 1):
                cv2.line(out, tuple(pts[j]), tuple(pts[j + 1]), stroke_color, 1)
            all_pts.append(pts)

        flat_pts = np.concatenate(all_pts, axis=0)
        if len(flat_pts) >= 2:
            mid = len(flat_pts) // 2
            p_tail = tuple(flat_pts[mid - 1])
            p_head = tuple(flat_pts[min(mid + 1, len(flat_pts) - 1)])
            cv2.arrowedLine(out, p_tail, p_head, stroke_color, 2, cv2.LINE_AA, tipLength=0.6)

        cv2.circle(out, tuple(flat_pts[0]), 3, (255, 255, 255), -1, cv2.LINE_AA)

        if idx > 0:
            prev_end = ordered[idx - 1].curves[-1].control_points[3].astype(float)
            cur_start = stroke.curves[0].control_points[0].astype(float)
            _draw_dashed_line(out, prev_end, cur_start, (0, 0, 255), 1)

    return out

def total_pen_up_distance(ordered: list[OrderedStroke]) -> float:
    """정렬된 스트로크 목록의 펜-업 이동 거리 합계를 반환한다."""
    return sum(s.pen_up_dist for s in ordered)


# ---------------------------------------------------------------------------
# 간단한 CLI 테스트
# ---------------------------------------------------------------------------
if __name__ == "__main__":

    import cv2
    from contour_extractor import extract_from_file  # type: ignore[import]
    from bezier_fitter import fit_contours  # type: ignore[import]

    vis_image, contours = extract_from_file(path)
    fit_results = fit_contours(contours)

    print(f"스트로크 수: {len(fit_results)}")

    ordered = greedy_nearest(fit_results)
    total = total_pen_up_distance(ordered)
    print(f"Greedy 펜-업 총 거리: {total:.1f} px")

    # 순서대로 색상을 변화시켜 시각화
    canvas = vis_image.copy()
    n = len(ordered)
    t_vals = np.linspace(0.0, 1.0, 60)

    from bezier_fitter import _eval_cubic  # noqa: PLC0415

    for idx, stroke in enumerate(ordered):
        # 스트로크: 파란색~청록색 계열 (hue 90~130)
        hue = int(90 + 40 * idx / max(n - 1, 1))
        color_hsv = np.array([[[hue, 230, 200]]], dtype=np.uint8)
        b, g, r = cv2.cvtColor(color_hsv, cv2.COLOR_HSV2BGR)[0, 0]
        stroke_color = (int(b), int(g), int(r))

        all_pts: list[np.ndarray] = []
        for curve in stroke.curves:
            pts = _eval_cubic(curve.control_points, t_vals).astype(np.int32)
            for j in range(len(pts) - 1):
                cv2.line(canvas, tuple(pts[j]), tuple(pts[j + 1]), stroke_color, 1)
            all_pts.append(pts)

        # 방향 화살표: 스트로크 중간 지점에 표시
        flat_pts = np.concatenate(all_pts, axis=0)
        if len(flat_pts) >= 2:
            mid = len(flat_pts) // 2
            p_tail = tuple(flat_pts[mid - 1])
            p_head = tuple(flat_pts[min(mid + 1, len(flat_pts) - 1)])
            cv2.arrowedLine(canvas, p_tail, p_head, stroke_color, 2, cv2.LINE_AA, tipLength=0.6)

        # 시작점 표시 (흰색 원)
        start_pt = tuple(flat_pts[0])
        cv2.circle(canvas, start_pt, 3, (255, 255, 255), -1, cv2.LINE_AA)

        # 펜-업 경로: 빨간색 점선
        if idx > 0:
            prev_end = ordered[idx - 1].curves[-1].control_points[3].astype(float)
            cur_start = stroke.curves[0].control_points[0].astype(float)
            _draw_dashed_line(canvas, prev_end, cur_start, (0, 0, 255), 1)

    out_path = Path(path).stem + "_greedy.png"
    cv2.imwrite(out_path, canvas)
    print(f"저장 완료: {out_path}")

    cv2.imshow("Greedy Order", canvas)
    cv2.waitKey(0)
    cv2.destroyAllWindows()
