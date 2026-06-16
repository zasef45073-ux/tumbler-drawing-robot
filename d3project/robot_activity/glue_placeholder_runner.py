import argparse
import json
import time
from pathlib import Path


# ============================================================
# glue_placeholder_runner.py
#
# 역할:
# - 실제 풀 도포 로봇 동작 파일이 오기 전까지 사용하는 placeholder
# - robot_process_adapter.py가 외부 팀 파일을 subprocess로 호출할 수 있는지 확인
#
# 주의:
# - 실제 로봇을 움직이지 않음
# - DSR_ROBOT2 import 없음
# - rclpy import 없음
# - Firebase 직접 접근 없음
#
# 실행 예:
#   python3 glue_placeholder_runner.py
#
# command_json을 받아 실행:
#   python3 glue_placeholder_runner.py --command-json /tmp/xxx.json
# ============================================================


def load_command_json(command_json_path):
    """
    robot_process_adapter.py가 넘긴 command_json 파일을 읽는다.
    """

    if not command_json_path:
        return {}

    path = Path(command_json_path).expanduser().resolve()

    if not path.exists():
        raise FileNotFoundError(f"command_json 파일을 찾을 수 없습니다: {path}")

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def run_glue_placeholder(command_data):
    """
    풀 도포 placeholder 실행.

    실제 로봇 동작 대신 로그만 출력한다.
    """

    command = command_data.get("command", {}) if isinstance(command_data, dict) else {}

    job_id = command.get("jobId", "-")
    customer_name = command.get("customerName", "-")
    option = command.get("option", "-")
    request_text = command.get("requestText", "-")
    image_url = command.get("imageUrl", "-")
    converted_image_url = command.get("convertedImageUrl", "-")

    print("=" * 70)
    print("[GluePlaceholder] 풀 도포 placeholder 시작")
    print(f"[GluePlaceholder] jobId             : {job_id}")
    print(f"[GluePlaceholder] customerName      : {customer_name}")
    print(f"[GluePlaceholder] option            : {option}")
    print(f"[GluePlaceholder] requestText       : {request_text}")
    print(f"[GluePlaceholder] imageUrl          : {image_url}")
    print(f"[GluePlaceholder] convertedImageUrl : {converted_image_url}")
    print("[GluePlaceholder] 실제 로봇은 움직이지 않습니다.")
    print("=" * 70)

    steps = [
        "1. 풀 위치 확인",
        "2. 풀 집기 위치 접근",
        "3. 그리퍼 닫기 가정",
        "4. 종이 시작점으로 이동 가정",
        "5. 상단 라인 풀 도포 가정",
        "6. 우측 라인 풀 도포 가정",
        "7. 하단 라인 풀 도포 가정",
        "8. 좌측 라인 풀 도포 가정",
        "9. 풀 원위치 복귀 가정",
        "10. 그리퍼 열기 가정",
        "11. 안전 위치 복귀 가정",
    ]

    for step in steps:
        print(f"[GluePlaceholder] {step}")
        time.sleep(0.3)

    print("=" * 70)
    print("[GluePlaceholder] 풀 도포 placeholder 완료")
    print("=" * 70)

    return True


def parse_args():
    parser = argparse.ArgumentParser(
        description="Glue apply placeholder runner"
    )

    parser.add_argument(
        "--command-json",
        default="",
        help="robot_process_adapter.py가 생성한 command json 경로",
    )

    return parser.parse_args()


def main():
    args = parse_args()

    try:
        command_data = load_command_json(args.command_json)
        run_glue_placeholder(command_data)
        return 0

    except Exception as e:
        print(f"[GluePlaceholder][ERROR] {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())