import rclpy
import DR_init
import time

# 1. 로봇 및 작업 설정 상수
ROBOT_ID = "dsr01"
ROBOT_MODEL = "m0609"
ROBOT_TOOL = "Tool Weight"
ROBOT_TCP = "GripperDA_v1"

# 이동 속도 및 가속도 설정
VELOCITY_J = 40  # 관절 이동 속도 (%)
ACC_J = 60       # 관절 가속도 (%)

# DR_init 설정 (DSR 로봇 초기화용)
DR_init.__dsr__id = ROBOT_ID
DR_init.__dsr__model = ROBOT_MODEL

def initialize_robot():
    """로봇의 Tool, TCP 및 모드 설정"""
    from DSR_ROBOT2 import set_tool, set_tcp, get_tool, get_tcp, ROBOT_MODE_MANUAL, ROBOT_MODE_AUTONOMOUS
    from DSR_ROBOT2 import get_robot_mode, set_robot_mode

    # 설정을 위해 일시적으로 매뉴얼 모드 변경
    set_robot_mode(ROBOT_MODE_MANUAL)
    set_tool(ROBOT_TOOL)
    set_tcp(ROBOT_TCP)
    
    # 작업 수행을 위해 오토 모드로 복귀
    set_robot_mode(ROBOT_MODE_AUTONOMOUS)
    time.sleep(1)

    print("-" * 30)
    print(f"Robot ID: {ROBOT_ID} / Model: {ROBOT_MODEL}")
    print(f"TCP: {get_tcp()} / Tool: {get_tool()}")
    print(f"Mode: {'Auto' if get_robot_mode() == 1 else 'Manual'}")
    print("-" * 30)


# ==========================================
# 각 기능별 분리된 함수들
# ==========================================

def move_to_initial(jready):
    """초기 대기 위치로 이동"""
    from DSR_ROBOT2 import movej
    print("Initialize: 초기 위치로 이동")
    movej(jready, vel=VELOCITY_J, acc=ACC_J)

def init_and_open_gripper():
    """그리퍼 초기화 및 열기 (100mm)"""
    from DSR_ROBOT2 import set_digital_output
    print("Gripper 초기화 및 Open")
    # 그리퍼 초기화
    set_digital_output(-1)
    set_digital_output(-2)
    set_digital_output(-3)
    
    # 그리퍼 open
    set_digital_output(1)
    set_digital_output(2)
    set_digital_output(3)

def move_to_glue(j1):
    """목공풀 대기 위치로 이동"""
    from DSR_ROBOT2 import movej, wait
    print("Moving to j1 (목공풀 위치)...")
    movej(j1, vel=VELOCITY_J, acc=ACC_J)
    

def pickup_glue():
    """그리퍼 닫기 (35mm) 및 대기"""
    from DSR_ROBOT2 import set_digital_output, wait
    print("Gripper Close (Activating Digital Output)")
    set_digital_output(-1)
    set_digital_output(2)
    set_digital_output(3)
    wait(2.0)

def calculate_zigzag_points(j_standby, length_mm, step_mm):
    """
    조인트 대기 위치(j_standby)를 직교 좌표로 변환한 뒤,
    ㄹ자 패턴의 6개 꼭짓점 직교 좌표(posx)를 반환합니다.
    """
    from DSR_ROBOT2 import fkin, posx
    
    # 1. 정기구학: 조인트 대기 위치를 직교 좌표(posx)로 변환
    p_start = fkin(j_standby)
    p_base = list(p_start)  # [X, Y, Z, Rx, Ry, Rz]
    
    # p1: 시작점 (대기 위치)
    p1 = posx(*p_base)
    
    # p2: 위로 80mm 이동 (Y축 +)
    p2_list = list(p_base)
    p2_list[1] += length_mm
    p2 = posx(*p2_list)
    
    # p3: 오른쪽으로 20mm 이동 (X축 +, Y축은 p2 위치 유지)
    p3_list = list(p2_list)
    p3_list[0] += step_mm
    p3 = posx(*p3_list)
    
    # p4: 아래로 80mm 이동 (Y축 -, 원래 Y 위치로 복귀)
    p4_list = list(p3_list)
    p4_list[1] -= length_mm
    p4 = posx(*p4_list)
    
    # p5: 오른쪽으로 20mm 이동 (X축 +)
    p5_list = list(p4_list)
    p5_list[0] += step_mm
    p5 = posx(*p5_list)
    
    # p6: 위로 80mm 이동 (Y축 +)
    p6_list = list(p5_list)
    p6_list[1] += length_mm
    p6 = posx(*p6_list)
    
    return [p1, p2, p3, p4, p5, p6]


