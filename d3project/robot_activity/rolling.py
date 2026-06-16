import rclpy
import DR_init
import time
import math

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

ROLL_VEL = 30
ROLL_ACC = 30

# DR_init 설정
DR_init.__dsr__id = ROBOT_ID
DR_init.__dsr__model = ROBOT_MODEL


def initialize_robot():
    """로봇의 Tool과 TCP를 설정"""
    from DSR_ROBOT2 import set_tool, set_tcp, get_tool, get_tcp, ROBOT_MODE_MANUAL, ROBOT_MODE_AUTONOMOUS
    from DSR_ROBOT2 import get_robot_mode, set_robot_mode

    set_robot_mode(ROBOT_MODE_MANUAL)
    set_tool(ROBOT_TOOL)
    set_tcp(ROBOT_TCP)
    
    set_robot_mode(ROBOT_MODE_AUTONOMOUS)
    time.sleep(2)

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


def calculate_rolling_points(p_center, diameter, max_angle=25.0):
    """중심점(P7)과 텀블러 지름을 기반으로 원호 궤적 좌표 4개를 생성"""
    from DSR_ROBOT2 import posx
    
    radius = diameter / 2.0
    points = []
    angles = [max_angle / 2.0, max_angle, -max_angle / 2.0, -max_angle]
    
    for angle_deg in angles:
        theta = math.radians(angle_deg)
        dx = radius * math.sin(theta)
        dz = -radius * (1 - math.cos(theta))
        
        new_pos = list(p_center)
        new_pos[0] += dx
        new_pos[2] += dz
        new_pos[3] += angle_deg * 0.6  
        new_pos[5] += angle_deg * 0.6  
        
        points.append(posx(*new_pos))
        
    return points


# ==========================================
# 각 기능별 분리된 함수들
# ==========================================

def open_gripper():
    """그리퍼 열기"""
    from DSR_ROBOT2 import set_digital_output
    print("Gripper open")
    set_digital_output(1)
    set_digital_output(2)
    set_digital_output(3)

def move_to_initial(p1):
    """초기 위치로 이동"""
    from DSR_ROBOT2 import movej
    print("초기 위치(P1)로 이동")
    movej(p1, vel=VELOCITY_J, acc=ACC_J)

def move_to_roller(p2, p3):
    """롤러 대기 위치로 이동"""
    from DSR_ROBOT2 import movej, movel
    print("Roller 위치로 이동")
    movej(p2, vel=VELOCITY_J, acc=ACC_J)
    movel(p3, vel=VELOCITY_L, acc=ACC_L)

def close_gripper():
    """그리퍼 닫기"""
    from DSR_ROBOT2 import set_digital_output, wait
    print("Gripper close")
    set_digital_output(-2)
    set_digital_output(-3)
    set_digital_output(1)
    wait(1.0)

def pickup_roller(p4, p5):
    """롤러 픽업 및 순응 제어"""
    from DSR_ROBOT2 import movel, task_compliance_ctrl, release_compliance_ctrl
    print("Compliance control ON")
    print("Roller pick up 시작")
    task_compliance_ctrl([3000, 3000, 500, 200, 200, 200])
    movel(p4, vel=VELOCITY_L, acc=ACC_L)
    movel(p5, vel=VELOCITY_L, acc=ACC_L)
    print("Compliance control OFF")
    release_compliance_ctrl()

def perform_rolling(p6, p7, p_right_up, p_right_press, p_left_up, p_left_press, diameter, max_angle):
    """사전 동작(P7->P6->좌우 누르기) 후 동적 좌표를 생성하여 롤링 작업 수행"""
    from DSR_ROBOT2 import movej, movel, movec, task_compliance_ctrl, release_compliance_ctrl, set_desired_force, release_force, DR_FC_MOD_REL, wait
    fd = [0, 0, -20, 0, 0, 0]
    fctrl_dir = [0, 0, 1, 0, 0, 0]

    print("Rolling 및 사전 누르기 시퀀스 시작")
    print("힘, 순응제어 시작")
    task_compliance_ctrl([500, 1000, 2000, 30, 30, 30])
    set_desired_force(fd, dir=fctrl_dir, mod=DR_FC_MOD_REL)
    
    # 1. 요청하신 시퀀스: P6 -> P7 -> P6 이동
    print("1. 롤링 시작점(P7) 이동 후 다시 대피(P6)")
    movel(p6, vel=30, acc=40)
    movel(p7, vel=30, acc=40)
    movel(p6, vel=30, acc=40)
    
    # 2. 롤러 오른쪽 위 -> 오른쪽 누르기
    print("2. 롤러 오른쪽 사전 누르기")
    movel(p_right_up, vel=60, acc=80)
    movel(p_right_press, vel=60, acc=80)
    # 표면을 긁으며 다음 좌표로 이동하지 않도록 다시 위로 들어 올림
    movel(p_right_up, vel=60, acc=80)

    # 3. 롤러 왼쪽 위 -> 왼쪽 누르기
    print("3. 롤러 왼쪽 사전 누르기")
    movel(p_left_up, vel=60, acc=80)
    # 주의: 전달해주신 p_left_press가 posj 형태이므로 임시로 movej를 적용해 두었습니다. 
    # 실제 티칭 시 직교좌표(posx)로 수정하셨다면 아래 코드를 movel(p_left_press, vel=ROLL_VEL, acc=ROLL_ACC)로 변경하세요.
    movel(p_left_press, vel=60, acc=80)
    movel(p_left_up, vel=60, acc=80)

    # 4. 다시 P6 -> P7 이동 후 본격적인 롤링 시작
    print("4. 본격적인 Rolling을 위해 복귀 (P6 -> P7)")
    movel(p6, vel=ROLL_VEL, acc=ROLL_ACC)
    
    # 동적 좌표 생성
    dynamic_pts = calculate_rolling_points(p7, diameter, max_angle)
    p8_dyn = dynamic_pts[0]
    p9_dyn = dynamic_pts[1]
    p10_dyn = dynamic_pts[2]
    p11_dyn = dynamic_pts[3]

    print("Rolling 시작 (총 3세트, 세트당 2회 반복)")
    for set_idx in range(3):
        print(f"--- Rolling 세트 {set_idx + 1}/3 진행 중 ---")
        
        # 롤링 시작점(P7)으로 이동
        movel(p7, vel=ROLL_VEL, acc=ROLL_ACC)
        
        # 원호 궤적 2회 반복
        for _ in range(2):
            movec(p8_dyn, p9_dyn, vel=ROLL_VEL, acc=ROLL_ACC)
            movec(p8_dyn, p7, vel=ROLL_VEL, acc=ROLL_ACC)
            movec(p10_dyn, p11_dyn, vel=ROLL_VEL, acc=ROLL_ACC)
            movec(p10_dyn, p7, vel=ROLL_VEL, acc=ROLL_ACC)
            
        # 첫 번째와 두 번째 세트 종료 후 P6으로 복귀하여 3초 대기
        if set_idx < 2:
            print("텀블러 회전을 위해 P6 위치로 대피 및 3초 대기...")
            movel(p6, vel=ROLL_VEL, acc=ROLL_ACC)
            wait(3.0)  # 작업자가 텀블러를 굴릴 수 있도록 3초간 대기
            
    release_force()
    release_compliance_ctrl()
    print("Rolling 끝")

