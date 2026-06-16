#!/usr/bin/env python3

import json
import logging
import time
from pathlib import Path

import DR_init
_logger = logging.getLogger(__name__)

# ============================================================
# 공통 로봇 상수
# ============================================================

ROBOT_ID = "dsr01"
ROBOT_MODEL = "m0609"
ROBOT_TOOL = "Tool Weight"
ROBOT_TCP = "GripperDA_v1"

DR_init.__dsr__id = ROBOT_ID
DR_init.__dsr__model = ROBOT_MODEL

# ============================================================
# DSR import 오류 출력
# ============================================================

def print_dsr_import_error(e):
    _logger.error(f"[ERROR] DSR import 실패: {e}")
    _logger.info("아래 source 확인:")
    _logger.info("source /opt/ros/humble/setup.bash")
    _logger.info("source ~/cobot_ws/install/setup.bash")


# ============================================================
# 로봇 초기화
# ============================================================

def initialize_robot():
    """Tool/TCP 설정 및 자율 모드 전환."""

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

    _logger.info("[INIT] robot setting")

    set_robot_mode(ROBOT_MODE_MANUAL)
    set_tool(ROBOT_TOOL)
    set_tcp(ROBOT_TCP)
    set_robot_mode(ROBOT_MODE_AUTONOMOUS)
    time.sleep(2.0)

    _logger.info("#" * 50)
    _logger.info("Initializing robot with the following settings:")
    _logger.info(f"ROBOT_ID    : {ROBOT_ID}")
    _logger.info(f"ROBOT_MODEL : {ROBOT_MODEL}")
    _logger.info(f"ROBOT_TCP   : {get_tcp()}")
    _logger.info(f"ROBOT_TOOL  : {get_tool()}")
    _logger.info(f"ROBOT_MODE (0:Manual, 1:Auto): {get_robot_mode()}")
    _logger.info("#" * 50)


# ============================================================
# 모션 대기 / 이동 래퍼
# ============================================================

def wait_motion_done(label="motion"):
    """amove 명령 이후 motion이 완료될 때까지 대기한다."""

    from DSR_ROBOT2 import check_motion, wait

    _logger.info(f"[WAIT] {label} 완료 대기 시작")
    wait(0.1)

    while True:
        if check_motion() == 0:
            break
        wait(0.05)

    _logger.info(f"[WAIT] {label} 완료 확인")


def safe_amovej(label, target, vel, acc):
    """joint 비동기 이동 + 완료 대기."""

    from DSR_ROBOT2 import amovej

    _logger.info(f"[AMOVEJ] {label} start")
    amovej(target, vel=vel, acc=acc)
    wait_motion_done(label)
    _logger.info(f"[AMOVEJ] {label} done")


def safe_amovel(label, target, vel, acc, ref=None):
    """task linear 비동기 이동 + 완료 대기."""

    from DSR_ROBOT2 import amovel, DR_BASE

    _logger.info(f"[AMOVEL] {label} start")
    amovel(target, vel=vel, acc=acc, ref=DR_BASE if ref is None else ref)
    wait_motion_done(label)
    _logger.info(f"[AMOVEL] {label} done")


def safe_amovec(label, via, target, vel, acc):
    """task circular 비동기 이동 + 완료 대기."""

    from DSR_ROBOT2 import amovec

    _logger.info(f"[AMOVEC] {label} start")
    amovec(via, target, vel=vel, acc=acc)
    wait_motion_done(label)
    _logger.info(f"[AMOVEC] {label} done")


# ============================================================
# 그리퍼 제어
# ============================================================

def gripper_close():
    from DSR_ROBOT2 import set_digital_output
    _logger.info("[GRIPPER] close")
    set_digital_output(1)
    set_digital_output(-2)


def gripper_open():
    from DSR_ROBOT2 import set_digital_output
    _logger.info("[GRIPPER] open")
    set_digital_output(-1)
    set_digital_output(2)


# ============================================================
# Command JSON 로더 (placeholder runner 공용)
# ============================================================

def load_command_json(command_json_path):
    """robot_process_adapter.py가 넘긴 command_json 파일을 읽는다."""

    if not command_json_path:
        return {}

    path = Path(command_json_path).expanduser().resolve()

    if not path.exists():
        raise FileNotFoundError(f"command_json 파일을 찾을 수 없습니다: {path}")

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
