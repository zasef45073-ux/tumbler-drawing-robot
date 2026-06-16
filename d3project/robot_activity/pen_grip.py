#!/usr/bin/env python3

import time

import rclpy
import DR_init

ROBOT_ID = "dsr01"
ROBOT_MODEL = "m0609"

VEL = 100
ACC = 200

DR_init.__dsr__id = ROBOT_ID
DR_init.__dsr__model = ROBOT_MODEL


def main(args=None):
    rclpy.init(args=args)

    node = rclpy.create_node("pen_grip", namespace=ROBOT_ID)
    DR_init.__dsr__node = node

    try:
        from DSR_ROBOT2 import (
            amovel,
            amovej,
            movej,
            check_motion,
            wait,
            set_digital_output,
            DR_BASE,
        )
        from DR_common2 import posx

    except ImportError as e:
        print(f"[ERROR] DSR import 실패: {e}")
        print("아래 source 확인:")
        print("source /opt/ros/humble/setup.bash")
        print("source ~/cobot_ws/install/setup.bash")
        rclpy.shutdown()
        return

    def wait_motion_done(label="motion"):
        """
        amovej/amovel 이후 해당 motion이 끝날 때까지 대기한다.

        핵심:
        - amove는 비동기라서 그냥 쓰면 다음 명령으로 바로 넘어감
        - check_motion()이 0이 될 때까지 기다려서 기존 movej/movel처럼 순차 실행
        """

        print(f"[WAIT] {label} 완료 대기 시작")

        # amove 명령 직후 motion 상태 반영까지 짧게 대기
        wait(0.1)

        while True:
            motion_state = check_motion()

            if motion_state == 0:
                break

            wait(0.05)

        print(f"[WAIT] {label} 완료 확인")

    def initialize_robot():
        from DSR_ROBOT2 import set_robot_mode, ROBOT_MODE_AUTONOMOUS
        
    
        # 로봇을 오토 모드로 확실하게 전환
        set_robot_mode(ROBOT_MODE_AUTONOMOUS)
        time.sleep(1.0) # 모드 전환 후 버퍼가 안정화될 때까지 잠시 대기

    def safe_amovel(label, target):
        """
        movel 대체용.
        amovel + check_motion 대기 루프로 동기식처럼 동작.
        """

        print(f"[AMOVEL] {label}")
        amovel(target, vel=VEL, acc=ACC, ref=DR_BASE)
        wait_motion_done(label)

    def safe_amovej(label, target):
        """
        movej 대체용.
        amovej + check_motion 대기 루프로 동기식처럼 동작.
        """

        print(f"[AMOVEJ] {label}")
        amovej(target, vel=VEL, acc=ACC)
        wait_motion_done(label)

    # 네가 외운 그리퍼 동작을 단수 함수로 감싼 것
    def gripper_close():
        # 기존: set_digital_outputs([1, -2])
        set_digital_output(1)    # DO 1 ON
        set_digital_output(-2)   # DO 2 OFF
        set_digital_output(-3)   # DO 3 OFF

    def gripper_open():
        # 기존: set_digital_outputs([-1, 2])
        set_digital_output(-1)   # DO 1 OFF
        set_digital_output(-3)   # DO 3 OFF
        set_digital_output(2)    # DO 2 ON

    # ============================================================
    # 좌표 정의
    # 주의: 사용자가 보낸 최신 pen_grip.py 좌표 그대로 유지
    # ============================================================

    p_ready = posx([367.200,   3.830, 195.200, 154.40, 179.97, 154.78])
    p_above = posx([565.13, -198.31, 192.26, 89.38, 179.49, 90.06])
    p_pick  = posx([565.13, -198.31, 92.26, 89.38, 179.49, 90.06])

    p_b1above = posx([329.94, -164.60, 211.28, 60.77, 179.68, 61.39])
    p_b1pick = posx([330.63, -164.77, 6.33, 90.77, 179.75, 91.41])
    p_b1paper = posx([667.52, -89.17, 143.63, 124.88, 178.47, 170.44])
    p_b1release = posx([674.87, -90.96, 56.31, 142.85, 178.03, -171.34])

    p_b2above = posx([397.34, -165.35, 209.48, 28.07, 179.80, 28.61])
    p_b2pick = posx([399.06, -166.32, 2.32, 73.46, 179.92, 74.06])
    p_b2paper = posx([570.43, -1.47, 209.24, 70.12, 179.35, 115.52])
    p_b2release = posx([583.72, -3.91, 49.73, 70.59, 179.42, 116.10])

    try:
        initialize_robot()

        print("[START] pen grip sequence")

        safe_amovel("p_ready", p_ready)

        safe_amovel("p_b1above", p_b1above)

        safe_amovel("p_b1pick", p_b1pick)

        print("[GRIPPER] close")
        gripper_close()

        print("[WAIT] 0.3 sec")
        time.sleep(0.3)

        safe_amovel("p_b1above", p_b1above)

        safe_amovel("p_b1paper", p_b1paper)

        safe_amovel("p_b1release", p_b1release)

        print("[GRIPPER] open")
        gripper_open()

        print("[WAIT] 0.3 sec")
        time.sleep(0.3)

        safe_amovel("p_b1paper", p_b1paper)

        safe_amovel("p_b2above", p_b2above)

        safe_amovel("p_b2pick", p_b2pick)

        print("[GRIPPER] close")
        gripper_close()

        print("[WAIT] 0.3 sec")
        time.sleep(0.3)

        safe_amovel("p_b2above", p_b2above)

        safe_amovel("p_b2paper", p_b2paper)

        safe_amovel("p_b2release", p_b2release)

        print("[GRIPPER] open")
        gripper_open()

        print("[WAIT] 0.3 sec")
        time.sleep(0.3)

        safe_amovel("p_b2paper", p_b2paper)

        # safe_amovel("p_above", p_above)

        # safe_amovel("p_pick", p_pick)

        # print("[GRIPPER] close")
        # gripper_close()

        # print("[WAIT] 0.3 sec")
        # time.sleep(0.3)

        # safe_amovel("p_above", p_above)

        print("[DONE] complete")

    except Exception as e:
        print(f"[ERROR] 실행 중 오류 발생: {e}")
        raise

    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()