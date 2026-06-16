import rclpy
import DR_init
import time

# 로봇 설정 상수
ROBOT_ID = "dsr01"
ROBOT_MODEL = "m0609"
ROBOT_TOOL = "Tool Weight"
ROBOT_TCP = "GripperDA_v1"

# 이동 속도 및 가속도
VELOCITY_J = 60
ACC_J = 80

VELOCITY_L = 150
ACC_L = 200

ROLL_VEL = 40
ROLL_ACC = 50

# DR_init 설정
DR_init.__dsr__id = ROBOT_ID
DR_init.__dsr__model = ROBOT_MODEL


def initialize_robot():
    """로봇의 Tool과 TCP를 설정"""
    from DSR_ROBOT2 import set_tool, set_tcp, get_tool, get_tcp, ROBOT_MODE_MANUAL, ROBOT_MODE_AUTONOMOUS
    from DSR_ROBOT2 import get_robot_mode, set_robot_mode

    # Tool과 TCP 설정 시 매뉴얼 모드로 변경해서 진행
    set_robot_mode(ROBOT_MODE_MANUAL)
    set_tool(ROBOT_TOOL)
    set_tcp(ROBOT_TCP)
    
    set_robot_mode(ROBOT_MODE_AUTONOMOUS)
    time.sleep(2)  # 설정 안정화를 위해 잠시 대기

    print("#" * 50)
    print("Initializing robot with the following settings:")
    print(f"ROBOT_ID: {ROBOT_ID}")
    print(f"ROBOT_MODEL: {ROBOT_MODEL}")
    print(f"ROBOT_TCP: {get_tcp()}") 
    print(f"ROBOT_TOOL: {get_tool()}")
    print(f"ROBOT_MODE (0:Manual, 1:Auto): {get_robot_mode()}")
    print(f"VELOCITY: {VELOCITY_J, VELOCITY_L}")
    print(f"ACC: {ACC_J, ACC_L}")
    print("#" * 50)


def perform_task():
    """로봇이 수행할 작업"""
    print("Performing task...")
    from DSR_ROBOT2 import posj, posx, movej, movel, movec, wait, set_digital_output, task_compliance_ctrl, release_compliance_ctrl, set_desired_force, release_force, DR_FC_MOD_REL, set_ref_coord, DR_TOOL, DR_BASE

    # 1. 초기 위치 및 요청하신 목표 위치 설정
    P1 = posj(0, 0, 90, 0, 90, 0)
    P2 = posj(91.19, 39.53, 57.64, -27.0, 82.56, 92.68)
    P3 = posx(166.67, 668.38, 60.03, 2.87, 153.4, 1.3)
    P4 = posx(205.01, 665.59, 74.41, 131.8, 174.96, 134.11)
    P5 = posx(215.63, 619.17, 211.18, 80.24, 170.11, 82.56)
    P6 = posx(353.47, 566.18, 165.35, 122.26, 179.47, 122.69)
    P7 = posx(355.84, 569.91, 153.28, 148.08, 179.38, 148.55) # movec 1
    P8 = posx(391.49, 566.81, 141.48, 151.04, 178.9, 151.58) # movec 2
    P9 = posx(401.96, 568.34, 120.73, 165.50, 178.06, 165.96) # movec 3
    P10 = posx(302.24, 565.55, 121.22, 155.28, 176.67, 155.89) # movec 4
    P11 = posx(218.54, 485.50, 173.14, 151.33, 175.96, 151.77) 
    P12 = posx(208.05, 667.41, 95.32, 153.88, 175.16, 154.45)
    P13 = posx(184.79, 667.04, 72.46, 13.09, 171.85, 12.44)
    P14 = posj(79.02, 46.94, 34.88, -6.55, 94.37, 77.33)
    

    fd = [0, 0, -20, 0, 0, 0]
    fctrl_dir= [0, 0, 1, 0, 0, 0]

    try:     
        # Gripper open, 초기 위치로 이동
        print("Gripper open")
        set_digital_output(1)
        set_digital_output(2)
        set_digital_output(3)
            
        print("Moving to Point1")
        movej(P1, vel=VELOCITY_J, acc=ACC_J)

        # Roller 위치로 이동
        print("Moving to Point2")
        movej(P2, vel=VELOCITY_J, acc=ACC_J)

        print(f"Moving to Point3") 
        movel(P3, vel=VELOCITY_L, acc=ACC_L)

        print("Gripper close")
        set_digital_output(-2)
        set_digital_output(-3)
        set_digital_output(1)
        wait(1.0)
        
        print(f"Compliance control ON") 
        task_compliance_ctrl([3000, 3000, 500, 200, 200, 200])

        print(f"Moving to Point4")
        movel(P4, vel=VELOCITY_L, acc=ACC_L)

        print(f"Moving to Point5")
        movel(P5, vel=VELOCITY_L, acc=ACC_L)

        print(f"Compliance control OFF")
        release_compliance_ctrl()

        print(f"Compliance control ON")
        task_compliance_ctrl([3000, 3000, 100, 30, 30, 30]) # 텀블러 이탈 방지를 위해 강성 조절


        set_desired_force(fd, dir=fctrl_dir, mod=DR_FC_MOD_REL) # 텀블러 이탈 방지를 위해 Z축 힘 조절.

        # Rolling 시작

        print(f"Moving to Point6")
        movel(P9, vel=ROLL_VEL, acc=ROLL_ACC)

        movel(P10, vel=ROLL_VEL, acc=ROLL_ACC)
        
        release_force()

        # Rolling 끝


        print(f"Compliance control OFF")
        release_compliance_ctrl()

        print(f"Moving to Point10")
        movel(P10, vel=VELOCITY_L, acc=ACC_L)

        print(f"Moving to Point11")
        movel(P11, vel=VELOCITY_L, acc=ACC_L)


        print("Moving to Point12")
        movel(P12, vel=VELOCITY_L, acc=ACC_L)

        print(f"Moving to Point13") 
        movel(P13, vel=VELOCITY_L, acc=ACC_L)

        print("Gripper off")
        set_digital_output(1)
        set_digital_output(2)
        set_digital_output(3)

        print("Moving to Point14")
        movej(P14, vel=VELOCITY_J, acc=ACC_J)

        print("Gripper off")
        set_digital_output(1)
        set_digital_output(2)
        set_digital_output(3)

        print("Moving to Point1")
        movej(P1, vel=VELOCITY_J, acc=ACC_J)

        print("Gripper initializing")
        set_digital_output(-3)
        set_digital_output(-1)
        set_digital_output(2)
        

    except Exception as e:
        print(f"Error in perform_task: {e}")
        print("Moving to Point1")
        movej(P1, vel=VELOCITY_J, acc=ACC_J)


def main(args=None):
    """메인 함수: ROS2 노드 초기화 및 동작 수행"""
    rclpy.init(args=args)
    # namespace를 ROBOT_ID로 설정하여 노드 생성
    node = rclpy.create_node("pick_roller", namespace=ROBOT_ID)

    # DR_init에 노드 설정 (DSR_ROBOT2 내부 로직에서 참조)
    DR_init.__dsr__node = node

    try:
        # 초기화는 한 번만 수행
        initialize_robot()

        # 작업 수행
        perform_task()

    except KeyboardInterrupt:
        print("\nNode interrupted by user. Shutting down...")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    finally:
        # 노드 종료 및 리소스 해제
        node.destroy_node()
        rclpy.shutdown()

if __name__ == "__main__":
    main()