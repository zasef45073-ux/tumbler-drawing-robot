"""2-opt 경로 개선 알고리즘.

greedy_order.py 로 얻은 OrderedStroke 리스트를 받아
2-opt 스왑을 반복 적용해 펜-업 이동 거리 합계를 줄인다.

각 스트로크는 역방향 접근이 허용되므로,
구간을 뒤집을 때 구간 내 스트로크 방향도 함께 반전한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / "_stroke"))
from bezier_fitter import BezierCurve  # type: ignore[import]

sys.path.insert(0, str(Path(__file__).parent))
from greedy_order import OrderedStroke, total_pen_up_distance  # type: ignore[import]
from cost_function import edge_cost, two_opt_gain, _sstart, _send  # type: ignore[import]

def _flip(s: OrderedStroke) -> OrderedStroke:
    """스트로크 방향을 반전한다 (is_reversed 토글, 제어점 역순)."""
    flipped = [
        BezierCurve(c.control_points[::-1].copy())
        for c in reversed(s.curves)
    ]
    return OrderedStroke(
        curves=flipped,
        contour_index=s.contour_index,
        is_reversed=not s.is_reversed,
        pen_up_dist=s.pen_up_dist,
    )


def _recalc_pen_up(
    strokes: list[OrderedStroke],
    start_pos: np.ndarray | None,
) -> list[OrderedStroke]:
    """전체 pen_up_dist를 재계산한다."""
    if not strokes:
        return []

    prev = (np.asarray(start_pos, dtype=float) if start_pos is not None
            else _sstart(strokes[0]))

    result: list[OrderedStroke] = []
    for s in strokes:
        cur = _sstart(s)
        dist = edge_cost(prev, cur)
        result.append(OrderedStroke(
            curves=s.curves,
            contour_index=s.contour_index,
            is_reversed=s.is_reversed,
            pen_up_dist=dist,
        ))
        prev = _send(s)

    return result


# ---------------------------------------------------------------------------
# 2-opt
# ---------------------------------------------------------------------------
def two_opt(
    ordered: list[OrderedStroke],
    start_pos: np.ndarray | None = None,
    max_iter: int = 500,
    threshold: float = 1e-6,
) -> list[OrderedStroke]:
    """2-opt 경로 개선 알고리즘.

    greedy_nearest()가 반환한 순서를 입력받아
    펜-업 이동 거리의 합이 줄어드는 2-opt 스왑을 반복 적용한다.
    First-improvement 전략 사용: 개선이 발견되면 즉시 적용하고 재탐색한다.

    원리 — 현재 두 엣지 (ei→ss, ej→sj1) 를 제거하고
    (ei→ej, ss→sj1) 로 교체하면 구간 [seg, j] 가 뒤집히며
    그 안의 각 스트로크 방향도 함께 반전된다.

    Args:
        ordered:    greedy_nearest()가 반환한 OrderedStroke 리스트.
        start_pos:  로봇 팔의 초기 위치 (픽셀 좌표 [x, y]).
                    제공하면 첫 이동 엣지(start_pos→s₀)도 최적화 대상에 포함한다.
        max_iter:   반복 상한. 대부분 수십 회 이내에 수렴한다.
        threshold:  이 값 이상 줄어들 때만 스왑을 적용한다.

    Returns:
        개선된 OrderedStroke 리스트 (pen_up_dist 재계산 포함).
    """
    n = len(ordered)
    if n < 3:
        return list(ordered)

    strokes = list(ordered)

    # start_pos 가 주어지면 i = -1(가상 시작 노드) 도 탐색 대상에 포함
    i_start = -1 if start_pos is not None else 0

    for _ in range(max_iter):
        improved = False

        for i in range(i_start, n - 2):
            seg = i + 1
            for j in range(seg + 1, n):
                gain = two_opt_gain(strokes, i, j, start_pos)

                if gain > threshold:
                    # [seg, j] 구간 역전 + 각 스트로크 방향 반전
                    strokes[seg:j + 1] = [
                        _flip(s) for s in reversed(strokes[seg:j + 1])
                    ]
                    improved = True
                    break

            if improved:
                break

        if not improved:
            break

    return _recalc_pen_up(strokes, start_pos)


# ---------------------------------------------------------------------------
# 간단한 CLI 테스트
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys as _sys

    if len(_sys.argv) < 2:
        print("사용법: python two_opt.py <이미지 경로>")
        _sys.exit(1)

    import cv2
    from contour_extractor import extract_from_file  # type: ignore[import]
    from bezier_fitter import fit_contours, _eval_cubic  # type: ignore[import]
    from greedy_order import greedy_nearest  # type: ignore[import]

    path = _sys.argv[1]
    vis_image, contours = extract_from_file(path)
    fit_results = fit_contours(contours)

    print(f"스트로크 수: {len(fit_results)}")

    greedy = greedy_nearest(fit_results)
    d_greedy = total_pen_up_distance(greedy)
    print(f"Greedy 펜-업 총 거리: {d_greedy:.1f} px")

    optimized = two_opt(greedy)
    d_opt = total_pen_up_distance(optimized)
    print(f"2-opt  펜-업 총 거리: {d_opt:.1f} px")
    if d_greedy > 0:
        print(f"개선율: {(d_greedy - d_opt) / d_greedy * 100:.1f} %")

    # 시각화 ---------------------------------------------------------------
    t_vals = np.linspace(0.0, 1.0, 60)

    def _draw_dashed(img, pt1, pt2, color, thickness=1):
        d = (pt2 - pt1).astype(float)
        length = float(np.hypot(d[0], d[1]))
        if length < 1e-5:
            return
        dash_len, gap_len = 10, 5
        step = dash_len + gap_len
        for k in range(int(length / step) + 1):
            t0 = k * step / length
            t1 = min((k * step + dash_len) / length, 1.0)
            p0 = tuple((pt1 + t0 * d).astype(np.int32))
            p1 = tuple((pt1 + t1 * d).astype(np.int32))
            cv2.line(img, p0, p1, color, thickness, cv2.LINE_AA)

    canvas = vis_image.copy()
    n_strokes = len(optimized)

    for idx, stroke in enumerate(optimized):
        hue = int(90 + 40 * idx / max(n_strokes - 1, 1))
        color_hsv = np.array([[[hue, 230, 200]]], dtype=np.uint8)
        b, g, r = cv2.cvtColor(color_hsv, cv2.COLOR_HSV2BGR)[0, 0]
        stroke_color = (int(b), int(g), int(r))

        all_pts: list[np.ndarray] = []
        for curve in stroke.curves:
            pts = _eval_cubic(curve.control_points, t_vals).astype(np.int32)
            for k in range(len(pts) - 1):
                cv2.line(canvas, tuple(pts[k]), tuple(pts[k + 1]), stroke_color, 1)
            all_pts.append(pts)

        flat_pts = np.concatenate(all_pts, axis=0)
        if len(flat_pts) >= 2:
            mid = len(flat_pts) // 2
            p_tail = tuple(flat_pts[mid - 1])
            p_head = tuple(flat_pts[min(mid + 1, len(flat_pts) - 1)])
            cv2.arrowedLine(canvas, p_tail, p_head, stroke_color, 2, cv2.LINE_AA, tipLength=0.6)

        cv2.circle(canvas, tuple(flat_pts[0]), 3, (255, 255, 255), -1, cv2.LINE_AA)

        if idx > 0:
            prev_end = optimized[idx - 1].curves[-1].control_points[3].astype(float)
            cur_start = stroke.curves[0].control_points[0].astype(float)
            _draw_dashed(canvas, prev_end, cur_start, (0, 0, 255))

    out_path = Path(path).stem + "_2opt.png"
    cv2.imwrite(out_path, canvas)
    print(f"저장 완료: {out_path}")

    cv2.imshow("2-opt Order", canvas)
    cv2.waitKey(0)
    cv2.destroyAllWindows()
