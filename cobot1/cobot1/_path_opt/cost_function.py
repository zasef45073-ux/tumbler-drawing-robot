"""경로 비용 함수 모음.

펜-업 엣지 비용, 2-opt 스왑 이득, 전체 경로 비용을 중앙화하여
greedy_order.py · two_opt.py 등에서 임포트해 사용한다.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from greedy_order import OrderedStroke  # type: ignore[import]


# ---------------------------------------------------------------------------
# 내부 유틸
# ---------------------------------------------------------------------------

def _sstart(s: OrderedStroke) -> np.ndarray:
    """스트로크의 현재 시작점 (방향 반영)."""
    return s.curves[0].control_points[0].astype(float)


def _send(s: OrderedStroke) -> np.ndarray:
    """스트로크의 현재 끝점 (방향 반영)."""
    return s.curves[-1].control_points[3].astype(float)


# ---------------------------------------------------------------------------
# 기본 비용 단위
# ---------------------------------------------------------------------------

def edge_cost(p1: np.ndarray, p2: np.ndarray) -> float:
    """두 점 사이의 유클리드 거리 (펜-업 비용 단위)."""
    d = np.asarray(p1, dtype=float) - np.asarray(p2, dtype=float)
    return float(np.hypot(d[0], d[1]))


# ---------------------------------------------------------------------------
# 2-opt 스왑 이득
# ---------------------------------------------------------------------------

def two_opt_gain(
    strokes: list[OrderedStroke],
    i: int,
    j: int,
    start_pos: np.ndarray | None = None,
) -> float:
    """2-opt 스왑 [i+1 .. j] 역전으로 얻는 비용 감소량.

    two_opt.py 내 인라인 계산을 함수로 추출한 것.
    양수면 개선, 음수면 악화.

    원리: 현재 두 엣지 (ei→ss, ej→sj1) 를 제거하고
          (ei→ej, ss→sj1) 로 교체했을 때의 비용 차이.

    Args:
        strokes:   현재 OrderedStroke 리스트.
        i:         역전 구간 직전 인덱스 (-1이면 start_pos 기준 첫 엣지).
        j:         역전 구간의 끝 인덱스.
        start_pos: 로봇 팔의 초기 위치 (i == -1 일 때 사용).

    Returns:
        gain > 0 이면 스왑 시 거리 감소.
    """
    n = len(strokes)
    seg = i + 1

    ei = (np.asarray(start_pos, dtype=float) if i == -1
          else _send(strokes[i]))
    ss = _sstart(strokes[seg])
    ej = _send(strokes[j])

    # 엣지 A: ei → ss  →(역전 후)→  ei → ej
    da = edge_cost(ei, ss)
    da_new = edge_cost(ei, ej)

    # 엣지 B: ej → sj1  →(역전 후)→  ss → sj1  (마지막 구간이면 없음)
    if j + 1 < n:
        sj1 = _sstart(strokes[j + 1])
        db = edge_cost(ej, sj1)
        db_new = edge_cost(ss, sj1)
        gain = (da + db) - (da_new + db_new)
    else:
        gain = da - da_new

    return gain


# ---------------------------------------------------------------------------
# 경로 평가
# ---------------------------------------------------------------------------

def _stroke_draw_dist(stroke: OrderedStroke, n_samples: int = 40) -> float:
    """스트로크 1개의 실제 그리기 거리 (베지어 호 길이 수치 적분)."""
    t = np.linspace(0.0, 1.0, n_samples)[:, None]
    u = 1.0 - t
    total = 0.0
    for c in stroke.curves:
        cp = c.control_points.astype(float)
        pts = u**3 * cp[0] + 3*u**2*t * cp[1] + 3*u*t**2 * cp[2] + t**3 * cp[3]
        d = np.diff(pts, axis=0)
        total += float(np.sum(np.hypot(d[:, 0], d[:, 1])))
    return total


def evaluate(
    ordered: list[OrderedStroke],
    csv_path: str | Path | None = None,
) -> dict:
    """경로 품질 지표를 계산한다.

    Args:
        ordered:  순서·방향이 결정된 OrderedStroke 리스트.
        csv_path: 결과를 저장할 CSV 경로. 파일이 없으면 생성, 있으면 행 추가.

    Returns:
        travel_dist : 펜-업 이동 거리 합 (px)
        draw_dist   : 실제 그리기 거리 합 (px)
        pen_lifts   : 펜-업 횟수 (pen_up_dist > 0 인 스트로크 수)
        total_dist  : travel_dist + draw_dist
    """
    travel_dist = sum(s.pen_up_dist for s in ordered)
    draw_dist   = sum(_stroke_draw_dist(s) for s in ordered)
    pen_lifts   = sum(1 for s in ordered if s.pen_up_dist > 0)
    metrics = {
        "travel_dist": travel_dist,
        "draw_dist":   draw_dist,
        "pen_lifts":   pen_lifts,
        "total_dist":  travel_dist + draw_dist,
    }

    if csv_path is not None:
        csv_path = Path(csv_path)
        write_header = not csv_path.exists()
        with csv_path.open("a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(metrics.keys()))
            if write_header:
                writer.writeheader()
            writer.writerow(metrics)

    return metrics
