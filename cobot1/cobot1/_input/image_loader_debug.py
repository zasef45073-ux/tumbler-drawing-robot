import cv2
import numpy as np
import os
from pathlib import Path
from typing import Optional


class ImageLoader:
    """로컬 이미지 파일을 읽어 RGB로 변환하는 클래스.

    변경점:
    - COBOT1_INPUT_IMAGE 환경변수가 있으면 그 파일을 최우선으로 읽는다.
    - 환경변수가 없으면 _input/test.png → test.jpg → test.jpeg 순서로 찾는다.

    이유:
    - robot_algorithm_adapter.py는 업로드 이미지를 _input/test.png로 복사한다.
    - 기존 image_loader_debug.py는 test.jpeg를 고정으로 읽어서,
      preview와 실제 main.py가 서로 다른 이미지를 쓰는 문제가 생길 수 있었다.
    """

    def __init__(self) -> None:
        current_dir = Path(__file__).resolve().parent
        env_image_path = os.getenv("COBOT1_INPUT_IMAGE", "").strip()

        candidates = []
        if env_image_path:
            candidates.append(Path(env_image_path).expanduser())

        candidates.extend([
            current_dir / "test.png",
            current_dir / "test.jpg",
            current_dir / "test.jpeg",
        ])

        self.image_path = ""
        for candidate in candidates:
            candidate = candidate.resolve()
            if candidate.exists() and candidate.is_file():
                self.image_path = str(candidate)
                break

        if not self.image_path:
            # 에러 메시지에서 어떤 경로를 찾으려 했는지 보이게 마지막 후보를 기록
            self.image_path = str(candidates[0].resolve() if candidates else current_dir / "test.png")

        print(f"이미지 로더가 초기화되었습니다. image_path={self.image_path}")

    def load(self) -> Optional[np.ndarray]:
        """이미지를 읽고 전처리하여 RGB 배열로 반환한다."""
        img: Optional[np.ndarray] = cv2.imread(self.image_path, cv2.IMREAD_UNCHANGED)

        if img is None:
            print(f"[ERROR] 이미지를 찾을 수 없습니다: {self.image_path}")
            return None

        # 투명 배경 처리
        if len(img.shape) == 3 and img.shape[2] == 4:
            alpha: np.ndarray = img[:, :, 3] / 255.0
            bgr: np.ndarray = img[:, :, :3]
            white_bg: np.ndarray = np.ones_like(bgr, dtype=np.uint8) * 255
            img = (bgr * alpha[..., np.newaxis] + white_bg * (1 - alpha[..., np.newaxis])).astype(np.uint8)

        # BGR -> RGB 변환
        if len(img.shape) == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
        else:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        # 512x512 고정 크기로 리사이즈
        img = cv2.resize(img, (512, 512), interpolation=cv2.INTER_AREA)

        # 픽셀 분포 기반 콘텐츠 중앙 정렬
        gray_tmp = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        _, binary = cv2.threshold(gray_tmp, 240, 255, cv2.THRESH_BINARY_INV)
        coords = cv2.findNonZero(binary)
        if coords is not None:
            x, y, w, h = cv2.boundingRect(coords)
            dx = 256 - (x + w // 2)
            dy = 256 - (y + h // 2)
            M = np.float32([[1, 0, dx], [0, 1, dy]])
            img = cv2.warpAffine(
                img,
                M,
                (512, 512),
                borderMode=cv2.BORDER_CONSTANT,
                borderValue=(255, 255, 255),
            )

        return img
