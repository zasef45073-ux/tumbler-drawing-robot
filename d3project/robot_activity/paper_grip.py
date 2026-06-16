#!/usr/bin/env python3

import time

import rclpy
import DR_init

ROBOT_ID = "dsr01"
ROBOT_MODEL = "m0609"

VEL = 40
ACC = 50

DR_init.__dsr__id = ROBOT_ID
DR_init.__dsr__model = ROBOT_MODEL


def main(args=None):
    rclpy.init(args=args)

    node = rclpy.create_node("paper_to_tumbler", namespace=ROBOT_ID)
    DR_init.__dsr__node = node

    try:
        from DSR_ROBOT2 import (
            amovej,
            check_motion,
            wait,
            set_digital_output,
        )

    except ImportError as e:
        print(f"[ERROR] DSR import 실패: {e}")
        print("아래 source 확인:")
        print("source /opt/ros/humble/setup.bash")
        print("source ~/cobot_ws/install/setup.bash")
        rclpy.shutdown()
        return

    def wait_motion_done(label="motion"):
        """
        amovej 이후 해당 motion이 끝날 때까지 대기한다.

        핵심:
        - amovej는 비동기라서 그냥 쓰면 다음 명령으로 바로 넘어감
        - check_motion()이 0이 될 때까지 기다려서 기존 movej처럼 순차 실행
        """

        print(f"[WAIT] {label} 완료 대기 시작")

        # amovej 명령 직후 motion 상태 반영까지 짧게 대기
        wait(0.1)

        while True:
            motion_state = check_motion()

            if motion_state == 0:
                break

            wait(0.05)

        print(f"[WAIT] {label} 완료 확인")

    def safe_amovej(label, target):
        """
        movej 대체용.
        amovej + check_motion 대기 루프로 동기식처럼 동작.
        """

        print(f"[AMOVEJ] {label}")
        amovej(target, vel=VEL, acc=ACC)
        wait_motion_done(label)

    # -----------------------------
    # 그리퍼 동작
    # grip on  = 0,0,1
    # grip off = 0,1,0
    #
    # set_digital_output(n)  : DO n ON
    # set_digital_output(-n) : DO n OFF
    # -----------------------------
    def gripper_on():
        set_digital_output(-1)   # DO1 OFF
        set_digital_output(-2)   # DO2 OFF
        set_digital_output(3)    # DO3 ON

    def gripper_off():
        set_digital_output(-2)   # DO2 OFF
        set_digital_output(-3)    # DO3 OFF
        set_digital_output(1)   # DO1 ON

    # -----------------------------
    # Joint pose 정의
    # 단위: degree
    # 주의: 사용자가 보낸 최신 paper_grip.py 좌표 그대로 유지
    # -----------------------------
    p1 = [0.0, 0.0, 90.0, 0.0, 90.0, 0.0]

    j_01 = [18.75, 43.86, 28.83, 0.32, 107.28, 18.98]
    j_02 = [21.36, 52.62, 25.79, 85.12, -112.82, 82.77]
    j_03 = [31.16, 75.01, 39.76, 111.09, -116.5, 119.67]
    j_04 = [28.36, 72.12, 46.33, 110.88, -112.99, 122.51]

    j_05 = [32.0, 76.09, 37.01, 110.47, -117.72, 118.14]
    j_06 = [35.01, 3.11, 85.1, 176.68, -91.46, 120.46]
    j_home = [0.0, 0.0, 90.0, 0.0, 90.0, 0.0]

    j_07 = [56.67, 15.94, 82.85, 81.69, -56.03, 68.37]
    j_08 = [92.77, 54.22, 87.13, 93.61, -90.49, 142.2]
    j_09 = [95.35, 56.44, 87.24, 94.71, -92.56, 142.16]
    # 92.35, 56.63, 87.22, 92.45, -90.97, 142.2 원본

    j_10 = [101.99, 57.04, 85.51, 99.25, -96.18, 141.44]
    j_11 = [101.1, 5.62, 131.55, 98.52, -100.74, 141.44]

    try:
        print("[START] joint sequence")

        safe_amovej("p1", p1)

        safe_amovej("j_01", j_01)

        safe_amovej("j_02", j_02)

        safe_amovej("j_03", j_03)

        safe_amovej("j_04", j_04)

        print("[GRIPPER] ON = 0,0,1")
        gripper_on()

        print("[WAIT] 0.5 sec")
        time.sleep(0.5)

        safe_amovej("j_05", j_05)

        safe_amovej("j_06", j_06)

        safe_amovej("j_07", j_07)

        safe_amovej("j_08", j_08)

        safe_amovej("j_09", j_09)

        print("[GRIPPER] OFF = 0,1,0")
        gripper_off()

        wait_motion_done()

        safe_amovej("j_10", j_10)

        safe_amovej("j_11", j_11)

        safe_amovej("j_home", j_home)

        print("[DONE] complete")

    except Exception as e:
        print(f"[ERROR] 실행 중 오류 발생: {e}")
        raise

    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()