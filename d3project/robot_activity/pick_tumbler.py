#!/usr/bin/env python3

import os
import time

import rclpy
import DR_init

from robot_safe_motion import SafeMotionContext


# ============================================================
# pick_tumbler.py
#
# 역할:
# - 텀블러를 집어서 작업 위치에 놓는 공정
#
# 현재 버전:
# - amovej / amovel + check_motion 구조 유지
# - pause/resume 즉시 반응 구조 유지
# - robot_safe_motion.SafeMotionContext 적용
#
# Safe Stop 처리:
# - 이동 대기 중 get_robot_state()로 STATE_SAFE_STOP(5) 감지
# - Firebase current_job / robot_status에 안전정지 상태 업데이트
# - 5초 카운트다운
# - SetRobotControl(2)로 노란불 Safe Stop 복구
# - STANDBY(1) 확인 후 끊긴 target 재전송
# - 같은 공정 계속 진행
#
# 주의:
# - Emergency Stop(빨간불, state=6)은 자동 복구하지 않음
# - 빨간불은 사람이 비상정지 버튼을 해제해야 함
# ============================================================


# 로봇 설정 상수
ROBOT_ID = "dsr01"
ROBOT_MODEL = "m0609"
ROBOT_TOOL = "Tool Weight"
ROBOT_TCP = "GripperDA_v1"

# 이동 속도 및 가속도
VELOCITY_J = 20
ACC_J = 30

VELOCITY_L = 100
ACC_L = 200

# DR_init 설정
DR_init.__dsr__id = ROBOT_ID
DR_init.__dsr__model = ROBOT_MODEL


def initialize_robot():
    """로봇의 Tool과 TCP를 설정한다."""

    from DSR_ROBOT2 import (
        set_tool,
        set_tcp,
        get_tool,
        get_tcp,
        ROBOT_MODE_MANUAL,
        ROBOT_MODE_AUTONOMOUS,
        get_robot_mode,
        set_robot_mode,
    )

    print("[INIT] robot setting")

    # Tool과 TCP 설정 시 매뉴얼 모드로 변경해서 진행
    set_robot_mode(ROBOT_MODE_MANUAL)
    set_tool(ROBOT_TOOL)
    set_tcp(ROBOT_TCP)

    set_robot_mode(ROBOT_MODE_AUTONOMOUS)
    time.sleep(2.0)

    print("#" * 50)
    print("Initializing robot with the following settings:")
    print(f"ROBOT_ID: {ROBOT_ID}")
    print(f"ROBOT_MODEL: {ROBOT_MODEL}")
    print(f"ROBOT_TCP: {get_tcp()}")
    print(f"ROBOT_TOOL: {get_tool()}")
    print(f"ROBOT_MODE (0:Manual, 1:Auto): {get_robot_mode()}")
    print(f"VELOCITY_J/L: {VELOCITY_J}, {VELOCITY_L}")
    print(f"ACC_J/L: {ACC_J}, {ACC_L}")
    print("#" * 50)


def gripper_open():
    """
    그리퍼 열기.
    기존 코드의 Gripper off 동작 유지.
    """

    from DSR_ROBOT2 import set_digital_output, wait

    print("[GRIPPER] open")
    set_digital_output(1)
    set_digital_output(2)
    set_digital_output(3)
    wait(0.2)


def gripper_close():
    """
    그리퍼 닫기.
    기존 코드의 Gripper on 동작 유지.
    """

    from DSR_ROBOT2 import set_digital_output, wait

    print("[GRIPPER] close")
    set_digital_output(-2)
    set_digital_output(-3)
    set_digital_output(1)
    wait(1.0)


def gripper_home():
    """
    그리퍼 기본자세.
    """

    from DSR_ROBOT2 import set_digital_output, wait

    print("[GRIPPER] home")
    set_digital_output(-2)
    set_digital_output(-3)
    set_digital_output(-1)
    set_digital_output(2)
    wait(1.0)


def create_safe_motion_context():
    """
    Safe Stop 복구 기능이 포함된 motion context 생성.

    환경변수는 없어도 동작한다.
    listener/adapter에서 나중에 job id를 넘기고 싶으면 아래 환경변수를 줄 수 있다.

    ROBOT_JOB_ID
    ROBOT_COMMAND_TYPE
    ROBOT_COMMAND_LABEL
    """

    job_id = os.getenv("ROBOT_JOB_ID", "").strip()
    command_type = os.getenv("ROBOT_COMMAND_TYPE", "tumbler_place").strip()
    command_label = os.getenv("ROBOT_COMMAND_LABEL", "텀블러 놓기").strip()

    return SafeMotionContext(
        robot_id=ROBOT_ID,
        job_id=job_id,
        command_type=command_type,
        command_label=command_label,
        countdown_sec=5,
        max_recovery_per_motion=2,
        firebase_enabled=True,
    )


