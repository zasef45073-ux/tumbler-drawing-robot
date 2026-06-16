# =========================
# Firebase 초기화 / 접근 함수
# firebase_admin SDK를 초기화하고 Realtime Database 경로별 읽기/쓰기 함수를 제공한다.
# =========================
import firebase_admin
from firebase_admin import credentials, db
from config import Config
from typing import cast

def init_firebase() -> None:
    # Firebase Admin SDK를 초기화한다. 이미 초기화된 경우 건너뛴다.
    # input:  없음 (Config.FIREBASE_SERVICE_ACCOUNT_KEY, Config.FIREBASE_DATABASE_URL 참조)
    # output: None — firebase_admin 앱이 등록됨
    if firebase_admin._apps:
        print("[Firebase] 이미 초기화되어 있습니다.")
        return

    cred = credentials.Certificate(Config.FIREBASE_SERVICE_ACCOUNT_KEY)

    firebase_admin.initialize_app(
        cred,
        {
            "databaseURL": Config.FIREBASE_DATABASE_URL,
        },
    )

    print("[Firebase] 초기화 완료")


def get_start_command() -> dict | None:
    # commands/start 경로에서 현재 명령을 읽어 반환한다.
    # input:  없음
    # output: {"jobId": "abc", "commandType": "drawing", "status": "REQUESTED", ...} / None
    return cast(dict | None, db.reference(f"{Config.COMMANDS_PATH}/start").get())


def get_control_command() -> dict | None:
    # commands/control 경로에서 현재 제어 명령을 읽어 반환한다.
    # input:  없음
    # output: {"jobId": "abc", "action": "stop", "status": "REQUESTED", ...} / None
    return cast(dict | None, db.reference(f"{Config.COMMANDS_PATH}/control").get())


def get_current_job_raw() -> dict:
    # current_job 경로의 스냅샷을 읽어 반환한다.
    # dict가 아니면(null 등) 빈 dict를 반환해 호출자가 .get()을 안전하게 쓸 수 있게 한다.
    # input:  없음
    # output: {"jobId": "abc", "status": "DRAWING", ...} / {}
    current_job = db.reference(Config.CURRENT_JOB_PATH).get()

    if not isinstance(current_job, dict):
        return {}

    return current_job


def update_command(data: dict) -> None:
    # commands/start 경로를 부분 갱신한다.
    # input:  data={"status": "ACCEPTED", "acceptedAt": "2026-05-08 12:00:00", ...}
    # output: None
    db.reference(f"{Config.COMMANDS_PATH}/start").update(data)


def set_start_command(data: dict) -> None:
    # commands/start 경로 전체를 덮어쓴다(자동 실행 다음 공정 생성 시 사용).
    # input:  data={"jobId": "abc", "commandType": "paper_attach", "status": "REQUESTED", ...}
    # output: None
    db.reference(f"{Config.COMMANDS_PATH}/start").set(data)


def update_control_command(data: dict) -> None:
    # commands/control 경로를 부분 갱신한다.
    # input:  data={"status": "ACCEPTED", "acceptedAt": "2026-05-08 12:00:00"}
    # output: None
    db.reference(f"{Config.COMMANDS_PATH}/control").update(data)


def update_current_job(data: dict) -> None:
    # current_job 경로를 부분 갱신한다.
    # input:  data={"status": "DRAWING", "progress": 50, "updatedAt": "..."}
    # output: None
    db.reference(Config.CURRENT_JOB_PATH).update(data)


def update_request(job_id: str, data: dict) -> None:
    # requests/{job_id} 경로를 부분 갱신한다. job_id가 없으면 아무 것도 하지 않는다.
    # input:  job_id="abc", data={"status": "DRAWING", "progress": 50, "updatedAt": "..."}
    # output: None
    if not job_id:
        return

    db.reference(f"{Config.REQUESTS_PATH}/{job_id}").update(data)


def update_robot_status(data: dict) -> None:
    # robot_status 경로를 부분 갱신한다.
    # input:  data={"state": "DRAWING", "last_update_timestamp": 1746691200.0, ...}
    # output: None
    db.reference(Config.ROBOT_STATUS_PATH).update(data)
