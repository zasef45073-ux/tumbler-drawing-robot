from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from services import process_flow as pf
from services.firebase_service import (
    approve_request,
    get_admin_request_detail,
    get_all_request_items,
    get_dashboard_data,
    reject_request,
    request_start_job,
    safe_update,
    now_text,
)


admin_bp = Blueprint("admin", __name__)
# ============================================================
# 전체 공정 자동 실행 설정
# ============================================================
#
# 기존 한 공정씩 실행하는 방식은 그대로 유지한다.
#
# 추가 기능:
# - 관리자 상세 페이지에서 "전체 공정 실행(풀 바르기 제외)" 버튼 클릭
# - 첫 공정으로 tumbler_place 명령 생성
# - listener가 autoRunAll 플래그를 보고 다음 공정을 자동으로 이어서 실행
# - glue는 평가/시연 편의를 위해 건너뛴다.
AUTO_RUN_SEQUENCE_FULL = [
    pf.COMMAND_TYPE_TUMBLER_PLACE,
    pf.COMMAND_TYPE_DRAWING,
    pf.COMMAND_TYPE_GLUE,
    pf.COMMAND_TYPE_PAPER_ATTACH,
    pf.COMMAND_TYPE_ROLLING_RETURN,
]


@admin_bp.route("/admin")
def admin_index():
    """
    /admin 접속 시 관리자 대시보드로 이동
    """

    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/admin/dashboard")
def dashboard():
    """
    관리자 첫 페이지

    사용 주소:
    http://localhost:5000/admin/dashboard
    """

    dashboard_data = get_dashboard_data(current_app.config)

    return render_template(
        "admin_dashboard.html",
        summary_cards=dashboard_data["summary_cards"],
        robot_status=dashboard_data["robot_status"],
        current_job=dashboard_data["current_job"],
        pending_requests=dashboard_data["pending_requests"],
        refresh_interval_ms=dashboard_data["refresh_interval_ms"],
    )


@admin_bp.route("/admin/requests")
def request_list():
    """
    관리자 전체 요청 목록 페이지

    사용 주소:
    http://localhost:5000/admin/requests
    """

    requests = get_all_request_items(current_app.config)

    return render_template(
        "admin_requests.html",
        requests=requests,
    )


@admin_bp.route("/admin/requests/<request_id>")
def request_detail(request_id):
    """
    관리자 요청 상세 페이지

    사용 주소:
    http://localhost:5000/admin/requests/TMB-xxxx
    """

    request_data = get_admin_request_detail(current_app.config, request_id)

    if request_data is None:
        flash("해당 요청을 찾을 수 없습니다.")
        return redirect(url_for("admin.request_list"))

    return render_template(
        "admin_request_detail.html",
        request_data=request_data,
    )


@admin_bp.route("/admin/requests/<request_id>/approve", methods=["POST"])
def request_approve(request_id):
    """
    요청 승인 처리

    기존:
    SUBMITTED 또는 REVIEWING → APPROVED

    변경:
    SUBMITTED 또는 REVIEWING → PAPER_READY

    이유:
    전체 공정이 PAPER → DRAWING → GLUE → ATTACH 순서로 확장되었기 때문.
    """

    request_data = get_admin_request_detail(current_app.config, request_id)

    if request_data is None:
        flash("해당 요청을 찾을 수 없습니다.")
        return redirect(url_for("admin.request_list"))

    if not request_data.get("canApprove"):
        flash("현재 상태에서는 제작 승인 처리를 할 수 없습니다.")
        return redirect(url_for("admin.request_detail", request_id=request_id))

    admin_memo = request.form.get("adminMemo", "").strip()

    success = approve_request(
        current_app.config,
        request_id=request_id,
        admin_memo=admin_memo,
    )

    if success:
        flash("요청을 승인하고 종이 세팅 대기 상태로 변경했습니다.")
    else:
        flash("요청 승인 처리 중 오류가 발생했습니다.")

    return redirect(url_for("admin.request_detail", request_id=request_id))


