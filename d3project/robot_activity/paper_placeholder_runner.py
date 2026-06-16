import argparse
import logging
import time
_logger = logging.getLogger(__name__)

# ============================================================
# default_robot_setting.py 에서 command json 로드 함수 import
#
# 역할:
# - robot_process_adapter.py 가 생성한 command json 파일 읽기
# ============================================================
from default_robot import load_command_json

# ============================================================
# Paper Placeholder 실행 함수
#
# 역할:
# - 실제 종이 세팅 로봇 동작 대신
#   placeholder 로그 출력
#
# 사용 목적:
# - API 연동 테스트
# - 공정 흐름 테스트
# - UI / Backend 연동 검증
#
# 주의:
# - 실제 로봇은 움직이지 않음
# - 단순 로그 + sleep 기반 시뮬레이션
# ============================================================
def run_paper_placeholder(command_data):

    # --------------------------------------------------------
    # command 데이터 추출
    #
    # 예상 구조:
    # {
    #   "command": {
    #       ...
    #   }
    # }
    # --------------------------------------------------------
    command = (
        command_data.get("command", {})
        if isinstance(command_data, dict)
        else {}
    )

    # --------------------------------------------------------
    # command 내부 값 추출
    #
    # 값이 없으면 "-" 사용
    # --------------------------------------------------------
    job_id        = command.get("jobId", "-")
    customer_name = command.get("customerName", "-")
    option        = command.get("option", "-")
    request_text  = command.get("requestText", "-")

    # --------------------------------------------------------
    # 시작 로그 출력
    # --------------------------------------------------------
    _logger.info("=" * 70)

    _logger.info("[PaperPlaceholder] 종이 세팅 placeholder 시작")

    _logger.info(f"[PaperPlaceholder] jobId        : {job_id}")
    _logger.info(f"[PaperPlaceholder] customerName : {customer_name}")
    _logger.info(f"[PaperPlaceholder] option       : {option}")
    _logger.info(f"[PaperPlaceholder] requestText  : {request_text}")

    _logger.info("[PaperPlaceholder] 실제 로봇은 움직이지 않습니다.")

    _logger.info("=" * 70)

    # --------------------------------------------------------
    # Placeholder 공정 단계 목록
    #
    # 실제 로봇 동작 대신
    # 단계별 로그 출력
    # --------------------------------------------------------
    steps = [

        # 종이 위치 확인
        "1. 종이 트레이 위치 확인",

        # 종이 pick 위치 접근
        "2. 종이 집기 위치 접근",

        # 그리퍼 닫기
        "3. 그리퍼 닫기 가정",

        # 작업대 이동
        "4. 작업대 위치로 이동 가정",

        # 종이 내려놓기
        "5. 종이 내려놓기 가정",

        # 그리퍼 열기
        "6. 그리퍼 열기 가정",

        # 안전 위치 복귀
        "7. 안전 위치 복귀 가정",
    ]

    # --------------------------------------------------------
    # 단계별 실행 로그
    #
    # sleep을 사용해 실제 동작 느낌 시뮬레이션
    # --------------------------------------------------------
    for step in steps:

        _logger.info(f"[PaperPlaceholder] {step}")

        # 0.3초 대기
        time.sleep(0.3)

    # --------------------------------------------------------
    # 종료 로그
    # --------------------------------------------------------
    _logger.info("=" * 70)

    _logger.info("[PaperPlaceholder] 종이 세팅 placeholder 완료")

    _logger.info("=" * 70)

    return True


# ============================================================
# CLI Argument Parsing
#
# 사용 예:
#
# python paper_placeholder.py \
#     --command-json /tmp/command.json
# ============================================================
def parse_args():

    parser = argparse.ArgumentParser(
        description="Paper setup placeholder runner"
    )

    # --------------------------------------------------------
    # command json 경로
    #
    # robot_process_adapter.py 에서 생성한 파일
    # --------------------------------------------------------
    parser.add_argument(
        "--command-json",

        default="",

        help=(
            "robot_process_adapter.py가 생성한 "
            "command json 경로"
        ),
    )

    return parser.parse_args()


# ============================================================
# Main
# ============================================================
def main():

    # CLI argument 읽기
    args = parse_args()

    try:

        # ----------------------------------------------------
        # command json 로드
        # ----------------------------------------------------
        command_data = load_command_json(
            args.command_json
        )

        # ----------------------------------------------------
        # Placeholder 실행
        # ----------------------------------------------------
        run_paper_placeholder(command_data)

        # 정상 종료
        return 0

    except Exception as e:

        # ----------------------------------------------------
        # 예외 처리
        # ----------------------------------------------------
        _logger.error(f"[PaperPlaceholder][ERROR] {e}")

        return 1


# ============================================================
# 프로그램 시작점
# ============================================================
if __name__ == "__main__":

    # main() 종료 코드를 시스템 종료 코드로 반환
    raise SystemExit(main())