def apply_glue_zigzag(j_standby, length_mm, step_mm):
    """
    대기 위치(j_standby)로 이동한 후, 계산된 포인트를 따라
    목공풀을 ㄹ자 모양으로 도포합니다.
    """
    from DSR_ROBOT2 import movej, movel, set_digital_output, wait
    
    # 1. 도포 대기 시작 위치로 이동
    print("Moving to standby position (도포 대기 위치)...")
    movej(j_standby, vel=VELOCITY_J, acc=ACC_J)
    
    # 2. ㄹ자 꼭짓점 직교 좌표(posx) 6개 생성
    zigzag_pts = calculate_zigzag_points(j_standby, length_mm, step_mm)
    p1 = zigzag_pts[0] # 시작점
    p2 = zigzag_pts[1]
    p3 = zigzag_pts[2]
    p4 = zigzag_pts[3]
    p5 = zigzag_pts[4]
    p6 = zigzag_pts[5]
    
    # 3. 풀 짜기 시작
    # set_modbus_output을 이용해서 해결하거나
    # set_digital_output(-2)
    # set_digital_output(-3)
    # set_digital_output(1)
      
    print("풀 도포 시작 (디지털 출력 ON)...")
    set_digital_output(-2)
    set_digital_output(-1)
    set_digital_output(3)
    wait(2.0) # 풀이 나올 때까지 대기
    
    # 4. 직교 좌표(posx)를 이용해 직선(movel)으로 ㄹ자 궤적 이동
    # 이미 p1 위치에 있으므로 p2부터 순차적으로 이동합니다.
    print(f"ㄹ자 도포 진행 중 (길이: {length_mm}mm, 간격: {step_mm}mm)...")
    movel(p2, vel=10, acc=20) # 위로
    movel(p3, vel=10, acc=20) # 오른쪽으로
    movel(p4, vel=10, acc=20) # 아래로
    movel(p5, vel=10, acc=20) # 오른쪽으로
    movel(p6, vel=10, acc=20) # 위로
    
    print("ㄹ자 도포 완료.")

def move_to_standby(j2, j3):
    """풀 도포 전 접근/대기 위치로 이동"""
    from DSR_ROBOT2 import movej
    print("Moving to j2, j3 (도포 대기 위치)...")
    movej(j2, vel=VELOCITY_J, acc=ACC_J)
    movej(j3, vel=VELOCITY_J, acc=ACC_J)


def return_glue(j2,j1):
    """목공풀 원위치 복귀 및 그리퍼 해제"""
    from DSR_ROBOT2 import movej, set_digital_output, wait
    print("풀 원위치(j2,j1)로 이동 및 놓기")
    movej(j2, vel=VELOCITY_J, acc=ACC_J)
    movej(j1, vel=VELOCITY_J, acc=ACC_J)
    
    set_digital_output(-1)
    set_digital_output(-3)
    set_digital_output(2)

    wait(0.5)


# ==========================================
# 메인 작업 수행 함수
# ==========================================

def perform_task():
    """요청하신 7개 좌표 이동 및 그리퍼 제어 작업"""
    from DSR_ROBOT2 import posj

    # 2. 관절 좌표(posj) 정의
    jready = posj(0.0, 0.0, 90.0, 0.0, 90.0, 0.0)
    j1 = posj(37.19, 60.38, 80.25, 116.88, 69.77, -56.33)
    j2 = posj(37.01, 54.26, 80.75, 114.81, 67.57, -50.95)
    j3 = posj(26.55, 38.31, 117.31, 112.70, 77.38, -222.56)
    length_mm=80.0
    step_mm=20.0
    
    try:
        # 시퀀스 제어
        move_to_initial(jready)
        init_and_open_gripper()
        
        move_to_glue(j1)
        pickup_glue()
        
        move_to_standby(j2,j3)
        apply_glue_zigzag(j3,length_mm, step_mm)
        
        return_glue(j2,j1)
        move_to_initial(jready)
        
        print("Task Completed Successfully.")

    except Exception as e:
        print(f"Error during task execution: {e}")
        print("에러 발생: 초기 위치로 복귀합니다.")
        move_to_initial(jready)


def main(args=None):
    """ROS2 노드 초기화 및 메인 루틴"""
    rclpy.init(args=args)
    # 네임스페이스를 포함한 노드 생성
    node = rclpy.create_node("glue_task", namespace=ROBOT_ID)

    # DSR_ROBOT2 라이브러리가 노드를 참조할 수 있도록 설정
    DR_init.__dsr__node = node

    try:
        initialize_robot()
        perform_task()
    except KeyboardInterrupt:
        print("\nProcess interrupted by user.")
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == "__main__":
    main()