@admin_bp.route("/admin/requests/<request_id>/reject", methods=["POST"])
def request_reject(request_id):
    """
    요청 거절 처리

    가능한 상태에서만 제작 불가 처리.
    실제 공정 진행 중이거나 완료된 요청은 거절하지 않음.
    """

    request_data = get_admin_request_detail(current_app.config, request_id)

    if request_data is None:
        flash("해당 요청을 찾을 수 없습니다.")
        return redirect(url_for("admin.request_list"))

    if not request_data.get("canReject"):
        flash("현재 상태에서는 제작 불가 처리를 할 수 없습니다.")
        return redirect(url_for("admin.request_detail", request_id=request_id))

    admin_memo = request.form.get("adminMemo", "").strip()

    success = reject_request(
        current_app.config,
        request_id=request_id,
        admin_memo=admin_memo,
    )

    if success:
        flash("요청을 제작 불가 상태로 변경했습니다.")
    else:
        flash("요청 거절 처리 중 오류가 발생했습니다.")

    return redirect(url_for("admin.request_detail", request_id=request_id))


def resolve_command_type(request_data, route_command_type=None):
    """
    관리자 공정 시작 시 commandType 결정.

    우선순위:
    1. URL 경로의 command_type
       예: /start/drawing
    2. form의 commandType
       예: <input name="commandType" value="drawing">
    3. request_data.nextAction.commandType
       현재 상태에서 가능한 다음 공정 자동 선택
    """

    form_command_type = request.form.get("commandType", "").strip()

    next_action = request_data.get("nextAction") or {}
    next_action_command_type = next_action.get("commandType", "")

    selected_command_type = (
        route_command_type
        or form_command_type
        or next_action_command_type
    )

    return pf.normalize_command_type(selected_command_type)


@admin_bp.route(
    "/admin/requests/<request_id>/start",
    methods=["POST"],
    defaults={"command_type": None},
)
@admin_bp.route(
    "/admin/requests/<request_id>/start/<command_type>",
    methods=["POST"],
)
def request_start(request_id, command_type=None):
    """
    공정 시작 처리

    기존 호환:
    POST /admin/requests/<request_id>/start

    공정별 명령:
    POST /admin/requests/<request_id>/start/paper
    POST /admin/requests/<request_id>/start/drawing
    POST /admin/requests/<request_id>/start/glue
    POST /admin/requests/<request_id>/start/attach

    처리:
    1. 요청 상세 조회
    2. commandType 결정
    3. request_start_job(command_type=...) 호출
    4. Firebase commands/start에 commandType 포함 명령 저장
    """

    request_data = get_admin_request_detail(current_app.config, request_id)

    if request_data is None:
        flash("해당 요청을 찾을 수 없습니다.")
        return redirect(url_for("admin.request_list"))

    selected_command_type = resolve_command_type(
        request_data=request_data,
        route_command_type=command_type,
    )

    if not selected_command_type:
        flash("시작할 공정 타입을 확인할 수 없습니다.")
        return redirect(url_for("admin.request_detail", request_id=request_id))

    command_definition = pf.get_command_definition(selected_command_type)

    if not command_definition:
        flash("지원하지 않는 공정 타입입니다.")
        return redirect(url_for("admin.request_detail", request_id=request_id))

    success = request_start_job(
        current_app.config,
        job_id=request_id,
        requested_by="admin",
        command_type=selected_command_type,
    )

    command_label = command_definition.get(
        "label",
        pf.get_command_type_label(selected_command_type),
    )

    if success:
        flash(f"{command_label} 명령을 Firebase에 저장했습니다.")
        return redirect(url_for("admin.dashboard"))

    current_status_text = request_data.get("statusText", request_data.get("status", "-"))

    flash(
        f"현재 상태에서는 {command_label} 명령을 시작할 수 없습니다. "
        f"(현재 상태: {current_status_text})"
    )
    return redirect(url_for("admin.request_detail", request_id=request_id))

