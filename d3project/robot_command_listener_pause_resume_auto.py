import argparse
import os
import sys
import threading
import time

# ============================================================
# 기본 실행 환경 설정
# 다른 모듈보다 먼저 실행되어야 하므로 import 전에 setdefault 호출
# ============================================================

os.environ.setdefault("ROBOT_JOB_MODE", "real")
os.environ.setdefault("COBOT1_ADAPTER_MODE", "preview_then_robot")
os.environ.setdefault("COBOT1_PREVIEW_PYTHON", "/usr/bin/python3")
os.environ.setdefault("COBOT1_ROBOT_PYTHON", "/usr/bin/python3")

# setting/ 모듈끼리 서로를 참조할 수 있도록 경로 추가
# (예: control_command_func → common_util_func 등 내부 의존성)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "setting"))

from config import Config
from robot_job_runner import run_robot_job          # drawing 공정 실행기
from robot_activity.robot_process_adapter import run_process_job   # 나머지 공정(tumbler/glue/attach/rolling) 실행기

# =========================
# setting 모듈 import
# 상수·유틸·Firebase·제어 로직은 setting/ 패키지로 분리되어 있다.
# 이 파일에서 직접 정의하지 않고 import만 한다.
# =========================
from setting.command_type_and_status_const import (
    COMMAND_TYPE_DRAWING,       # drawing 공정 식별자
    CONTROL_ACTION_STOP,        # stop 액션 문자열
    CONTROL_ACTION_PAUSE,       # pause 액션 문자열
    PROCESS_ADAPTER_COMMAND_TYPES,  # robot_process_adapter로 처리하는 공정 집합
)

from setting.listener_path_const import (
    POLL_INTERVAL_SEC,          # commands/start 폴링 주기 (초)
    CONTROL_POLL_INTERVAL_SEC,  # commands/control 폴링 주기 (초)
    DEFAULT_JOB_MODE,           # 기본 실행 모드 ("real")
)

from setting.common_util_func import (
    validate_job_mode,      # "demo" / "real" 이외의 값이면 ValueError
    get_command_type,       # command dict에서 정규화된 commandType 추출
    get_command_definition, # commandType → COMMAND_DEFINITIONS 조회
)

from setting.active_job import (
    _SHUTDOWN_EVENT,                  # control watcher 종료 신호 (Event)
    set_active_command,               # 현재 실행 중인 command를 전역에 등록
    clear_active_command,             # 실행 완료 / 오류 후 전역 command 해제
    get_remembered_control_action,    # stop/pause 기록 조회 (중복 처리 방지)
    clear_remembered_control_action,  # 새 작업 시작 전 이전 기록 초기화
)

from setting.reset_firebase_func import (
    init_firebase,      # Firebase Admin SDK 초기화 (중복 호출 방어 포함)
    get_start_command,  # commands/start 경로에서 현재 명령 읽기
)

from setting.control_command_func import (
    control_watcher_loop,         # stop/pause/resume 폴링 루프 (데몬 스레드로 실행)
    get_active_control_for_job,   # 특정 job의 유효한 control 명령 조회
    handle_stop_or_pause_control, # stop/pause 명령 처리 (subprocess 종료 or pause)
)

from setting.update_firebase_func import (
    accept_command,              # 명령 접수 → Firebase 4개 경로 실행 중 상태로 갱신
    update_progress_from_runner, # 러너 콜백으로 받은 진행률을 Firebase에 반영
    mark_process_completed,      # 공정 완료 → Firebase 갱신 + 자동 실행 다음 공정 생성
    mark_job_error,              # 오류 발생 → Firebase ERROR 상태로 갱신
)


