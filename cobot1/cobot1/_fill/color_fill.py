"""
파란색 영역 래스터 스캔 모듈.
main 파일에서 import해서 사용한다.
"""
import numpy as np

# 색상 양자화 단계: 픽셀값을 이 단위로 내림해 미세한 색상 차이를 무시한다
QUANT_STEP = 32

def _continuous_segments(cols: np.ndarray) -> list[tuple[int, int]]:
    """1D 열 인덱스 배열에서 연속 구간의 (start_col, end_col) 쌍을 반환."""
    if len(cols) == 0:
        return []
    segments = []
    start = int(cols[0])
    prev  = int(cols[0])
    for c in cols[1:]:
        c = int(c)
        if c > prev + 1:
            segments.append((start, prev))
            start = c
        prev = c
    segments.append((start, prev))
    return segments


def _transition_in_mask(mask: np.ndarray, p1: tuple[int, int], p2: tuple[int, int]) -> bool:
    """p1~p2 직선 위의 모든 샘플 픽셀이 마스크 내부(255)에 있으면 True."""
    x1, y1 = p1
    x2, y2 = p2
    steps = max(abs(x2 - x1), abs(y2 - y1), 1)
    h, w = mask.shape
    for t in np.linspace(0, 1, steps + 1):
        x = int(round(x1 + t * (x2 - x1)))
        y = int(round(y1 + t * (y2 - y1)))
        if not (0 <= y < h and 0 <= x < w) or mask[y, x] != 255:
            return False
    return True


def raster_scan(blue_mask: np.ndarray, line_spacing: int) -> list:
    """v1: 행마다 연속 구간별로 선분 생성. 구멍(불연속 구간)은 별도 선분으로 처리.

    수정 이력:
      - 불연속 구간 분리: cols[0]~cols[-1] 단일 선분 대신 연속 구간별로 선분 생성.
        구멍이 있는 글자(B, e, a 등)에서 구멍을 통과하는 선을 긋지 않는다.
    """
    h = blue_mask.shape[0]
    strokes = []
    go_right = True
    for row in range(0, h, line_spacing):
        cols = np.where(blue_mask[row] == 255)[0]
        if len(cols) == 0:
            continue
        segments = _continuous_segments(cols)
        if go_right:
            for s, e in segments:
                strokes.append([(s, row), (e, row)])
        else:
            for s, e in reversed(segments):
                strokes.append([(e, row), (s, row)])
        go_right = not go_right
    return strokes


def raster_scan_grouped(blue_mask: np.ndarray, line_spacing: int) -> list:
    """v2: 연속된 행을 하나의 경로로 묶되, 전환 선이 마스크 밖을 나가면 경로를 분리.

    수정 이력:
      - 불연속 구간 분리: 한 행의 여러 구간을 개별 처리하고 구간 사이 마스크 검사.
      - 마스크 외부 전환 방지: 행 간 연결선(_transition_in_mask)이 마스크 밖을 지나면
        경로를 분리해 마스크 외부에 선이 그려지지 않도록 함.
    """
    h = blue_mask.shape[0]
    all_paths = []
    current_path = None
    last_p2 = None
    go_right = True

    for row in range(0, h, line_spacing):
        cols = np.where(blue_mask[row] == 255)[0]
        if len(cols) == 0:
            if current_path:
                all_paths.append(current_path)
                current_path = None
                last_p2 = None
            go_right = True
            continue

        segments = _continuous_segments(cols)
        # 진행 방향에 따라 구간 순서 및 각 구간 방향 결정
        if go_right:
            ordered = [(s, e) for s, e in segments]
        else:
            ordered = [(e, s) for s, e in reversed(segments)]

        for x1, x2 in ordered:
            p1 = (x1, row)
            p2 = (x2, row)
            if current_path is None:
                current_path = [p1, p2]
            elif _transition_in_mask(blue_mask, last_p2, p1):
                current_path.extend([p1, p2])
            else:
                # 전환선이 마스크 밖을 지남 → 경로 분리
                all_paths.append(current_path)
                current_path = [p1, p2]
            last_p2 = p2

        go_right = not go_right

    if current_path:
        all_paths.append(current_path)
    return all_paths