@admin_bp.route("/admin/requests/<request_id>/start-auto", methods=["POST"])
def request_start_auto(request_id):
    """
    전체 공정 자동 실행 시작.

    기존 한 공정씩 실행하는 방식은 그대로 둔다.

    이 route는 전체 자동 실행의 첫 명령만 생성한다.

    실행 흐름:
    1. tumbler_place 명령을 commands/start에 저장
    2. commands/start에 autoRunAll / skipGlue / autoRunSequence 플래그 추가
    3. listener가 tumbler_place 완료 후 다음 공정을 자동으로 생성
    4. drawing 완료 후 glue는 건너뛰고 paper_attach 자동 실행
    5. rolling_return 완료 후 COMPLETED

    자동 실행 순서:
    tumbler_place → drawing → paper_attach → rolling_return

    glue는 건너뜀.
    """

    request_data = get_admin_request_detail(current_app.config, request_id)

    if request_data is None:
        flash("해당 요청을 찾을 수 없습니다.")
        return redirect(url_for("admin.request_list"))

    first_command_type = pf.COMMAND_TYPE_TUMBLER_PLACE
    first_command_definition = pf.get_command_definition(first_command_type)

    if not first_command_definition:
        flash("전체 자동 실행 첫 공정 정보를 확인할 수 없습니다.")
        return redirect(url_for("admin.request_detail", request_id=request_id))

    success = request_start_job(
        current_app.config,
        job_id=request_id,
        requested_by="admin_auto_run",
        command_type=first_command_type,
    )

    if not success:
        current_status_text = request_data.get(
            "statusText",
            request_data.get("status", "-"),
        )

        flash(
            "현재 상태에서는 전체 공정 자동 실행을 시작할 수 없습니다. "
            f"(현재 상태: {current_status_text})"
        )
        return redirect(url_for("admin.request_detail", request_id=request_id))

    now = now_text()

    command_update = {
        "autoRunAll": True,
        "autoRunSequence": AUTO_RUN_SEQUENCE_FULL,
        "autoRunIndex": 0,
        "autoRunTotal": len(AUTO_RUN_SEQUENCE_FULL),
        "autoRunSource": "admin_request_detail",
        "autoRunStartedAt": now,
        "autoRunUpdatedAt": now,
        "autoRunNote": "전체 공정 자동 실행",
    }

    current_job_update = {
        "autoRunAll": True,
        "autoRunSequence": AUTO_RUN_SEQUENCE_FULL,
        "autoRunIndex": 0,
        "autoRunTotal": len(AUTO_RUN_SEQUENCE_FULL),
        "autoRunSource": "admin_request_detail",
        "autoRunStartedAt": now,
        "autoRunUpdatedAt": now,
        "autoRunNote": "전체 공정 자동 실행",
    }

    request_update = {
        "autoRunAll": True,
        "autoRunSequence": AUTO_RUN_SEQUENCE_FULL,
        "autoRunIndex": 0,
        "autoRunTotal": len(AUTO_RUN_SEQUENCE_FULL),
        "autoRunSource": "admin_request_detail",
        "autoRunStartedAt": now,
        "autoRunUpdatedAt": now,
        "autoRunNote": "전체 공정 자동 실행",
    }

    commands_path = current_app.config["COMMANDS_PATH"]
    current_job_path = current_app.config["CURRENT_JOB_PATH"]
    requests_path = current_app.config["REQUESTS_PATH"]

    safe_update(f"{commands_path}/start", command_update)
    safe_update(current_job_path, current_job_update)
    safe_update(f"{requests_path}/{request_id}", request_update)

    flash("전체 공정 자동 실행을 시작했습니다.")
    return redirect(url_for("admin.dashboard"))