def return_roller(p11_ret, p12, p13, p14):
    """롤러 원위치 및 로봇 팔 대기 위치(P14)로 이동"""
    from DSR_ROBOT2 import movej, movel, set_digital_output
    print("Roller 원위치")
    movel(p11_ret, vel=VELOCITY_L, acc=ACC_L)
    movel(p12, vel=VELOCITY_L, acc=ACC_L)
    movel(p13, vel=VELOCITY_L, acc=ACC_L)
    
    print("Gripper off")
    set_digital_output(1)
    set_digital_output(2)
    set_digital_output(3)
    movej(p14, vel=VELOCITY_J, acc=ACC_J)
    
    print("Gripper initializing")
    set_digital_output(-1)
    set_digital_output(-3)
    set_digital_output(2)


# ==========================================
# 메인 작업 수행 함수
# ==========================================

def perform_task():
    """정의된 세부 함수들을 순서대로 실행"""
    print("Performing task...")
    from DSR_ROBOT2 import posj, posx
    
    # 1. 기존 사용 좌표 정의
    P1 = posj(0, 0, 90, 0, 90, 0)
    P2 = posj(91.19, 39.53, 57.64, -27.0, 82.56, 92.68) 
    P3 = posx(167.95, 670.79, 59.31, 3.15, 153.51, 1.61)
    P4 = posx(205.01, 665.59, 74.41, 131.8, 174.96, 134.11)
    P5 = posx(215.63, 619.17, 211.18, 80.24, 170.11, 82.56)
    P6 = posx(353.47, 566.18, 165.35, 122.26, 179.47, 122.69)
    P7 = posx(355.84, 569.91, 148.28, 148.08, 179.38, 148.55) 
    P11_ret = posx(218.54, 485.50, 273.14, 151.33, 175.96, 151.77) 
    P12 = posx(208.05, 667.41, 95.32, 153.88, 175.16, 154.45)
    P13 = posx(184.79, 671.04, 63.46, 13.09, 171.85, 12.44)
    P14 = posj(79.02, 46.94, 34.88, -6.55, 94.37, 77.33)

    # 2. 추가된 사전 누르기 좌표 정의
    # !!! 주의: 요청글에서 '왼쪽 위'와 '왼쪽 누르기'가 '오른쪽 위' 좌표와 동일하게 입력되었습니다. 실제 티칭 좌표로 수정 필수 !!!
    P_right_up = posx(376.49, 562.59, 159.74, 42.73, -179.19, 42.95)
    P_right_press = posx(379.44, 565.21, 145.04, 46.19, -178.71, 46.52)
    
    P_left_up = posx(313.03, 562.59, 190.60, 42.67, -179.20, 42.89)
    # 왼쪽 누르기가 직교좌표(posx)인 경우 아래를 posx()로 변경해 주셔야 합니다.
    P_left_press = posx(313.03, 562.59, 130.04, 42.67, -179.20, 42.89)

    TUMBLER_DIAMETER = 80.0
    ROLLING_MAX_ANGLE = 50.0

    try:     
        open_gripper()
        move_to_initial(P1)
        
        move_to_roller(P2, P3)
        close_gripper()
        pickup_roller(P4, P5)
        
        
        perform_rolling(P6, P7, P_right_up, P_right_press, P_left_up, P_left_press, TUMBLER_DIAMETER, ROLLING_MAX_ANGLE)
        
        return_roller(P11_ret, P12, P13, P14)
        
        move_to_initial(P1)

    except Exception as e:
        print(f"Error in perform_task: {e}")
        move_to_initial(P1)


def main(args=None):
    rclpy.init(args=args)
    node = rclpy.create_node("rolling", namespace=ROBOT_ID)
    DR_init.__dsr__node = node

    try:
        initialize_robot()
        perform_task()
    except KeyboardInterrupt:
        print("\nNode interrupted by user. Shutting down...")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == "__main__":
    main()