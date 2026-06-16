import numpy as np

# =============================================
# 캔버스 설정
# =============================================
CANVAS_ORIGIN_X = 567.2 # mm, 로봇 베이스 기준 캔버스 원점 x
CANVAS_ORIGIN_Y = 3.8  # mm, 로봇 베이스 기준 캔버스 원점 y
CANVAS_ORIGIN_Z = 0  # mm, 캔버스 높이 (실제 로봇 세팅 시 맞출 것)

CANVAS_SIZE_MM = 100.0   # mm, 캔버스 가로/세로 크기

Z_DRAW = CANVAS_ORIGIN_Z         # mm, 펜이 캔버스에 닿는 높이
Z_MOVE = CANVAS_ORIGIN_Z + 20.0  # mm, 획 사이 이동 높이

# 그림 회전: 0, 90, 180, 270
ROTATION_DEG = 270


def _rotate_pixel(u: int, v: int, image_size_px: int, deg: int) -> tuple:
    s = image_size_px
    if deg == 90:
        return (v, s - 1 - u)
    elif deg == 180:
        return (s - 1 - u, s - 1 - v)
    elif deg == 270:
        return (s - 1 - v, u)
    return (u, v)


# =============================================
# 변환 함수
# =============================================
def pixel_to_xyz(u: int, v: int, x_offset:float ,y_offset: float ,image_size_px: int) -> tuple:
    """픽셀 좌표 한 점을 로봇 베이스 기준 3D 좌표(mm)로 변환한다.

    Args:
        u: 픽셀 x 좌표
        v: 픽셀 y 좌표
        image_size_px: 이미지의 가로/세로 최대 픽셀 수 (스케일 계산 기준)

    Returns:
        (x, y, z) 로봇 베이스 기준 mm 단위 좌표
    """
    scale = CANVAS_SIZE_MM / image_size_px
    s = image_size_px - 1
    u = max(0, min(s, u))
    v = max(0, min(s, v))
    u, v = _rotate_pixel(u, v, image_size_px, ROTATION_DEG)
    x = CANVAS_ORIGIN_X + u * scale
    y = CANVAS_ORIGIN_Y - v * scale
    z = Z_DRAW

    return (x + x_offset , y + y_offset, z)


def pixel_to_xyz_batch(points: list, image_size_px: int, x_offset :float , y_offset: float) -> list:
    """픽셀 좌표 목록 전체를 로봇 베이스 기준 3D 좌표 목록으로 일괄 변환한다.

    Args:
        points: (u, v) 픽셀 좌표 튜플의 리스트
        image_size_px: 이미지의 가로/세로 최대 픽셀 수

    Returns:
        (x, y, z) 좌표 튜플의 리스트
    """
    return [pixel_to_xyz(u, v, image_size_px,x_offset,y_offset) for u, v in points]


def pixel_to_xyz_centered_batch(all_strokes: list, image_size_px: int) -> list:
    """
    그림을 (0,0) 기점으로 재정렬한 후, 
    100x100 캔버스의 정중앙에 위치하도록 오프셋을 계산합니다.
    """
    scale = CANVAS_SIZE_MM / image_size_px
    s = image_size_px - 1

    # 1. 픽셀 -> mm 변환 및 회전 적용
    rotated_strokes = []
    all_xs, all_ys = [], []
    
    for pixels in all_strokes:
        stroke_pts = []
        for u, v in pixels:
            u_c, v_c = max(0, min(s, u)), max(0, min(s, v))
            u_rot, v_rot = _rotate_pixel(u_c, v_c, image_size_px, ROTATION_DEG)
            
            rx, ry = u_rot * scale, v_rot * scale
            stroke_pts.append([rx, ry])
            all_xs.append(rx)
            all_ys.append(ry)
        rotated_strokes.append(stroke_pts)

    if not rotated_strokes or not all_xs:
        return [[]]

    # 2. 그림의 현재 바운딩 박스(실제 그려지는 영역) 계산
    min_rx, max_rx = min(all_xs), max(all_xs)
    min_ry, max_ry = min(all_ys), max(all_ys)
    
    content_w = max_rx - min_rx
    content_h = max_ry - min_ry

    # 3. 캔버스(100mm) 내부의 중앙 여백(Margin) 계산
    # 가로(X) 여백과 세로(Y) 여백을 각각 구합니다.
    margin_x = (CANVAS_SIZE_MM - content_w) / 2.0
    margin_y = (CANVAS_SIZE_MM - content_h) / 2.0

    # 4. 최종 로봇 좌표 매핑 (좌측 상단 원점 기준)
    result = []
    for stroke in rotated_strokes:
        xyz_stroke = []
        for rx, ry in stroke:
            # [기존 좌표 - 최소값]을 하면 그림이 (0,0)에서 시작하게 됨
            # 그 후 margin을 더해 중앙으로 보냄
            
            # X좌표: 원점(좌측 상단)에서 '앞'으로 나가는 거리
            # 그림이 몸쪽(하단)으로 쏠린다면 margin_x와 (rx - min_rx)가 정확히 더해져야 함
            final_x = CANVAS_ORIGIN_X + (rx - min_rx + margin_x)
            
            # Y좌표: 원점(좌측 상단)에서 '오른쪽'으로 들어가는 거리
            # 로봇의 오른쪽은 -Y 방향이므로, 여백만큼 원점에서 빼줘야 중앙으로 이동함
            final_y = CANVAS_ORIGIN_Y - (ry - min_ry + margin_y)
            
            xyz_stroke.append((final_x, final_y, Z_DRAW))
        result.append(xyz_stroke)

    return result

def image_to_xyz_list(edges: np.ndarray) -> list:
    """엣지 이미지(numpy 배열)를 받아 로봇 베이스 기준 3D 좌표 목록으로 변환한다.

    Args:
        edges: mono8 형식의 엣지 이미지 (numpy ndarray)

    Returns:
        (x, y, z) 좌표 튜플의 리스트
    """
    h, w = edges.shape
    image_size_px = max(h, w)

    points = np.column_stack(np.where(edges > 0))
    pixels = [(int(u), int(v)) for v, u in points]

    return pixel_to_xyz_batch(pixels, image_size_px)
