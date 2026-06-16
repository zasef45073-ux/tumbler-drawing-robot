from pathlib import Path

from werkzeug.utils import secure_filename

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from services.firebase_service import (
    create_customer_request,
    generate_request_id,
    get_customer_request_status,
)


customer_bp = Blueprint("customer", __name__)


def get_file_extension(filename, default_extension="png"):
    """
    업로드 파일명에서 확장자를 안전하게 추출한다.

    중요한 이유:
    - 한글 파일명은 secure_filename() 처리 후 파일명이 비거나
      점(.)이 사라질 수 있다.
    - 따라서 확장자는 secure_filename() 적용 전 원본 파일명에서 먼저 뽑는다.
    """

    clean_filename = str(filename or "").strip()

    if "." not in clean_filename:
        return default_extension

    extension = clean_filename.rsplit(".", 1)[1].lower().strip()

    if not extension:
        return default_extension

    return extension


def allowed_file(filename):
    """
    업로드 허용 확장자인지 확인
    """

    extension = get_file_extension(filename, default_extension="")

    if not extension:
        return False

    return extension in current_app.config["ALLOWED_IMAGE_EXTENSIONS"]


def make_upload_filename(request_id, original_filename):
    """
    저장할 파일명 생성

    접수번호와 파일명을 동일하게 맞춤.

    예:
    접수번호: TMB-20260430-202241-469F
    파일명: TMB-20260430-202241-469F.png
    """

    extension = get_file_extension(original_filename, default_extension="png")
    safe_request_id = secure_filename(request_id)

    return f"{safe_request_id}.{extension}"


def make_public_file_url(url_prefix, filename):
    """
    로봇 PC가 접근 가능한 전체 이미지 URL 생성

    예:
    PUBLIC_BASE_URL = http://192.168.0.25:5000
    url_prefix = /static/uploads/original
    filename = TMB-xxxx.png

    결과:
    http://192.168.0.25:5000/static/uploads/original/TMB-xxxx.png
    """

    public_base_url = current_app.config["PUBLIC_BASE_URL"].rstrip("/")
    clean_prefix = url_prefix.strip("/")

    return f"{public_base_url}/{clean_prefix}/{filename}"


def normalize_request_id_input(value):
    """
    고객이 입력한 접수번호 정리

    - 앞뒤 공백 제거
    - 소문자로 입력해도 조회되도록 대문자로 변환
    """

    return str(value or "").strip().upper()


@customer_bp.route("/")
def customer_home():
    """
    고객용 첫 페이지

    http://localhost:5000/
    """

    return render_template("customer_upload.html")


@customer_bp.route("/customer")
def customer_upload_page():
    """
    고객용 업로드 페이지

    http://localhost:5000/customer
    """

    return render_template("customer_upload.html")


@customer_bp.route("/customer/upload", methods=["POST"])
def customer_upload():
    """
    고객 이미지 업로드 처리

    처리 흐름:
    1. 고객명, 요청사항, 옵션, 이미지 파일 받기
    2. 접수번호 생성
    3. 접수번호와 같은 이름으로 이미지 저장
    4. Firebase /requests/{request_id}에 요청 정보 저장
    5. 접수 완료 페이지로 이동
    """

    customer_name = request.form.get("customerName", "").strip()
    request_text = request.form.get("requestText", "").strip()

    # 고객 화면에서 제작 옵션 입력란은 제거했지만,
    # 기존 Firebase/관리자 화면 호환을 위해 기본값은 유지한다.

    image_file = request.files.get("imageFile")

    if not customer_name:
        flash("고객명을 입력해주세요.")
        return redirect(url_for("customer.customer_upload_page"))

    if image_file is None or image_file.filename == "":
        flash("이미지 파일을 선택해주세요.")
        return redirect(url_for("customer.customer_upload_page"))

    if not allowed_file(image_file.filename):
        flash("png, jpg, jpeg, webp, gif 파일만 업로드할 수 있습니다.")
        return redirect(url_for("customer.customer_upload_page"))

    # 확장자 추출은 secure_filename 적용 전 원본 파일명 기준으로 처리한다.
    raw_original_filename = image_file.filename
    safe_original_filename = secure_filename(raw_original_filename)

    if not safe_original_filename:
        safe_original_filename = "uploaded_image"

    # 1. 접수번호 먼저 생성
    request_id = generate_request_id()

    # 2. 접수번호 기준으로 파일명 생성
    saved_filename = make_upload_filename(
        request_id=request_id,
        original_filename=raw_original_filename,
    )

    # 3. 업로드 폴더 생성
    upload_folder = Path(current_app.config["CUSTOMER_UPLOAD_FOLDER"])
    upload_folder.mkdir(parents=True, exist_ok=True)

    # 4. 파일 저장
    save_path = upload_folder / saved_filename
    image_file.save(save_path)

    # 5. 로봇 PC가 접근 가능한 전체 이미지 URL 생성
    image_url = make_public_file_url(
        current_app.config["CUSTOMER_UPLOAD_URL_PREFIX"],
        saved_filename,
    )

    # 6. Firebase requests/{request_id}에 저장
    result = create_customer_request(
        current_app.config,
        request_id=request_id,
        customer_name=customer_name,
        request_text=request_text,
        image_url=image_url,
        original_filename=safe_original_filename,
    )

    if result is None:
        flash("요청 저장 중 오류가 발생했습니다. 다시 시도해주세요.")
        return redirect(url_for("customer.customer_upload_page"))

    return redirect(url_for("customer.customer_complete", request_id=request_id))


@customer_bp.route("/customer/complete/<request_id>")
def customer_complete(request_id):
    """
    고객 접수 완료 페이지
    """

    return render_template(
        "customer_complete.html",
        request_id=request_id,
    )


@customer_bp.route("/status")
def customer_status_search():
    """
    고객 접수번호 조회 페이지

    사용 주소:
    http://localhost:5000/status
    """

    return render_template("customer_status_search.html")


@customer_bp.route("/status/check", methods=["POST"])
def customer_status_check():
    """
    고객 접수번호 조회 처리

    처리 흐름:
    1. 고객이 입력한 접수번호 받기
    2. 접수번호가 비어 있으면 /status로 되돌리기
    3. 접수번호가 있으면 /status/<request_id>로 이동
    """

    request_id = normalize_request_id_input(
        request.form.get("requestId", "")
    )

    if not request_id:
        flash("접수번호를 입력해주세요.")
        return redirect(url_for("customer.customer_status_search"))

    return redirect(
        url_for(
            "customer.customer_status_detail",
            request_id=request_id,
        )
    )


@customer_bp.route("/status/<request_id>")
def customer_status_detail(request_id):
    """
    고객 접수번호 상세 조회 페이지

    사용 주소:
    http://localhost:5000/status/TMB-xxxx
    """

    clean_request_id = normalize_request_id_input(request_id)

    if not clean_request_id:
        flash("접수번호를 입력해주세요.")
        return redirect(url_for("customer.customer_status_search"))

    request_status = get_customer_request_status(
        current_app.config,
        clean_request_id,
    )

    if request_status is None:
        flash("해당 접수번호의 제작 요청을 찾을 수 없습니다.")
        return redirect(url_for("customer.customer_status_search"))

    return render_template(
        "customer_status_detail.html",
        request_status=request_status,
    )