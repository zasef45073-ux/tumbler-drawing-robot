#!/usr/bin/env python3

# =========================================================
# ROS2 Doosan Robot Pause / Resume 제어 테스트 코드
# - move_pause / move_resume 서비스 호출
# - CLI 인자로 pause 또는 resume 선택 가능
# =========================================================
import sys
import rclpy
from rclpy.logging import get_logger

# 로봇 ID (namespace 구성용)
from default_robot import ROBOT_ID

# 전역 로그 객체 (CLI 사용 시 활용)
_logger = get_logger("pause")


# =========================================================
# [FUNCTION] 로봇 동작 일시정지 (Pause)
# =========================================================
def call_pause(node):

    # ROS2 서비스 타입 import (동작 일시정지)
    from dsr_msgs2.srv import MovePause

    # 서비스 이름 (namespace 포함)
    service_name = f"/{ROBOT_ID}/motion/move_pause"

    # 로그 출력
    node.get_logger().info(f"[PAUSE] service call: {service_name}")

    # 서비스 클라이언트 생성
    client = node.create_client(MovePause, service_name)

    # 서비스 서버가 올라올 때까지 최대 3초 대기
    if not client.wait_for_service(timeout_sec=3.0):
        raise RuntimeError(f"서비스를 찾을 수 없습니다: {service_name}")

    # 요청 메시지 생성 (Pause는 보통 empty request)
    request = MovePause.Request()

    # 비동기 서비스 호출
    future = client.call_async(request)

    # 응답 올 때까지 blocking spin
    rclpy.spin_until_future_complete(node, future)

    # 결과 수신
    response = future.result()

    # 응답 없음 예외 처리
    if response is None:
        raise RuntimeError("pause service 응답이 없습니다.")

    # 결과 로그 출력 (성공 여부)
    node.get_logger().info(f"[PAUSE] response.success = {response.success}")


# =========================================================
# [FUNCTION] 로봇 동작 재개 (Resume)
# =========================================================
def call_resume(node):

    # ROS2 서비스 타입 import (동작 재개)
    from dsr_msgs2.srv import MoveResume

    # 서비스 이름
    service_name = f"/{ROBOT_ID}/motion/move_resume"

    # 로그 출력
    node.get_logger().info(f"[RESUME] service call: {service_name}")

    # 서비스 클라이언트 생성
    client = node.create_client(MoveResume, service_name)

    # 서비스 서버 준비 대기 (최대 3초)
    if not client.wait_for_service(timeout_sec=3.0):
        raise RuntimeError(f"서비스를 찾을 수 없습니다: {service_name}")

    # 요청 메시지 생성
    request = MoveResume.Request()

    # 비동기 요청
    future = client.call_async(request)

    # 응답 받을 때까지 blocking
    rclpy.spin_until_future_complete(node, future)

    # 결과 수신
    response = future.result()

    # 응답 없으면 에러
    if response is None:
        raise RuntimeError("resume service 응답이 없습니다.")

    # 결과 로그 출력
    node.get_logger().info(f"[RESUME] response.success = {response.success}")


# =========================================================
# [MAIN] 실행 진입점
# =========================================================
def main():

    # 기본 동작은 pause
    action = "pause"

    # CLI 인자로 동작 변경 가능
    # 예:
    #   python3 script.py pause
    #   python3 script.py resume
    if len(sys.argv) >= 2:
        action = sys.argv[1].strip().lower()

    # 입력값 검증
    if action not in {"pause", "resume"}:
        _logger.info("사용법:")
        _logger.info("  python3 robot_pause_resume_test.py pause")
        _logger.info("  python3 robot_pause_resume_test.py resume")
        sys.exit(1)

    # =====================================================
    # ROS2 초기화
    # =====================================================
    rclpy.init()

    # ROS2 노드 생성 (robot namespace 적용)
    node = rclpy.create_node(
        "robot_pause_resume_test",
        namespace=ROBOT_ID,
    )

    try:
        # 선택된 action 실행
        if action == "pause":
            call_pause(node)
        else:
            call_resume(node)

    finally:
        # =================================================
        # 안전 종료 (노드 + ROS shutdown)
        # =================================================
        node.destroy_node()
        rclpy.shutdown()


# =========================================================
# 프로그램 시작점
# =========================================================
if __name__ == "__main__":
    main()