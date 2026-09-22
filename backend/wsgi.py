"""
wsgi.py — 生产部署 WSGI 入口

用法：
    gunicorn -w 4 -b 0.0.0.0:5000 wsgi:application
"""
from app import create_app

application = create_app("production")

if __name__ == "__main__":
    from config import FLASK_CONFIG
    application.run(
        host=FLASK_CONFIG["host"],
        port=FLASK_CONFIG["port"],
        debug=False,
    )