# =========================
# commandType / status 정의
# 로봇 공정의 명령 타입, 진행 상태, 제어 액션 상수를 한곳에 모은 파일.
# 다른 모듈은 이 상수를 직접 임포트해서 사용한다(하드코딩 문자열 금지).
# =========================

# ── 명령 타입 (commandType) ──────────────────────────────────────────────────
# Firebase commands/start.commandType 필드에 들어가는 공정 식별자
COMMAND_TYPE_TUMBLER_PLACE = "tumbler_place"   # 1공정: 텀블러 집어 작업 위치에 놓기
COMMAND_TYPE_DRAWING = "drawing"               # 2공정: 펜으로 그림 그리기
COMMAND_TYPE_GLUE = "glue"                     # 3공정: 종이에 풀 바르기
COMMAND_TYPE_PAPER_ATTACH = "paper_attach"     # 4공정: 종이를 텀블러에 붙이기
COMMAND_TYPE_ROLLING_RETURN = "rolling_return" # 5공정: 종이 롤링 후 로봇 원위치

# ── 레거시 alias ─────────────────────────────────────────────────────────────
# 예전 Firebase 명령이나 기존 코드에서 paper / attach가 들어와도 처리되도록 매핑
COMMAND_TYPE_PAPER = COMMAND_TYPE_TUMBLER_PLACE
COMMAND_TYPE_ATTACH = COMMAND_TYPE_PAPER_ATTACH

# 레거시 commandType 문자열 → 현재 명칭으로 변환하는 매핑 테이블
# input 키: 예전 commandType 문자열 / output 값: 현재 COMMAND_TYPE_* 상수
LEGACY_COMMAND_TYPE_ALIAS_MAP: dict[str, str] = {
    "paper": COMMAND_TYPE_TUMBLER_PLACE,
    "attach": COMMAND_TYPE_PAPER_ATTACH,
}

# 현재 유효한 commandType 집합. normalize_command_type()에서 검증에 사용한다.
VALID_COMMAND_TYPES: set[str] = {
    COMMAND_TYPE_TUMBLER_PLACE,
    COMMAND_TYPE_DRAWING,
    COMMAND_TYPE_GLUE,
    COMMAND_TYPE_PAPER_ATTACH,
    COMMAND_TYPE_ROLLING_RETURN,
}

# drawing은 robot_job_runner.py로 보내고,
# 나머지 공정은 robot_process_adapter.py로 보낸다.
PROCESS_ADAPTER_COMMAND_TYPES: set[str] = {
    COMMAND_TYPE_TUMBLER_PLACE,
    COMMAND_TYPE_GLUE,
    COMMAND_TYPE_PAPER_ATTACH,
    COMMAND_TYPE_ROLLING_RETURN,
}

# ── 작업 진행 상태 (status) ──────────────────────────────────────────────────
# Firebase current_job / requests/{id}.status 필드에 들어가는 상태 문자열

STATUS_TUMBLER_PLACING = "TUMBLER_PLACING"       # 1공정 진행 중
STATUS_TUMBLER_PLACE_DONE = "TUMBLER_PLACE_DONE" # 1공정 완료

STATUS_DRAWING = "DRAWING"                       # 2공정 진행 중
STATUS_DRAWING_DONE = "DRAWING_DONE"             # 2공정 완료

STATUS_GLUING = "GLUING"                         # 3공정 진행 중
STATUS_GLUE_DONE = "GLUE_DONE"                   # 3공정 완료

STATUS_PAPER_ATTACHING = "PAPER_ATTACHING"       # 4공정 진행 중
STATUS_PAPER_ATTACH_DONE = "PAPER_ATTACH_DONE"   # 4공정 완료

STATUS_ROLLING_RETURNING = "ROLLING_RETURNING"   # 5공정 진행 중

STATUS_COMPLETED = "COMPLETED"                   # 전체 공정 최종 완료

STATUS_ERROR = "ERROR"                           # 오류 발생
STATUS_IDLE = "IDLE"                             # 대기 중 (작업 없음)

# ── 제어 요청 상태 (stop / pause / resume) ───────────────────────────────────
STATUS_STOP_REQUESTED = "STOP_REQUESTED"         # 중지 요청 접수
STATUS_STOPPED = "STOPPED"                       # 중지 완료

STATUS_PAUSE_REQUESTED = "PAUSE_REQUESTED"       # 일시정지 요청 접수
STATUS_PAUSED = "PAUSED"                         # 일시정지 완료
STATUS_RESUME_REQUESTED = "RESUME_REQUESTED"     # 재개 요청 접수

# ── 제어 액션 문자열 ─────────────────────────────────────────────────────────
# Firebase commands/control.action 필드에 들어가는 소문자 액션
CONTROL_ACTION_STOP = "stop"
CONTROL_ACTION_PAUSE = "pause"
CONTROL_ACTION_RESUME = "resume"