# =========================
# 명령 처리 메인 로직
# Firebase commands/start에서 읽은 단일 명령을 처음부터 끝까지 처리한다.
# drawing → robot_job_runner, 나머지 → robot_process_adapter로 분기한다.
# =========================
def process_command(command, mode):
    # dict가 아니면 Firebase 오류 응답이거나 null — 조용히 무시
    if not isinstance(command, dict):
        return

    job_id = command.get("jobId")
    command_type = get_command_type(command)
    command_definition = get_command_definition(command_type)

    # jobId 없으면 어떤 요청인지 특정 불가 — 에러 기록 후 종료
    if not job_id:
        mark_job_error(None, "commands/start에 jobId가 없습니다.", command)
        return

    # 지원하지 않는 commandType이면 에러로 처리
    if not command_definition:
        mark_job_error(
            job_id,
            f"지원하지 않는 commandType입니다: {command.get('commandType')}",
            command,
        )
        return

    print("=" * 70)
    print("[Listener] 작업 처리 시작")
    print(f"[Listener] job_id      : {job_id}")
    print(f"[Listener] commandType : {command_type}")
    print(f"[Listener] commandLabel: {command_definition['label']}")
    print(f"[Listener] 실행 모드    : {mode}")
    print(f"[Listener] adapter 모드 : {os.getenv('COBOT1_ADAPTER_MODE', '-')}")
    print("=" * 70)

    # 이전 작업의 stop 기록이 남아 있으면 초기화하고 현재 작업 등록
    clear_remembered_control_action(job_id)
    set_active_command(command, mode)

    try:
        # ── 실행 전 제어 체크 ─────────────────────────────────────────────
        # accept_command 이전에 stop/pause가 들어오면 runner를 시작하지 않는다.
        pre_control = get_active_control_for_job(
            job_id,
            allowed_actions={CONTROL_ACTION_STOP, CONTROL_ACTION_PAUSE},
        )

        if pre_control:
            handle_stop_or_pause_control(pre_control)
            return

        # Firebase에 실행 중 상태 기록 (UI 진행률 표시 시작)
        accept_command(command, mode)

        # ── 명령 접수 직후 제어 체크 ──────────────────────────────────────
        # accept_command와 runner 시작 사이에 stop/pause가 들어올 수 있다.
        mid_control = get_active_control_for_job(
            job_id,
            allowed_actions={CONTROL_ACTION_STOP, CONTROL_ACTION_PAUSE},
        )

        if mid_control:
            handle_stop_or_pause_control(mid_control)
            return

        # ── 공정 실행 분기 ────────────────────────────────────────────────
        if command_type == COMMAND_TYPE_DRAWING:
            # drawing은 robot_job_runner가 직접 경로·진행률을 관리
            result = run_robot_job(
                command=command,
                mode=mode,
                progress_callback=update_progress_from_runner,
            )

        elif command_type in PROCESS_ADAPTER_COMMAND_TYPES:
            # tumbler_place / glue / paper_attach / rolling_return
            result = run_process_job(
                command_type=command_type,
                command=command,
                mode=mode,
                progress_callback=update_progress_from_runner,
            )

        else:
            # 알 수 없는 commandType — 실행하지 않고 에러 반환
            result = {
                "success": False,
                "errorMessage": f"처리할 수 없는 commandType입니다: {command_type}",
            }

        # ── runner 완료 후 제어 체크 ──────────────────────────────────────
        # runner 실행 중 stop이 처리됐으면 완료 기록을 건너뛴다.
        remembered = get_remembered_control_action(job_id)

        if remembered.get("action") == CONTROL_ACTION_STOP:
            print(
                f"[Listener] control 처리로 인해 runner 결과 무시: "
                f"job_id={job_id}, action={remembered.get('action')}"
            )
            return

        # runner 종료 직후에도 stop/pause가 들어왔을 수 있다.
        post_control = get_active_control_for_job(
            job_id,
            allowed_actions={CONTROL_ACTION_STOP, CONTROL_ACTION_PAUSE},
        )

        if post_control:
            handle_stop_or_pause_control(post_control)
            return

        # ── 결과 처리 ─────────────────────────────────────────────────────
        if result.get("success"):
            # 완료 처리 + autoRunAll이면 다음 공정 자동 생성
            mark_process_completed(
                job_id=job_id,
                command=command,
                result=result,
                mode=mode,
            )
            return

        # runner가 실패를 반환한 경우
        error_message = result.get("errorMessage") or result.get("message") or "알 수 없는 작업 오류"
        mark_job_error(job_id, error_message, command)

    except Exception as e:
        mark_job_error(job_id, str(e), command)

    finally:
        # 성공 / 실패 / 예외 어느 경우에도 반드시 active command 해제
        clear_active_command()


def should_process_command(command):
    # Firebase에서 읽은 값이 처리 가능한 상태인지 확인한다.
    # status가 REQUESTED이고 jobId가 있어야 실행 대상이다.
    if not isinstance(command, dict):
        return False

    if command.get("status") != "REQUESTED":
        return False

    if not command.get("jobId"):
        return False

    return True


def make_command_signature(command):
    # jobId·commandType·requestedAt 조합으로 중복 실행을 방지하는 서명을 만든다.
    # 같은 서명의 명령은 이미 처리 중인 것으로 판단해 건너뛴다.
    job_id = command.get("jobId", "")
    command_type = (
        command.get("commandType")
        or command.get("command_type")
        or COMMAND_TYPE_DRAWING
    )
    requested_at = command.get("requestedAt", "")

    return f"{job_id}|{command_type}|{requested_at}"


