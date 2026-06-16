# ik_solver.py
# 두산 로봇 DRL movel()을 래핑하여 XYZ 좌표 기반으로 이동/드로잉을 수행하는 모듈.
# 실제 DRL 환경(DART-Studio)에서는 movel() 주석을 해제하고 사용한다.

from __future__ import annotations
from typing import Optional
import json
import os
# =============================================
# 캔버스 설정 (coord_transform.py와 맞출 것)
# =============================================
"""
안마르는 싸인펜
Z_DRAW: float = 125.3   # mm, 펜이 캔버스에 닿는 Z 높이
컴싸
Z_DRAW: float =   # mm, 펜이 캔버스에 닿는 Z 높이
"""
# 디폴트
Z_DRAW: float = 123.5   # mm, 펜이 캔버스에 닿는 Z 높이
Z_MOVE: float = 150.0   # mm, 획 사이 공중 이동 Z 높이
# 레드 
RED_Z_DRAW: float = 116.5   # mm, 펜이 캔버스에 닿는 Z 높이
RED_Z_MOVE: float = 135.0   # mm, 획 사이 공중 이동 Z 높이
# 블랙
BLACK_Z_DRAW: float = 122.5   # mm, 펜이 캔버스에 닿는 Z 높이
BLACK_Z_MOVE: float = 150.0   # mm, 획 사이 공중 이동 Z 높이

# TCP 자세 고정값 — 캔버스에 수직으로 내려찍는 자세 (rx=0, ry=180, rz=0)
RX: float = 0.0
RY: float = 180.0
RZ: float = 0.0

# =============================================
# DRL 연결 (윈도우 DART-Studio에서 활성화)
# =============================================
# from DRCF import *   # 두산 DRL 라이브러리 (윈도우에서 주석 해제)
import rclpy
import DR_init
import time

# 로봇 설정 상수 (필요에 따라 수정)
ROBOT_ID = "dsr01"
ROBOT_MODEL = "m0609"
ROBOT_TOOL = "Tool Weight"
ROBOT_TCP = "GripperDA_v1"

# 이동 속도 및 가속도 (필요에 따라 수정)
VELOCITY = 40
ACC = 60

# DR_init 설정
DR_init.__dsr__id = ROBOT_ID
DR_init.__dsr__model = ROBOT_MODEL

# 디지털 출력 상태
ON, OFF = 1, 0


# ============================================================
# 드로잉 진행률 기록
# ============================================================
_PROGRESS_ENABLED = False
_PROGRESS_FILE = ""
_PROGRESS_JOB_ID = ""
_PROGRESS_TOTAL_POINTS = 0
_PROGRESS_DONE_POINTS = 0
_PROGRESS_LAST_PERCENT = 0


def configure_drawing_progress(
    total_points: int,
    job_id: str = "",
    progress_file: str = "",
) -> None:
    """드로잉 진행률 기록을 시작한다."""

    global _PROGRESS_ENABLED, _PROGRESS_FILE, _PROGRESS_JOB_ID
    global _PROGRESS_TOTAL_POINTS, _PROGRESS_DONE_POINTS, _PROGRESS_LAST_PERCENT

    _PROGRESS_JOB_ID = str(job_id or "").strip()
    _PROGRESS_FILE = str(progress_file or "").strip()
    _PROGRESS_TOTAL_POINTS = max(0, int(total_points or 0))
    _PROGRESS_DONE_POINTS = 0
    _PROGRESS_LAST_PERCENT = 0
    _PROGRESS_ENABLED = bool(_PROGRESS_FILE and _PROGRESS_TOTAL_POINTS > 0)

    print("=" * 60)
    print("[DrawingProgress] configure")
    print(f"[DrawingProgress] enabled      : {_PROGRESS_ENABLED}")
    print(f"[DrawingProgress] job_id       : {_PROGRESS_JOB_ID}")
    print(f"[DrawingProgress] total_points : {_PROGRESS_TOTAL_POINTS}")
    print(f"[DrawingProgress] file         : {_PROGRESS_FILE}")
    print("=" * 60)

    if _PROGRESS_ENABLED:
        _write_progress_json(phase="ready", percent=0)


