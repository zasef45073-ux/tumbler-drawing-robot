import cv2
import numpy as np

class EdgeDetector:
    """이미지 파일을 로드하여 Adaptive Thresholding 이진화를 수행하는 클래스.

    Args:
        block_size  (int): Adaptive Thresholding 블록 크기 (기본값: 11, 홀수여야 함)
        c           (int): 임계값 보정 상수 (기본값: 2)
    """

    def __init__(self, block_size: int = 11, c: int = 2) -> None:
        self.block_size = block_size
        self.c = c

    def detect(self, img: np.ndarray) -> np.ndarray:
        """이미 로드된 이미지에 이진화(Adaptive Thresholding) 처리를 수행합니다.

        Args:
            img (np.ndarray): BGR 또는 그레이스케일 이미지 배열

        Returns:
            np.ndarray: 이진화된 이미지
        """
        if img.ndim == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            gray = img
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        thresh = cv2.adaptiveThreshold(
            blurred, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV, self.block_size, self.c
        )
        kernel = np.ones((3, 3), np.uint8)
        return cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=1)