def run_listener(mode):
    # mode 검증 → Firebase 초기화 → control watcher 스레드 시작 → 메인 폴링 루프
    mode = validate_job_mode(mode)

    init_firebase()

    print("[Listener] Firebase 작업 명령 대기 시작")
    print(f"[Listener] commands path: {Config.COMMANDS_PATH}/start")
    print(f"[Listener] control path: {Config.COMMANDS_PATH}/control")
    print(f"[Listener] current_job path: {Config.CURRENT_JOB_PATH}")
    print(f"[Listener] requests path: {Config.REQUESTS_PATH}")
    print(f"[Listener] robot_status path: {Config.ROBOT_STATUS_PATH}")
    print(f"[Listener] 실행 모드: {mode}")
    print(f"[Listener] adapter 모드: {os.getenv('COBOT1_ADAPTER_MODE', '-')}")
    print(f"[Listener] preview python: {os.getenv('COBOT1_PREVIEW_PYTHON', '-')}")
    print(f"[Listener] robot python: {os.getenv('COBOT1_ROBOT_PYTHON', '-')}")
    print(f"[Listener] 확인 주기: {POLL_INTERVAL_SEC}초")
    print(f"[Listener] control 확인 주기: {CONTROL_POLL_INTERVAL_SEC}초")

    if mode == "real" and os.getenv("COBOT1_ADAPTER_MODE") == "preview_then_robot":
        print("[Listener][주의] drawing 공정 시작 시 preview 후 실제 로봇이 움직입니다.")

    if mode == "demo":
        print("[Listener] demo 모드입니다. 실제 로봇은 움직이지 않습니다.")
        print("[Listener] drawing은 robot_job_runner demo로 처리됩니다.")
        print("[Listener] paper / glue / attach는 robot_process_adapter demo로 처리됩니다.")

    if mode == "real":
        print("[Listener] real 모드입니다.")
        print("[Listener] drawing은 기존 preview_then_robot 구조를 사용합니다.")
        print("[Listener] tumbler_place / glue / paper_attach / rolling_return은")
        print("[Listener] robot_process_adapter.py의 환경변수 runner command가 있어야 실행됩니다.")

    print("[Listener] 작업 제어:")
    print("[Listener] commands/control action=stop/pause/resume 요청을 감시합니다.")
    print("[Listener] stop  : 현재 subprocess 종료 후 STOPPED")
    print("[Listener] pause : move_pause service 호출 후 PAUSED, subprocess 유지")
    print("[Listener] resume: move_resume service 호출 후 기존 subprocess 계속 진행")
    print("[Listener] 전체 자동 실행:")
    print("[Listener] autoRunAll=True 명령은 완료 후 다음 공정을 자동 생성합니다.")
    print("[Listener] 자동 순서: tumbler_place → drawing → paper_attach → rolling_return")
    print("[Listener] glue 공정은 자동 실행에서 건너뜁니다.")
    print("[Listener] 종료: Ctrl + C")

    # control watcher 시작 전에 종료 이벤트를 초기화
    _SHUTDOWN_EVENT.clear()

    # control watcher는 데몬 스레드로 실행 — 메인 루프가 종료되면 자동으로 종료됨
    control_thread = threading.Thread(
        target=control_watcher_loop,
        name="robot-control-watcher",
        daemon=True,
    )
    control_thread.start()

    last_processed_signature = None

    while True:
        try:
            command = get_start_command()

            if should_process_command(command):
                signature = make_command_signature(command)

                # 같은 명령을 반복 처리하지 않도록 서명으로 중복 체크
                if signature == last_processed_signature:
                    print(f"[Listener][Skip] 이미 처리 중인 명령입니다: {signature}")
                    time.sleep(POLL_INTERVAL_SEC)
                    continue

                last_processed_signature = signature
                process_command(command, mode)  # 동기 실행 — 완료될 때까지 블로킹

            time.sleep(POLL_INTERVAL_SEC)

        except KeyboardInterrupt:
            print("\n[Listener] 사용자 종료")
            _SHUTDOWN_EVENT.set()  # control watcher 루프 종료 신호
            break

        except Exception as e:
            print(f"[Listener][Loop Error] {e}")
            time.sleep(POLL_INTERVAL_SEC)


# =========================
# CLI 실행부
# =========================

def parse_args():
    parser = argparse.ArgumentParser(
        description="Firebase commands/start를 감시하는 Doosan M0609 로봇 작업 listener"
    )

    parser.add_argument(
        "--mode",
        choices=["demo", "real"],
        default=DEFAULT_JOB_MODE,
        help=(
            "demo: 가짜 작업 테스트, real: 실제 로봇 알고리즘 또는 외부 공정 runner 호출. "
            "기본값은 real입니다."
        ),
    )

    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_listener(args.mode)