def _write_progress_json(phase: str, percent: int) -> None:
    """progress JSON 파일을 기록한다."""

    if not _PROGRESS_FILE:
        return

    folder = os.path.dirname(_PROGRESS_FILE)
    if folder:
        os.makedirs(folder, exist_ok=True)

    safe_total = max(0, int(_PROGRESS_TOTAL_POINTS or 0))
    safe_done = max(0, int(_PROGRESS_DONE_POINTS or 0))
    if safe_total > 0:
        safe_done = min(safe_done, safe_total)
    safe_percent = max(0, min(int(percent or 0), 100))

    data = {
        "jobId": _PROGRESS_JOB_ID,
        "drawingPhase": phase,
        "drawingPointIndex": safe_done,
        "drawingTotalPoints": safe_total,
        "drawingProgressPercent": safe_percent,
        "updatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    with open(_PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(
        f"[DrawingProgress] {phase} | "
        f"{safe_percent}% | "
        f"{safe_done}/{safe_total}"
    )


def mark_drawing_point_done() -> None:
    """실제 드로잉 point 하나가 완료되었을 때 호출한다."""

    global _PROGRESS_DONE_POINTS, _PROGRESS_LAST_PERCENT

    if not _PROGRESS_ENABLED or _PROGRESS_TOTAL_POINTS <= 0:
        return

    _PROGRESS_DONE_POINTS = min(_PROGRESS_DONE_POINTS + 1, _PROGRESS_TOTAL_POINTS)
    percent = max(0, min(int((_PROGRESS_DONE_POINTS / _PROGRESS_TOTAL_POINTS) * 100), 100))

    if percent > _PROGRESS_LAST_PERCENT:
        _PROGRESS_LAST_PERCENT = percent
        _write_progress_json(phase="drawing", percent=percent)


def finish_drawing_progress(success: bool = True) -> None:
    """드로잉 진행률 기록을 종료한다."""

    global _PROGRESS_DONE_POINTS, _PROGRESS_LAST_PERCENT

    if not _PROGRESS_ENABLED:
        return

    if success:
        _PROGRESS_DONE_POINTS = _PROGRESS_TOTAL_POINTS
        _PROGRESS_LAST_PERCENT = 100
        _write_progress_json(phase="done", percent=100)
    else:
        percent = max(0, min(int((_PROGRESS_DONE_POINTS / _PROGRESS_TOTAL_POINTS) * 100), 100))
        _write_progress_json(phase="stopped", percent=percent)


def initialize_robot():
    """로봇의 Tool과 TCP를 설정"""
    from DSR_ROBOT2 import set_tool, set_tcp,get_tool,get_tcp,ROBOT_MODE_MANUAL,ROBOT_MODE_AUTONOMOUS  # 필요한 기능만 임포트
    from DSR_ROBOT2 import get_robot_mode,set_robot_mode

    # Tool과 TCP 설정시 매뉴얼 모드로 변경해서 진행
    set_robot_mode(ROBOT_MODE_MANUAL)
    set_tool(ROBOT_TOOL)
    set_tcp(ROBOT_TCP)
    
    set_robot_mode(ROBOT_MODE_AUTONOMOUS)
    time.sleep(2)  # 설정 안정화를 위해 잠시 대기
    # 설정된 상수 출력
    print("#" * 50)
    print("Initializing robot with the following settings:")
    print(f"ROBOT_ID: {ROBOT_ID}")
    print(f"ROBOT_MODEL: {ROBOT_MODEL}")
    print(f"ROBOT_TCP: {get_tcp()}") 
    print(f"ROBOT_TOOL: {get_tool()}")
    print(f"ROBOT_MODE 0:수동, 1:자동 : {get_robot_mode()}")
    print(f"VELOCITY: {VELOCITY}")
    print(f"ACC: {ACC}")
    print("#" * 50)