# ── 제어 명령 처리 상태 ──────────────────────────────────────────────────────
# Firebase commands/control.status 필드에 들어가는 상태
CONTROL_STATUS_REQUESTED = "REQUESTED"   # 제어 요청 접수 전
CONTROL_STATUS_ACCEPTED = "ACCEPTED"     # 제어 요청 확인(처리 시작)
CONTROL_STATUS_DONE = "DONE"             # 제어 처리 완료
CONTROL_STATUS_IGNORED = "IGNORED"       # 처리 불가 무시

# ── 종료 상태 집합 ───────────────────────────────────────────────────────────
# 작업이 이미 끝났는지 판단할 때 사용한다.
TERMINAL_STATUSES: set[str] = {
    STATUS_COMPLETED,
    STATUS_ERROR,
    STATUS_STOPPED,
    "REJECTED",
    "CANCELLED",
}


# ── 공정 정의 테이블 ─────────────────────────────────────────────────────────
# commandType별로 상태 문자열·진행률·라벨 등을 한 곳에서 관리한다.
# 키: COMMAND_TYPE_* 상수 / 값: 공정 메타데이터 dict
COMMAND_DEFINITIONS: dict[str, dict] = {
    COMMAND_TYPE_TUMBLER_PLACE: {
        "commandType": COMMAND_TYPE_TUMBLER_PLACE,
        "label": "텀블러 놓기",
        "runningStatus": STATUS_TUMBLER_PLACING,
        "runningStatusText": "텀블러 놓는 중",
        "doneStatus": STATUS_TUMBLER_PLACE_DONE,
        "doneStatusText": "텀블러 놓기 완료",
        "nextReadyStatus": "DRAWING_READY",
        "step": "1 / 5",
        "startProgress": 15,
        "runningProgress": 22,
        "doneProgress": 30,
        "description": "텀블러를 집어 작업 위치에 놓는 공정",
    },
    COMMAND_TYPE_DRAWING: {
        "commandType": COMMAND_TYPE_DRAWING,
        "label": "드로잉",
        "runningStatus": STATUS_DRAWING,
        "runningStatusText": "로봇 드로잉 중",
        "doneStatus": STATUS_DRAWING_DONE,
        "doneStatusText": "드로잉 완료",
        "nextReadyStatus": "GLUE_READY",
        "step": "2 / 5",
        "startProgress": 32,
        "runningProgress": 50,
        "doneProgress": 65,
        "description": "펜을 잡고 그림을 그린 뒤 펜을 놓는 공정",
    },
    COMMAND_TYPE_GLUE: {
        "commandType": COMMAND_TYPE_GLUE,
        "label": "풀 바르기",
        "runningStatus": STATUS_GLUING,
        "runningStatusText": "풀 바르는 중",
        "doneStatus": STATUS_GLUE_DONE,
        "doneStatusText": "풀 바르기 완료",
        "nextReadyStatus": "PAPER_ATTACH_READY",
        "step": "3 / 5",
        "startProgress": 68,
        "runningProgress": 74,
        "doneProgress": 80,
        "description": "그림이 그려진 종이에 풀을 바르는 공정",
    },
    COMMAND_TYPE_PAPER_ATTACH: {
        "commandType": COMMAND_TYPE_PAPER_ATTACH,
        "label": "종이 붙이기",
        "runningStatus": STATUS_PAPER_ATTACHING,
        "runningStatusText": "종이 붙이는 중",
        "doneStatus": STATUS_PAPER_ATTACH_DONE,
        "doneStatusText": "종이 붙이기 완료",
        "nextReadyStatus": "ROLLING_RETURN_READY",
        "step": "4 / 5",
        "startProgress": 82,
        "runningProgress": 88,
        "doneProgress": 92,
        "description": "그림이 그려진 종이를 텀블러에 붙이는 공정",
    },
    COMMAND_TYPE_ROLLING_RETURN: {
        "commandType": COMMAND_TYPE_ROLLING_RETURN,
        "label": "롤링 후 원위치",
        "runningStatus": STATUS_ROLLING_RETURNING,
        "runningStatusText": "롤링 후 원위치 진행 중",
        "doneStatus": STATUS_COMPLETED,
        "doneStatusText": "제작 완료",
        "nextReadyStatus": STATUS_COMPLETED,
        "step": "5 / 5",
        "startProgress": 94,
        "runningProgress": 97,
        "doneProgress": 100,
        "description": "부착된 종이를 롤링하고 로봇을 원위치로 복귀시키는 공정",
    },
}

# =========================
# 전체 자동 실행 설정
# =========================

# 관리자 상세 페이지의 "전체 공정 실행(풀 바르기 제외)" 버튼에서 사용하는 순서.
# 단일 공정 실행 방식은 그대로 두고, autoRunAll=True 명령에 대해서만
# listener가 다음 공정을 자동으로 commands/start에 생성한다.
AUTO_RUN_SEQUENCE_FULL: list[str] = [
    COMMAND_TYPE_TUMBLER_PLACE,
    COMMAND_TYPE_DRAWING,
    COMMAND_TYPE_GLUE,
    COMMAND_TYPE_PAPER_ATTACH,
    COMMAND_TYPE_ROLLING_RETURN,
]
