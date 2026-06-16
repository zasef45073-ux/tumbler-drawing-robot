import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from cv_bridge import CvBridge
import cv2
import numpy as np
import os
from typing import Optional

"""
주문 ui 
이미지를 가지고 경로계산을 해서 보내는 작업
이미지를 보내는 과정
"""
class ImageLoaderNode(Node):
    """로컬 이미지 파일을 읽어 ROS 2 토픽으로 발행하는 노드.

    이미지를 1초 주기로 읽고, 알파 채널 합성 및 그레이스케일 변환 후
    'raw_image' 토픽에 mono8 인코딩으로 발행한다.

    Input:
        - self.image_path: 로컬 이미지 파일 경로 (JPEG, PNG 등)
    Output:
        - ROS 2 토픽 'raw_image': mono8 인코딩의 그레이스케일 Image 메시지 (1초 주기)
    """

    def __init__(self) -> None:
        # Input:  없음 (노드 초기화)
        # Output: publisher('raw_image'), bridge, image_path, timer 설정
        super().__init__('image_loader')
        # ui에서 업로드된 'raw_image' 토픽으로 전처리된 이미지를 발행합니다.
        self.publisher = self.create_publisher(Image, 'raw_image', 10)
        self.bridge: CvBridge = CvBridge()

        # 이미지 경로 (이 스크립트 파일 기준 상대경로)
        self.image_path: str = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test.png')

        # 1초마다 이미지를 읽어서 발행하는 타이머
        self.create_timer(1.0, self.timer_callback)
        self.get_logger().info('이미지 로더 노드가 실행되었습니다.')

    def timer_callback(self) -> None:
        """타이머 콜백: 이미지를 읽고 전처리하여 ROS 2 토픽으로 발행한다.

        Input:
            - self.image_path: 로드할 이미지 파일 경로
        Output:
            - ROS 2 토픽 'raw_image': mono8 그레이스케일 Image 메시지 발행
            - 이미지 로드 실패 시 에러 로그 출력 후 조기 반환
        """
        # 1. 알파 채널을 포함하여 이미지 로드
        img: Optional[np.ndarray] = cv2.imread(self.image_path, cv2.IMREAD_UNCHANGED)

        if img is None:
            self.get_logger().error(f'이미지를 찾을 수 없습니다: {self.image_path}')
            return

        # 2. 투명 배경 처리 (4채널일 경우 흰색 배경과 합성)
        if len(img.shape) == 3 and img.shape[2] == 4:
            alpha: np.ndarray = img[:, :, 3] / 255.0
            rgb: np.ndarray = img[:, :, :3]
            white_bg: np.ndarray = np.ones_like(rgb, dtype=np.uint8) * 255
            img = (rgb * alpha[..., np.newaxis] + white_bg * (1 - alpha[..., np.newaxis])).astype(np.uint8)

        # 3. 그레이스케일 변환
        gray_img: np.ndarray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # 4. ROS 2 메시지로 변환 및 발행
        msg: Image = self.bridge.cv2_to_imgmsg(gray_img, encoding="mono8")
        self.publisher.publish(msg)
        self.get_logger().info('전처리된 이미지를 발행했습니다.')


def main(args: Optional[list] = None) -> None:
    """노드를 초기화하고 스핀한다.

    Input:
        - args: rclpy 초기화 인자 (기본값 None, ROS 2 CLI 인자 전달 시 사용)
    Output:
        - 없음 (노드 종료 시 rclpy.shutdown() 호출)
    """
    rclpy.init(args=args)
    node = ImageLoaderNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