# 포즈 한번 보내기
def perform_task(pos):
    """로봇이 수행할 작업"""
    print("Performing task...")
    from DSR_ROBOT2 import posx, movel,movej,set_ref_coord,wait  # 필요한 기능만 임포트

    # 초기 위치 및 목표 위치 설정
    JReady = [0, 0, 90, 0, 90, 0]
    pos_group = pos
    print(pos_group)
    for x,y,z,rx,ry,rz in pos_group:
        loc = posx([x,y,z,rx,ry,rz])
        print("movel")
        movel(loc, vel=VELOCITY, acc=ACC)
        time.sleep(0.2)
    movej(JReady, vel=VELOCITY, acc=ACC)
    
def perform_first():
    """로봇이 수행할 작업"""
    print("Performing task...")
    from DSR_ROBOT2 import posx, movel,movej

    # 초기 위치 및 목표 위치 설정
    JReady = [0, 0, 90, 0, 90, 0]
    movej(JReady, vel=VELOCITY, acc=ACC)
    time.sleep(0.2)


def move_to_xyz(
    x: float,
    y: float,
    z: float,
    vel: float = 50,
    acc: float = 30,
) -> None:
    """XYZ 좌표로 로봇 TCP를 직선 이동시킨다 (DRL movel 래퍼).

    Args:
        x: 목표 X 좌표 (mm)
        y: 목표 Y 좌표 (mm)
        z: 목표 Z 좌표 (mm)
        vel: 직선 속도 (mm/s)
        acc: 직선 가속도 (mm/s²)
    """
    from DSR_ROBOT2 import movel
    pose: list[float] = [x, y, z, RX, RY, RZ]

    # --- 실제 DRL 연결 시 아래 주석 해제 ---
    # 세밀한 그림도 고려
    movel(pose, vel=vel, acc=acc, radius= 8)

    # --- 시뮬/테스트용 출력 ---
    print(f"movel 호출 → x:{x:.2f}, y:{y:.2f}, z:{z:.2f}, rx:{RX}, ry:{RY}, rz:{RZ}, vel:{vel}, acc:{acc}")

# 원래 가속도 100 acc 60

def draw_path(
    xyz_points: list[tuple[float, float, float]],
    vel: float = 150,
    acc: float = 60,
    color: str = "black"
) -> None:
    """XYZ 좌표 시퀀스를 따라 이동하며 한 획을 그린다.

    첫 번째 점에 도달하기 전에 Z_MOVE 높이로 공중 이동한 뒤 Z_DRAW로 내려찍고,
    이후 점들은 전달된 z 값 그대로 이동한다. 획이 끝나면 마지막 위치에서 펜을 Z_MOVE로 올린다.

    Args:
        xyz_points: 순서대로 이동할 (x, y, z) 좌표 튜플 리스트
        vel: 직선 속도 (mm/s)
        acc: 직선 가속도 (mm/s²)
    """
    z_move : float = 123.5
    z_draw : float = 140
    # 디폴트
    if color =="red":
        z_draw = RED_Z_DRAW
        z_move = RED_Z_MOVE
    
    if color == "black":
        z_draw = BLACK_Z_DRAW
        z_move = BLACK_Z_MOVE
    
    if not xyz_points:
        print("[draw_path][WARN] xyz_points가 비어 있어 건너뜁니다.")
        return

    for i, (x, y, _) in enumerate(xyz_points):
        if i == 0:
            # 첫 점 위 공중으로 이동 (진행률 미포함)
            move_to_xyz(x, y, z_move, vel, acc)

        # 실제 드로잉 point 이동
        move_to_xyz(x, y, z_draw, vel, acc)

        # 실제 point 하나를 그린 직후 카운트
        mark_drawing_point_done()

    # 획 완료 후 펜 들어올리기 (진행률 미포함)
    last_x, last_y, _ = xyz_points[-1]
    move_to_xyz(last_x, last_y, z_move, vel, acc)
    print("획 완료, 펜 올림")

def wait_digital_input(sig_num):
    from DSR_ROBOT2 import get_digital_input,wait
    while not get_digital_input(sig_num):
        wait(0.5)
        print("Waiting for digital input...")

