#!/usr/bin/env python3

# =========================================================
# ROS2 + Doosan Robot
# Move Pause / Resume 테스트 코드
#
# 기능:
# ---------------------------------------------------------
# 1. 비동기 MoveJ(amovej) 실행
# 2. 이동 중 Pause 서비스 호출
# 3. 현재 관절각 확인
# 4. Resume 서비스 호출
# 5. 이동 재개 확인
# 6. Home 위치 복귀
# =========================================================
import rclpy
import DR_init
from rclpy.logging import get_logger
_logger = get_logger("move_pause_resume")

# ---------------------------------------------------------
# 기본 로봇 설정 import
# ---------------------------------------------------------
from default_robot import (
    ROBOT_ID,
    ROBOT_MODEL,
    initialize_robot,
)

# ---------------------------------------------------------
# 기본 속도 / 가속도 설정
# ---------------------------------------------------------
VELOCITY = 40
ACC = 60

# ---------------------------------------------------------
# Doosan Robot 초기 설정
# ---------------------------------------------------------
DR_init.__dsr__id = ROBOT_ID
DR_init.__dsr__model = ROBOT_MODEL


# =========================================================
# Pause 서비스 호출
# =========================================================

def call_pause():
    """
    현재 로봇 motion을 Pause 상태로 변경

    사용 서비스:
        /{ROBOT_ID}/motion/move_pause
    """

    from dsr_msgs2.srv import MovePause

    # 서비스 클라이언트 생성
    cli = DR_init.__dsr__node.create_client(
        MovePause,
        f'/{ROBOT_ID}/motion/move_pause'
    )

    # 서비스 활성화 대기
    cli.wait_for_service()

    # 비동기 요청
    future = cli.call_async(MovePause.Request())

    # 응답 대기
    rclpy.spin_until_future_complete(
        DR_init.__dsr__node,
        future
    )

    _logger.info(">>> 이동이 Pause 되었습니다.")


# =========================================================
# Resume 서비스 호출
# =========================================================

def call_resume():
    """
    Pause 상태의 motion을 다시 Resume

    사용 서비스:
        /{ROBOT_ID}/motion/move_resume
    """

    from dsr_msgs2.srv import MoveResume

    # 서비스 클라이언트 생성
    cli = DR_init.__dsr__node.create_client(
        MoveResume,
        f'/{ROBOT_ID}/motion/move_resume'
    )

    # 서비스 활성화 대기
    cli.wait_for_service()

    # 비동기 요청
    future = cli.call_async(MoveResume.Request())

    # 응답 완료까지 대기
    rclpy.spin_until_future_complete(
        DR_init.__dsr__node,
        future
    )

    _logger.info(">>> 이동이 Resume 되었습니다.")


# =========================================================
# 테스트 동작 수행
# =========================================================

def perform_task():

    import time

    from DSR_ROBOT2 import (
        posj,
        amovej,
        movej,
        get_current_posj,
    )

    _logger.info("로봇 MoveJ 시작합니다.")

    # -----------------------------------------------------
    # 목표 관절 자세 생성
    # -----------------------------------------------------
    p1 = posj([
        -90,
        0,
        90,
        0,
        90,
        0
    ])

    _logger.info(f"목표 관절각도: {p1}")

    # -----------------------------------------------------
    # 비동기 MoveJ 시작
    # -----------------------------------------------------
    amovej(
        p1,
        vel=20,
        acc=20
    )

    # 이동 시작 후 2초 대기
    time.sleep(2)

    # -----------------------------------------------------
    # Pause 수행
    # -----------------------------------------------------
    _logger.info("Pause 합니다.")

    call_pause()

    # 현재 관절각 확인
    _logger.info(f"현재 관절각도: {get_current_posj()}")

    # Pause 상태 유지
    time.sleep(5)

    # -----------------------------------------------------
    # Resume 수행
    # -----------------------------------------------------
    _logger.info("Resume 합니다.")

    call_resume()

    # Resume 이후 이동 확인용 대기
    time.sleep(5)

    _logger.info(
        f"Resume 후 현재 관절각도: {get_current_posj()}"
    )

    # -----------------------------------------------------
    # Home 위치 복귀
    # -----------------------------------------------------
    _logger.info("Home으로 이동합니다.")

    movej(
        [0, 0, 90, 0, 90, 0],
        vel=20,
        acc=20
    )


# =========================================================
# 메인 함수
# =========================================================

def main(args=None):

    # ROS2 초기화
    rclpy.init(args=args)

    # ROS2 노드 생성
    node = rclpy.create_node(
        "move_pause_resume",
        namespace=ROBOT_ID
    )

    # Doosan Robot node 등록
    DR_init.__dsr__node = node

    try:

        # -------------------------------------------------
        # 로봇 초기화
        # -------------------------------------------------
        initialize_robot()

        _logger.info(f"VELOCITY: {VELOCITY}")
        _logger.info(f"ACC: {ACC}")

        # 테스트 수행
        perform_task()

    # -----------------------------------------------------
    # Ctrl+C 종료 처리
    # -----------------------------------------------------
    except KeyboardInterrupt:

        _logger.warn("\nNode interrupted by user. Shutting down...")

    # -----------------------------------------------------
    # 일반 예외 처리
    # -----------------------------------------------------
    except Exception as e:

        _logger.error(f"An unexpected error occurred: {e}")

    # -----------------------------------------------------
    # ROS2 종료
    # -----------------------------------------------------
    finally:

        rclpy.shutdown()


# =========================================================
# 프로그램 시작점
# =========================================================

if __name__ == "__main__":
    main()

