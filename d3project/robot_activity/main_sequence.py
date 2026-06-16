#!/usr/bin/env python3

import os
import sys
import time
import subprocess
from pathlib import Path


# ============================================================
# 실행 순서:
# 1) 픽 텀블러
# 2) 펜 그립
# 3) 펜 릴리즈
# 4) 페이퍼 그립
# 5) 롤링
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

# 기본은 현재 실행 중인 python 사용
# 필요 시:
# ROBOT_PYTHON=/usr/bin/python3 python3 main_sequence.py
PYTHON = os.environ.get("ROBOT_PYTHON", sys.executable)


TASKS = [
    {
        "name": "픽 텀블러",
        "candidates": ["pick_tumbler.py"],
    },
    {
        "name": "펜 그립",
        "candidates": ["pen_grip.py"],
    },
    {
        "name": "펜 릴리즈",
        "candidates": ["pen_release.py"],
    },
    {
        "name": "페이퍼 그립",
        "candidates": ["paper_grip.py"],
    },
    {
        "name": "롤링",
        "candidates": ["rolling.py"],
    },
]


def find_script(candidates):
    """
    후보 파일명 중 실제 존재하는 파일을 찾는다.
    """
    for filename in candidates:
        path = BASE_DIR / filename
        if path.exists():
            return path

    return None


def run_script(task_name, script_path):
    """
    각 작업 파일을 별도 Python 프로세스로 실행한다.

    이유:
    각 파일이 내부에서 rclpy.init(), node 생성, rclpy.shutdown()을 직접 수행하므로
    import 방식으로 한 프로세스 안에서 이어붙이면 ROS2 context 충돌이 날 수 있다.
    따라서 subprocess 방식이 가장 안전하다.
    """
    print("\n" + "=" * 70)
    print(f"[START] {task_name}")
    print(f"[FILE]  {script_path.name}")
    print("=" * 70)

    result = subprocess.run(
        [PYTHON, str(script_path)],
        cwd=str(BASE_DIR),
    )

    if result.returncode != 0:
        print("\n" + "!" * 70)
        print(f"[ERROR] {task_name} 실패")
        print(f"[FILE]  {script_path.name}")
        print(f"[CODE]  return code = {result.returncode}")
        print("안전을 위해 이후 시퀀스는 중단합니다.")
        print("!" * 70)
        return False

    print("\n" + "-" * 70)
    print(f"[DONE] {task_name} 완료")
    print("-" * 70)

    return True


def main():
    print("\n" + "=" * 70)
    print(" Robot Main Sequence Start")
    print(" 순서: 픽 텀블러 -> 펜 그립 -> 펜 릴리즈 -> 페이퍼 그립 -> 롤링")
    print(f" BASE_DIR: {BASE_DIR}")
    print(f" PYTHON:   {PYTHON}")
    print("=" * 70)

    for task in TASKS:
        task_name = task["name"]
        script_path = find_script(task["candidates"])

        if script_path is None:
            print("\n" + "!" * 70)
            print(f"[ERROR] {task_name} 파일을 찾을 수 없습니다.")
            print(f"찾은 위치: {BASE_DIR}")
            print(f"후보 파일명: {task['candidates']}")
            print("파일명이 맞는지 확인하세요.")
            print("!" * 70)
            return

        ok = run_script(task_name, script_path)

        if not ok:
            return

        # 각 파일 종료 후 ROS/로봇 상태 안정화 대기
        time.sleep(1.0)

    print("\n" + "=" * 70)
    print("[ALL DONE] 전체 시퀀스 완료")
    print("=" * 70)


if __name__ == "__main__":
    main()