# Grip 동작
def grip():
        print("Gripping...")
        from DSR_ROBOT2 import set_digital_output,wait
        # release()
        set_digital_output(2, OFF)
        set_digital_output(3, OFF)
        set_digital_output(1, ON)
        wait(0.5)
    
# Release 동작
def release():
        from DSR_ROBOT2 import set_digital_output, get_digital_input, wait
        print("Releasing...")        
        set_digital_output(1, OFF)
        set_digital_output(2, ON)
        set_digital_output(1, OFF)
        wait(0.5)


import time

# ============================================================
# 설정
# ============================================================
GRIPPER_DELAY = 0.5
LIFT_OFFSET = 30.0
_BLOCK = 0

# ============================================================
# 펜 홀더 좌표 (절대 좌표)
# ============================================================

# ============================================================
# 펜 집기 (Pick Up)
# ============================================================
# 펜 스탠드로 가기

#!/usr/bin/env python3

# ============================================================
# 비동기를 대비하여 만듬
# ============================================================
def wait_motion_done(label="motion"):
    """amove 명령 이후 motion이 완료될 때까지 대기한다."""

    from DSR_ROBOT2 import check_motion, wait
    wait(0.1)

    while True:
        if check_motion() == 0:
            break
        wait(0.05)

def safe_amovel(label, target):
    """
    movel 대체용.
    amovel + check_motion 대기 루프로 동기식처럼 동작.
    """
    from DSR_ROBOT2 import amovel, DR_BASE
    print(f"[AMOVEL] {label}")
    amovel(target, vel=100, acc=60, ref=DR_BASE)
    wait_motion_done(label)

def safe_amovej(label, target):
    """
    movej 대체용.
    amovej + check_motion 대기 루프로 동기식처럼 동작.
    """
    from DSR_ROBOT2 import amovej
    print(f"[AMOVEJ] {label}")
    amovej(target, vel=100, acc=60)
    wait_motion_done(label)


def pick_up_pen(color):
    """지정한 색상의 펜을 홀더에서 집어 드는 함수.

    충돌 방지를 위해 수직 상승 → X축 이동 → Y축 이동 → 하강 -> 그립 → 상승 순서로
    직각 경로를 따라 이동한다.
    """
    from DSR_ROBOT2 import posx
    p_ready = posx([367.200, 3.830, 195.200, 154.40, 179.97, 154.78])

    # 각 색상 펜 홀더의 절대 좌표 (단위: mm)
    # z_up  : 홀더 바로 위 대기 높이 (수평 이동 시 사용)
    # z_down: 펜을 실제로 잡는 하강 높이 (그리퍼가 펜을 쥘 수 있는 위치)
    PEN_HOLDERS = {
        'black': 
            {'up': [570.44, -204.35, 170.57, 48.65 ,-179.25,139.32], 
            'down': [570.44, -204.35, 90.57, 48.65 ,-179.32, 139.32]},
        'red': {'up': [619.55, -202.31, 170.94, 20.85 ,-179.56, 111.49],
                'down': [619.55, -202.31, 84.94, 20.85 ,-179.56, 111.49]}
    
    }
    
    # 펜이 없는 경우 
    if color not in PEN_HOLDERS:
        print(f"[오류] 존재하지 않는 색상: {color}")
        return
    # 그리퍼 풀기 -> 다가가기
    #release()
    safe_amovel("p_ready", p_ready)

    release()
    # 펜위로 이동
    if color == 'red':        
        # 빨간펜 위로 가기
        up_pos= PEN_HOLDERS['red']['up']
        safe_amovel(label="grip_red",target= posx(up_pos))
        # 빨간펜 아래로 가기
        down_pos= PEN_HOLDERS['red']['down']
        safe_amovel(label="grip_red",target= posx(down_pos))
        # 빨간펜 집고 위로 올라가기 
        grip()
        up_pos= PEN_HOLDERS['red']['up']
        safe_amovel(label="grip_red",target= posx(up_pos)) 
    
    if color == 'black':     
        # 검은펜 잡기
        up_pos= PEN_HOLDERS['black']['up']
        safe_amovel(label="grip_black",target= posx(up_pos))
        down_pos= PEN_HOLDERS['black']['down']
        safe_amovel(label="grip_black",target= posx(down_pos))
        # 검은펜 집고 위로 올라가기 
        grip()
        up_pos= PEN_HOLDERS['black']['up']
        safe_amovel(label="grip_black",target= posx(up_pos)) 
    

    # 펜위로 돌아가기
    safe_amovel("p_ready", p_ready)
    print(f"\n>>> [{color}] 펜 집기 시작 (절대 좌표 이동)")


