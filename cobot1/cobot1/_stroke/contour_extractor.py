import sys
import os
import cv2
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dataclasses import dataclass
from _input.edge_detector import EdgeDetector
from _input.image_loader_debug import ImageLoader

@dataclass
class ContourResult:
    """윤곽선 추출 결과를 담는 데이터 클래스.

    Attributes:
        contours:  검출된 윤곽선 목록. 각 원소는 (N, 1, 2) 형태의 np.ndarray.
        hierarchy: 윤곽선 계층 정보. shape=(1, N, 4).
        binary:    Canny 엣지 검출 결과 이진 이미지. shape=(H, W), dtype=uint8.
    """

    contours: list[np.ndarray]
    hierarchy: np.ndarray
    binary: np.ndarray

def make_line(binary: np.ndarray, thickness: int = 2) -> np.ndarray:
    """이진화 이미지에서 흰색 선을 thinning 후 지정한 두께로 조절한다.

    Args:
        binary:    흰색 선이 있는 이진 이미지. shape=(H, W), dtype=uint8.
        thickness: 최종 선 두께 (픽셀). 1이면 thinning만 적용.

    Returns:
        np.ndarray: 두께가 조절된 이진 이미지. shape=(H, W), dtype=uint8.
    """
    _, binary = cv2.threshold(binary, 127, 255, cv2.THRESH_BINARY)
    thinned = cv2.ximgproc.thinning(binary, thinningType=cv2.ximgproc.THINNING_GUOHALL)
    if thickness > 1:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (thickness, thickness))
        thinned = cv2.dilate(thinned, kernel, iterations=1)
    return thinned

def extract_contours(
    edges: np.ndarray,
    mode: int = cv2.RETR_TREE,
    method: int = cv2.CHAIN_APPROX_SIMPLE,
) -> ContourResult:
    """Canny 엣지 검출한 값을 받은 후, 윤곽선을 추출한다.

    Canny Edge → findContours 순서로 처리한다.

    Args:
        edges:       Canny 엣지 이진 이미지. shape=(H, W), dtype=uint8.
        mode:        윤곽선 검색 모드. cv2.RETR_EXTERNAL(외곽만), RETR_TREE(계층 전체) 등.
        method:      윤곽선 근사 방법. cv2.CHAIN_APPROX_SIMPLE(꼭짓점만), NONE(전체 좌표) 등.

    Returns:
        ContourResult:
            - contours:  검출된 윤곽선 리스트.
            - hierarchy: 윤곽선 계층 배열.
            - binary:    Canny 엣지 이진 이미지.
    """
    contours, hierarchy = cv2.findContours(edges, mode, method)
    return ContourResult(list(contours), hierarchy, edges)


def filter_contours_by_area(
    edges: np.ndarray,
    min_area: float = 1,
    max_area: float = float("inf"),
    thickness: int = 2,
    mode: int =  cv2.CHAIN_APPROX_NONE,
) -> list[np.ndarray]:
    """엣지 이미지로부터 thinning·팽창·윤곽선 추출·면적 필터링을 한 번에 수행한다.

    Args:
        edges:     Canny 엣지 이진 이미지. shape=(H, W), dtype=uint8.
        min_area:  허용할 최소 윤곽선 면적 (픽셀²). 이 값 미만은 제거.
        max_area:  허용할 최대 윤곽선 면적 (픽셀²). 이 값 초과는 제거.
        thickness: make_line에 전달할 선 두께 (픽셀).
        mode:      extract_contours에 전달할 윤곽선 검색 모드.

    Returns:
        list[np.ndarray]: 면적 조건을 만족하는 윤곽선만 담은 리스트.
    """
    edges_thin = make_line(edges, thickness=thickness)
    result = extract_contours(edges_thin, mode=mode)
    return [
        c for c in result.contours
        if min_area <= cv2.contourArea(c) <= max_area
    ]

