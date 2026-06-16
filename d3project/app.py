from flask import Flask

from config import Config
from routes.customer_routes import customer_bp
from routes.admin_routes import admin_bp
from routes.api_routes import api_bp
from services.firebase_service import init_firebase


def create_app():
    """
    Flask 앱 생성 함수

    역할:
    1. Flask 앱 생성
    2. config.py 설정값 불러오기
    3. Firebase 초기화
    4. 고객용 페이지 라우트 등록
    5. 관리자 페이지 라우트 등록
    6. API 라우트 등록
    """

    app = Flask(__name__)

    # config.py 안의 Config 클래스 적용
    app.config.from_object(Config)

    # Firebase Admin SDK 초기화
    init_firebase(app)

    # 고객용 페이지 라우트 등록
    # / 또는 /customer 로 접속하면 고객 업로드 페이지가 열림
    app.register_blueprint(customer_bp)

    # 관리자 화면 라우트 등록
    # /admin/dashboard 로 접속하면 관리자 대시보드가 열림
    app.register_blueprint(admin_bp)

    # API 라우트 등록
    # /api/dashboard, /api/robot-status 등
    app.register_blueprint(api_bp)

    @app.route("/health")
    def health_check():
        """
        서버 정상 실행 확인용 주소

        http://localhost:5000/health
        """
        return "OK"

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )