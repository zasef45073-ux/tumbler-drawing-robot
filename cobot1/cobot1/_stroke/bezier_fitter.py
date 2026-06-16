import cv2
import numpy as np
from dataclasses import dataclass
from pathlib import Path

from _stroke.contour_extractor import extract_contours, filter_contours_by_area


@dataclass
class BezierCurve:
    """3차 베지어 곡선 하나를 담는 데이터 클래스.

    Attributes:
        control_points: 베지어 곡선의 제어점 4개. shape=(4, 2), dtype=float64.
                        순서는 [P0(시작), P1(제어1), P2(제어2), P3(끝)].
    """

    control_points: np.ndarray

@dataclass
class BezierFitResult:
    """윤곽선 하나에서 피팅된 베지어 곡선 묶음."""

    curves: list[BezierCurve]
    contour_index: int


def quantize(v: float, precision: int = 10) -> int:
    """precision=10 → 0.1 단위, precision=100 → 0.01 단위"""
    return int(round(v * precision))


def make_key(curve: BezierCurve, precision: int = 1000) -> str:
    """베지어 곡선을 문자열 key로 변환한다. 역방향도 동일한 key를 반환한다."""
    p0, p1, p2, p3 = curve.control_points

    rev = p3[0] < p0[0] or (p3[0] == p0[0] and p3[1] < p0[1])
    pts = [p3, p2, p1, p0] if rev else [p0, p1, p2, p3]

    parts = [f"{quantize(p[0], precision)},{quantize(p[1], precision)}" for p in pts]
    return "|".join(parts)

def make_curve_key(
    curve: BezierCurve,
    precision: int = 10,
    samples: int = 20,
) -> str:
    """베지어 곡선을 샘플링 기반 문자열 key로 변환한다.

    제어점(control point) 자체가 아니라 실제 곡선 위의 샘플 점들을 기준으로
    key를 생성하므로, 제어점이 조금 달라도 동일한 경로를 그리는 곡선을
    더 안정적으로 중복 제거할 수 있다.

    역방향 곡선도 동일한 key를 반환한다.

    Args:
        curve:      키를 생성할 BezierCurve.
        precision:  좌표 양자화 정밀도.
                    precision=10   → 0.1 단위
                    precision=100  → 0.01 단위
                    precision=1000 → 0.001 단위
        samples:    곡선 위에서 샘플링할 점 개수.
                    값이 클수록 비교 정확도는 높아지지만 key 길이와
                    계산 비용도 증가한다.

    Returns:
        샘플링된 곡선 경로를 나타내는 문자열 key.
    """
    t = np.linspace(0.0, 1.0, samples)
    pts = _eval_cubic(curve.control_points, t)

    parts = [
        f"{quantize(p[0], precision)},{quantize(p[1], precision)}"
        for p in pts
    ]

    # 역방향 곡선도 동일한 key를 갖도록 정규화
    rev_parts = list(reversed(parts))

    return min("|".join(parts), "|".join(rev_parts))


def _chord_parameterize(pts: np.ndarray) -> np.ndarray:
    """점 시퀀스를 현(chord) 길이 기준으로 [0, 1] 파라미터화한다."""
    diffs = np.diff(pts, axis=0)
    seg_len = np.hypot(diffs[:, 0], diffs[:, 1])
    # zero-length 세그먼트(중복 스트로크)는 미세 오프셋으로 대체해 t 중복을 방지한다
    seg_len = np.where(seg_len < 1e-10, 1e-10, seg_len)
    cum = np.concatenate([[0.0], np.cumsum(seg_len)])
    return cum / cum[-1]


def _fit_cubic(pts: np.ndarray, t: np.ndarray) -> np.ndarray:
    """점 배열과 파라미터 t로 3차 베지어 제어점을 최소제곱 피팅한다.

    P0=pts[0], P3=pts[-1]로 고정하고 P1, P2를 구한다.

    Returns:
        shape=(4, 2)의 제어점 배열 [P0, P1, P2, P3].
    """
    p0, p3 = pts[0].astype(float), pts[-1].astype(float)
    b1 = 3.0 * t * (1.0 - t) ** 2
    b2 = 3.0 * t**2 * (1.0 - t)

    rhs = pts.astype(float) - np.outer((1.0 - t) ** 3, p0) - np.outer(t**3, p3)
    A = np.column_stack([b1, b2])  # (N, 2)
    ATA = A.T @ A

    if abs(np.linalg.det(ATA)) < 1e-10:
        p1 = p0 + (p3 - p0) / 3.0
        p2 = p0 + 2.0 * (p3 - p0) / 3.0
    else:
        # ATA @ [[P1x,P1y],[P2x,P2y]] = A.T @ rhs
        sol = np.linalg.solve(ATA, A.T @ rhs)
        p1, p2 = sol[0], sol[1]

    return np.array([p0, p1, p2, p3])


def _eval_cubic(ctrl: np.ndarray, t: np.ndarray) -> np.ndarray:
    """3차 베지어 곡선을 t 값에서 평가한다."""
    p0, p1, p2, p3 = ctrl
    return (
        np.outer((1.0 - t) ** 3, p0)
        + np.outer(3.0 * t * (1.0 - t) ** 2, p1)
        + np.outer(3.0 * t**2 * (1.0 - t), p2)
        + np.outer(t**3, p3)
    )


def _make_line(p0: np.ndarray, p3: np.ndarray) -> np.ndarray:
    """P0→P3 직선을 나타내는 3차 베지어 제어점을 반환한다."""
    return np.array([p0, p0 + (p3 - p0) / 3.0, p0 + 2.0 * (p3 - p0) / 3.0, p3])


def _find_corners(pts: np.ndarray, angle_thresh_deg: float = 25.0, window: int = 4) -> list[int]:
    """방향이 급격히 바뀌는 코너 인덱스를 반환한다 (NMS 적용)."""
    n = len(pts)
    if n < 3:
        return []

    angles = []
    for i in range(1, n - 1):
        i0 = max(0, i - window)
        i1 = min(n - 1, i + window)
        v1 = pts[i] - pts[i0]
        v2 = pts[i1] - pts[i]
        len1 = np.hypot(*v1)
        len2 = np.hypot(*v2)
        if len1 < 1e-10 or len2 < 1e-10:
            angles.append(0.0)
            continue
        cos_a = np.clip(np.dot(v1, v2) / (len1 * len2), -1.0, 1.0)
        angles.append(np.degrees(np.arccos(cos_a)))

    corners = []
    for i, a in enumerate(angles):
        if a <= angle_thresh_deg:
            continue
        lo = max(0, i - window)
        hi = min(len(angles) - 1, i + window)
        if a == max(angles[lo : hi + 1]):  # 로컬 최댓값만 채택
            corners.append(i + 1)  # angles[i]는 pts[i+1]에 해당
    return corners


def _split_fit(pts: np.ndarray, error_thresh: float, depth: int) -> list[np.ndarray]:
    """재귀 분할로 점 배열을 베지어 세그먼트 목록으로 피팅한다.

    직선으로 근사 가능하면 직선, 아니면 3차 베지어 곡선을 사용한다.
    """
    if len(pts) < 2:
        return []
    
    p0, p3 = pts[0].astype(float), pts[-1].astype(float)
    t = _chord_parameterize(pts)

    # 직선 오차 먼저 확인 — 충분히 작으면 직선으로 처리
    straight = np.outer(1.0 - t, p0) + np.outer(t, p3)
    if np.hypot(*(pts.astype(float) - straight).T).max() <= error_thresh:
        return [_make_line(p0, p3)]

    if len(pts) == 2:
        return [_make_line(p0, p3)]

    ctrl = _fit_cubic(pts, t)
    fitted = _eval_cubic(ctrl, t)
    errors = np.hypot(*(pts.astype(float) - fitted).T)

    if errors.max() <= error_thresh or depth <= 0:
        return [ctrl]

    mid = int(np.argmax(errors))
    mid = max(1, min(mid, len(pts) - 2))
    return _split_fit(pts[: mid + 1], error_thresh, depth - 1) + _split_fit(
        pts[mid:], error_thresh, depth - 1
    )

def fit_contour(
    contour: np.ndarray,
    error_thresh: float = 3.0,
    max_depth: int = 8,
    corner_angle_thresh: float = 25.0,
) -> list[BezierCurve]:
    """OpenCV 윤곽선 하나를 3차 베지어 곡선 목록으로 피팅한다.

    Args:
        contour:             OpenCV 윤곽선. shape=(N, 1, 2).
        error_thresh:        허용 최대 픽셀 오차. 작을수록 세그먼트가 더 많이 생긴다.
        max_depth:           재귀 분할 최대 깊이 (최대 2^max_depth 세그먼트).
        corner_angle_thresh: 이 각도(도) 이상으로 꺾이면 코너로 분리한다.
                             직선 도형(사각형 등)을 정확히 표현하려면 낮출 것.

    Returns:
        BezierCurve 리스트.
    """
    pts = contour.reshape(-1, 2).astype(float)
    # 연속 중복점 제거 (순서 보존)
    mask = np.ones(len(pts), dtype=bool)
    mask[1:] = np.any(pts[1:] != pts[:-1], axis=1)
    pts = pts[mask]
    if len(pts) < 2:
        return []

    # 코너에서 미리 분할해 직선 구간이 곡선으로 묶이지 않도록 한다
    corners = _find_corners(pts, corner_angle_thresh)
    split_indices = sorted(set([0] + corners + [len(pts) - 1]))

    curves = []
    for i in range(len(split_indices) - 1):
        seg = pts[split_indices[i] : split_indices[i + 1] + 1]
        if len(seg) >= 2:
            curves.extend(BezierCurve(ctrl) for ctrl in _split_fit(seg, error_thresh, max_depth))

    # 닫힌 윤곽선의 마지막 선분(pts[-1] → pts[0]) 추가
    if not np.allclose(pts[-1], pts[0]):
        closing_seg = np.array([pts[-1], pts[0]])
        curves.extend(
            BezierCurve(ctrl) for ctrl in _split_fit(closing_seg, error_thresh, max_depth)
        )
    return curves


def deduplicate_curves(
    curves: list[BezierCurve],
    precision: int = 10,
    samples: int = 20,
) -> list[BezierCurve]:
    """동일한 경로를 그리는 중복 베지어 곡선을 제거한다 (순서 보존).

    제어점(control point) 자체가 아니라 실제 곡선 샘플 경로를 기준으로
    비교하므로, 제어점이 조금 달라도 같은 경로를 그리는 곡선을
    안정적으로 제거할 수 있다.

    방향이 반대여도 같은 경로로 간주한다.
    """
    seen: set[str] = set()
    result: list[BezierCurve] = []

    for curve in curves:
        key = make_curve_key(
            curve,
            precision=precision,
            samples=samples,
        )

        if key not in seen:
            seen.add(key)
            result.append(curve)

    return result


def deduplicate_fit_results(
    fit_results: list[BezierFitResult],
    precision: int = 10,
    samples: int = 32,
) -> list[BezierFitResult]:
    """BezierFitResult 목록 전체에서 중복 곡선을 제거한다.

    곡선 샘플 기반 key를 사용해 동일 경로를 안정적으로 판별한다.
    """
    seen: set[str] = set()
    out: list[BezierFitResult] = []

    for result in fit_results:
        unique: list[BezierCurve] = []

        for curve in result.curves:
            key = make_curve_key(
                curve,
                precision=precision,
                samples=samples,
            )

            if key not in seen:
                seen.add(key)
                unique.append(curve)

        if unique:
            out.append(
                BezierFitResult(
                    curves=unique,
                    contour_index=result.contour_index,
                )
            )

    return out

class PaintedMask:
    """이미 그려진 픽셀을 추적해 겹침 비율을 계산한다."""

    def __init__(self, shape: tuple[int, int]):
        self.mask = np.zeros(shape, dtype=np.uint8)

    def overlap_ratio(self, curve: BezierCurve, samples: int = 100) -> float:
        """곡선이 이미 그려진 영역과 겹치는 비율 (0.0~1.0)."""
        t = np.linspace(0.0, 1.0, samples)
        pts = _eval_cubic(curve.control_points, t).astype(np.int32)
        h, w = self.mask.shape
        total, painted = 0, 0
        for p in pts:
            x, y = int(p[0]), int(p[1])
            if 0 <= x < w and 0 <= y < h:
                total += 1
                if self.mask[y, x] > 0:
                    painted += 1
        return painted / total if total > 0 else 0.0

    def paint(self, curve: BezierCurve, thickness: int = 3, samples: int = 100) -> None:
        """곡선을 마스크에 등록한다."""
        t = np.linspace(0.0, 1.0, samples)
        pts = _eval_cubic(curve.control_points, t).astype(np.int32)
        for j in range(len(pts) - 1):
            cv2.line(self.mask, tuple(pts[j]), tuple(pts[j + 1]), 255, thickness)


def filter_and_order_fit_results(
    fit_results: list[BezierFitResult],
    canvas_shape: tuple[int, int],
    overlap_threshold: float = 0.6,
    mask_thickness: int = 3,
) -> list[BezierFitResult]:
    """PaintedMask로 겹치는 곡선을 필터링한다. 스트로크 경계는 보존된다.

    문제 1, 2를 해결하고 문제 3(역방향 재진입)은 force_directed_path / two_opt에 위임한다:
    1. 닫힌 루프 컨투어의 겹치는 구간 — PaintedMask로 필터
    2. 인접 컨투어 공유 선분 — PaintedMask로 필터

    Args:
        fit_results:       deduplicate_fit_results 결과.
        canvas_shape:      (H, W) 캔버스 크기. PaintedMask에 사용.
        overlap_threshold: 이 비율 이상 겹치면 해당 곡선을 스킵 (0.0~1.0).
        mask_thickness:    PaintedMask 등록 시 선 두께 (픽셀).

    Returns:
        겹침 곡선이 제거된 BezierFitResult 목록. 스트로크 경계 보존.
    """
    painted = PaintedMask(canvas_shape)
    out: list[BezierFitResult] = []

    for result in fit_results:
        surviving: list[BezierCurve] = []
        for curve in result.curves:
            if painted.overlap_ratio(curve) < overlap_threshold:
                painted.paint(curve, thickness=mask_thickness)
                surviving.append(curve)
        if surviving:
            out.append(BezierFitResult(curves=surviving, contour_index=result.contour_index))

    return out


def split_on_gaps(
    fit_results: list[BezierFitResult],
    gap_threshold_px: float = 5.0,
) -> list[BezierFitResult]:
    """불연속 구간이 있는 스트로크를 개별 스트로크로 분리한다.

    중복 제거/필터링 후 BezierFitResult 내부에 끊긴 구간이 생길 수 있다.
    curve[i] 끝점과 curve[i+1] 시작점 거리가 gap_threshold_px를 초과하면 분리.
    """
    out: list[BezierFitResult] = []
    for result in fit_results:
        group: list[BezierCurve] = [result.curves[0]]
        for i in range(1, len(result.curves)):
            prev_end = result.curves[i - 1].control_points[3]
            curr_start = result.curves[i].control_points[0]
            dist = float(np.hypot(curr_start[0] - prev_end[0], curr_start[1] - prev_end[1]))
            if dist > gap_threshold_px:
                out.append(BezierFitResult(curves=group, contour_index=result.contour_index))
                group = []
            group.append(result.curves[i])
        if group:
            out.append(BezierFitResult(curves=group, contour_index=result.contour_index))
    return out


def draw_bezier_fit_results(
    canvas: np.ndarray,
    fit_results: list[BezierFitResult],
    color: tuple[int, int, int] = (0, 0, 255),
    thickness: int = 2,
    samples: int = 100,
) -> np.ndarray:
    """BezierFitResult 목록을 캔버스에 그려 반환한다."""
    t_vals = np.linspace(0.0, 1.0, samples)
    out = canvas.copy()
    for result in fit_results:
        for curve in result.curves:
            pts = _eval_cubic(curve.control_points, t_vals).astype(np.int32)
            for j in range(len(pts) - 1):
                cv2.line(out, tuple(pts[j]), tuple(pts[j + 1]), color, thickness)
    return out