# ============================================================
# 펜 반납 (Release)
# ============================================================
def release_pen(color):
    # 펜을 받납하고 반납한 펜 위치보다 위로
    from DSR_ROBOT2 import posx
    LIFT_OFFSET = 50.0
    #'blue':  {'x': 656.9,  'y': -200.7,  'z_up': 200.0, 'z_down': 86.0},
    #'green': {'x': 710.3,  'y': -200.7,  'z_up': 200.0, 'z_down': 86.0}

    p_ready = posx([367.200, 3.830, 195.200, 154.40, 179.97, 154.78])

    # 각 색상 펜 홀더의 절대 좌표 (단위: mm)
    # z_up  : 홀더 바로 위 대기 높이 (수평 이동 시 사용)
    # z_down: 펜을 실제로 잡는 하강 높이 (그리퍼가 펜을 쥘 수 있는 위치)
    PEN_HOLDERS = {
        'black': 
            {'up': [570.44, -204.35, 170.57, 48.65 ,-179.25,139.32], 
            'down': [570.44, -204.35, 90.57, 48.65 ,-179.32, 139.32]},
        'red': {'up': [619.55, -202.31, 170.94, 20.85 ,-179.56, 111.49],
                'down': [619.55, -202.31, 84.94, 20.85 ,-179.56, 111.49]}
    
    }
    
    
    if color not in PEN_HOLDERS:
        print(f"[오류] 존재하지 않는 색상: {color}")
        return
    
    # 펜위로 이동
    if color == 'red':        
        # 빨간펜 위로 가기
        up_pos= PEN_HOLDERS['red']['up']
        safe_amovel(label="grip_red",target= posx(up_pos))
        # 빨간펜 아래로 가기
        down_pos= PEN_HOLDERS['red']['down']
        safe_amovel(label="grip_red",target= posx(down_pos))
        # 빨간펜 집고 위로 올라가기 
        release()
        up_pos= PEN_HOLDERS['red']['up']
        safe_amovel(label="grip_red",target= posx(up_pos)) 

    if color == 'black':     
        # 검은펜 잡기
        up_pos= PEN_HOLDERS['black']['up']
        safe_amovel(label="grip_black",target= posx(up_pos))
        down_pos= PEN_HOLDERS['black']['down']
        safe_amovel(label="grip_black",target= posx(down_pos))
        release()
        # 검은펜 집고 위로 올라가기 
        up_pos= PEN_HOLDERS['black']['up']
        safe_amovel(label="grip_black",target= posx(up_pos)) 


    print(f"\n>>> [{color}] 펜 반납 시작")

def change_pen(now_color,future_color):
    # 집어놓은 거 다시 방출 
    release_pen(now_color)
    # 새로운거 다시 잡기
    pick_up_pen(future_color)

def main(args: Optional[list[str]] = None) -> None:
    # 정사각형 경로 테스트 (10×10 ~ 50×50 mm)
    test_path: list[tuple[float, float, float]] = [
        (10.0, 10.0, Z_DRAW),
        (50.0, 10.0, Z_DRAW),
        (50.0, 50.0, Z_DRAW),
        (10.0, 50.0, Z_DRAW),
        (10.0, 10.0, Z_DRAW),
    ]

    print("=== ik_solver 테스트 ===")
    draw_path(test_path)


if __name__ == "__main__":
    main()