def _dominant_color(img: np.ndarray, mask: np.ndarray, quant_step: int) -> tuple[int, int, int] | None:
    #마스크 내부 픽셀들의 최빈 양자화 BGR 색상을 반환한다. 샘플이 없으면 None.
    pixels = img[mask == 255]
    if len(pixels) == 0:
        return None
    quantized = (pixels.astype(np.int32) // quant_step) * quant_step
    # 각 픽셀을 단일 정수로 인코딩해 np.unique로 최빈값을 구한다
    encoded = quantized[:, 0] * (256 ** 2) + quantized[:, 1] * 256 + quantized[:, 2]
    values, counts = np.unique(encoded, return_counts=True)
    dominant = int(values[np.argmax(counts)])
    b = dominant // (256 ** 2)
    g = (dominant % (256 ** 2)) // 256
    r = dominant % 256
    return (b, g, r)


def build_color_masks_from_contours(
    img: np.ndarray,
    contours: list[np.ndarray],
    quant_step: int = 32,
    erode_px: int = 2,
    bg_threshold: int = 200,
    black_threshold: int = 40,
) -> dict[tuple[int, int, int], np.ndarray]:
    """
    윤곽선 목록으로부터 색상별 채움 마스크를 생성한다.

    각 윤곽선의 테두리 링(fill - erosion)에서 색상을 샘플링해 지배적인 색상을
    결정하고, 같은 색상끼리 하나의 마스크로 합친다.
    테두리 색상이 흰색 계열(모든 채널 >= bg_threshold)이거나
    검은색 계열(모든 채널 <= black_threshold)이면 건너뛴다.
    반환값은 color_fill.py 의 build_blue_mask 와 동일한 uint8 마스크 형식이므로
    raster_scan / raster_scan_grouped 에 바로 전달할 수 있다.

    Args:
        img:          원본 BGR 이미지. shape=(H, W, 3), dtype=uint8.
        contours:     윤곽선 리스트. 각 원소 shape=(N, 1, 2).
        quant_step:   색상 양자화 단위. color_fill.py 의 QUANT_STEP 과 맞춰 사용.
        erode_px:     테두리 링 두께(픽셀). fill에서 이 만큼 erosion한 결과를 빼서 링을 만든다.
        bg_threshold:    세 채널 모두 이 값 이상이면 배경(흰색 계열)으로 간주해 제외.
        black_threshold: 세 채널 모두 이 값 이하이면 검은색으로 간주해 제외.

    Returns:
        dict[tuple[int,int,int], np.ndarray]:
            키: 양자화된 BGR 색상 튜플 (b, g, r).
            값: 해당 색상에 속하는 윤곽선 내부를 채운 uint8 마스크. shape=(H, W).
            예) {(0, 0, 128): mask_red, (128, 0, 0): mask_blue, ...}
    """
    h, w = img.shape[:2]
    color_masks: dict[tuple[int, int, int], np.ndarray] = {}
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (erode_px * 2 + 1, erode_px * 2 + 1))

    # 면적 작은 순(안쪽→바깥쪽)으로 처리해 안쪽 영역이 픽셀을 먼저 선점한다.
    # 이렇게 하면 외곽 윤곽선 fill이 내부 색상 영역을 덮어쓰는 문제가 해결된다.
    sorted_contours = sorted(contours, key=cv2.contourArea)
    assigned = np.zeros((h, w), dtype=np.uint8)  # 이미 색상이 배정된 픽셀

    for contour in sorted_contours:
        fill_mask = np.zeros((h, w), dtype=np.uint8)
        cv2.drawContours(fill_mask, [contour], -1, 255, thickness=cv2.FILLED)

        # 색상 샘플링: 원본 fill_mask의 테두리 링 사용 (경계부 색상이 해당 영역 색)
        eroded_mask = cv2.erode(fill_mask, kernel, iterations=1)
        border_mask = cv2.bitwise_and(fill_mask, cv2.bitwise_not(eroded_mask))

        color = _dominant_color(img, border_mask, quant_step)
        if color is None:
            color = _dominant_color(img, fill_mask, quant_step)
        if color is None:
            continue

        # 아직 배정되지 않은 픽셀만 이 윤곽선 색상으로 채운다
        exclusive_mask = cv2.bitwise_and(fill_mask, cv2.bitwise_not(assigned))
        # fill 전체를 배정 완료로 표시 (흰/검 영역도 외곽이 덮지 못하게)
        assigned = cv2.bitwise_or(assigned, fill_mask)

        b, g, r = color
        if b >= bg_threshold and g >= bg_threshold and r >= bg_threshold:
            continue
        if b <= black_threshold and g <= black_threshold and r <= black_threshold:
            continue

        if color not in color_masks:
            color_masks[color] = np.zeros((h, w), dtype=np.uint8)
        color_masks[color] = cv2.bitwise_or(color_masks[color], exclusive_mask)

    return color_masks


if __name__ == "__main__":
    loader = ImageLoader()
    color_img = loader.load()
    if color_img is None:
        print("이미지를 불러올 수 없습니다.")
        exit(1)

    edge_detector = EdgeDetector()
    edges = edge_detector.detect(color_img)

    contours = filter_contours_by_area(edges)
    print(f"검출된 윤곽선 수: {len(contours)}")

    # ── 색상 검출 디버그 ──────────────────────────────────────────────
    color_masks = build_color_masks_from_contours(color_img, contours)
    print(f"검출된 색상 수: {len(color_masks)}")

    # 검출된 색상과 픽셀 수 출력
    for (b, g, r), mask in color_masks.items():
        px = int(np.count_nonzero(mask))
        print(f"  BGR=({b:3d},{g:3d},{r:3d})  픽셀수={px:6d}")

    # 시각화 이미지 구성
    h, w = color_img.shape[:2]

    # 패널 1: 원본
    panel_orig = color_img.copy()

    # 패널 2: 엣지
    panel_edge = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)

    # 패널 3: 검출 색상으로 각 영역을 채운 결과
    panel_fill = np.full((h, w, 3), 255, dtype=np.uint8)
    for (b, g, r), mask in color_masks.items():
        panel_fill[mask == 255] = (b, g, r)

    # 패널 4: 컬러마다 색 이름/값을 레이블로 표시한 마스크 합산
    panel_label = color_img.copy()
    for (b, g, r), mask in color_masks.items():
        # 영역 테두리 강조
        contour_vis, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(panel_label, contour_vis, -1, (b, g, r), 2)
        # 무게중심에 BGR 값 텍스트 표시
        M = cv2.moments(mask)
        if M["m00"] > 0:
            cx = int(M["m10"] / M["m00"])
            cy = int(M["m01"] / M["m00"])
            label = f"({b},{g},{r})"
            cv2.putText(panel_label, label, (cx - 30, cy),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 0), 2, cv2.LINE_AA)
            cv2.putText(panel_label, label, (cx - 30, cy),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (b, g, r), 1, cv2.LINE_AA)

    # 2×2 그리드로 합치기
    row1 = np.hstack([panel_orig, panel_edge])
    row2 = np.hstack([panel_fill, panel_label])
    debug_view = np.vstack([row1, row2])

    # 제목 추가
    titles = ["Original", "Edges", "Color Fill", "Color Labels"]
    for i, title in enumerate(titles):
        tx = (i % 2) * w + 5
        ty = (i // 2) * h + 20
        cv2.putText(debug_view, title, (tx, ty),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2, cv2.LINE_AA)

    cv2.imshow("Color Debug", debug_view)
    print("아무 키나 누르면 종료합니다.")
    cv2.waitKey(0)
    cv2.destroyAllWindows()