def perform_task():
    """로봇이 텀블러 놓기 작업을 수행한다."""

    print("[START] pick tumbler task")

    from DSR_ROBOT2 import (
        posj,
        posx,
        wait,
        task_compliance_ctrl,
        release_compliance_ctrl,
    )

    safe = create_safe_motion_context()

    # ========================================================
    # 좌표 정의
    # ========================================================

    joint1 = posj(0, 0, 90, 0, 90, 0)

    joint2 = posj(
        18.56,
        54.73,
        81.05,
        103.57,
        77.51,
        -47.23,
    )

    joint3 = posj(
        24.98,
        56.97,
        74.61,
        107.25,
        71.91,
        -44.29,
    )

    joint4 = posj(
        24.98,
        49.07,
        73.73,
        104.23,
        69.54,
        -35.34,
    )

    joint5 = posj(
        47.88,
        16.64,
        78.33,
        23.70,
        58.48,
        41.95,
    )

    point6 = posx(
        355.10,
        585.44,
        14.02,
        89.47,
        160.92,
        92.36,
    )

    point7 = posx(
        348.07,
        569.64,
        -3.60,
        86.74,
        172.83,
        85.89,
    )

    compliance_enabled = False

    try:
        # ====================================================
        # 1. 그리퍼 열고 초기 위치 이동
        # ====================================================

        gripper_open()

        safe.safe_amovej(
            label="Joint1_home",
            target=joint1,
            vel=VELOCITY_J,
            acc=ACC_J,
        )

        safe.safe_amovej(
            label="Joint2_approach",
            target=joint2,
            vel=VELOCITY_J,
            acc=ACC_J,
        )

        safe.safe_amovej(
            label="Joint3_pick_position",
            target=joint3,
            vel=VELOCITY_J,
            acc=ACC_J,
        )

        wait(0.5)

        # ====================================================
        # 2. 텀블러 그립
        # ====================================================

        gripper_close()

        # ====================================================
        # 3. 텀블러 이동
        # ====================================================

        wait(0.5)

        safe.safe_amovej(
            label="Joint4_lift",
            target=joint4,
            vel=VELOCITY_J,
            acc=ACC_J,
        )

        safe.safe_amovej(
            label="Joint5_place_approach",
            target=joint5,
            vel=VELOCITY_J,
            acc=ACC_J,
        )

        # ====================================================
        # 4. 순응제어 후 작업 위치에 내려놓기
        # ====================================================

        print("[COMPLIANCE] on")
        task_compliance_ctrl([500, 3000, 500, 200, 200, 200])
        compliance_enabled = True

        safe.safe_amovel(
            label="Point6_place_down_1",
            target=point6,
            vel=VELOCITY_L,
            acc=ACC_L,
        )

        safe.safe_amovel(
            label="Point7_place_down_2",
            target=point7,
            vel=VELOCITY_L,
            acc=ACC_L,
        )

        print("[COMPLIANCE] off")
        release_compliance_ctrl()
        compliance_enabled = False

        # ====================================================
        # 5. 그리퍼 열고 원위치 복귀
        # ====================================================

        gripper_open()
        wait(1.0)

        safe.safe_amovel(
            label="Point6_place_return",
            target=point6,
            vel=VELOCITY_L,
            acc=ACC_L,
        )

        safe.safe_amovej(
            label="Joint1_home_return",
            target=joint1,
            vel=VELOCITY_J,
            acc=ACC_J,
        )

        gripper_home()

        print("[DONE] pick tumbler task complete")

    except Exception as e:
        print(f"[ERROR] perform_task failed: {e}")

        if compliance_enabled:
            try:
                print("[COMPLIANCE] emergency off")
                release_compliance_ctrl()
            except Exception as release_error:
                print(f"[WARN] compliance release failed: {release_error}")

        raise


def main(args=None):
    """메인 함수: ROS2 노드 초기화 및 동작 수행."""

    rclpy.init(args=args)

    node = rclpy.create_node("pick_tumbler", namespace=ROBOT_ID)
    DR_init.__dsr__node = node

    try:
        initialize_robot()
        perform_task()

    except KeyboardInterrupt:
        print("\n[INTERRUPTED] user keyboard interrupt")
        raise

    except Exception as e:
        print(f"[ERROR] unexpected error: {e}")
        raise

    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()