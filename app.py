"""应用启动入口。

负责创建 Flask 应用并按 settings.json 中的服务配置启动 Web 服务。
"""

import os

from app import create_app


os.environ.setdefault("SMART_VIDEO_DISABLE_RELOADER", "1")
app = create_app()


if __name__ == "__main__":
    app.run(
        host=app.config["APP_SETTINGS"]["server"]["host"],
        port=app.config["APP_SETTINGS"]["server"]["port"],
        debug=app.config["APP_SETTINGS"]["server"]["debug"],
        use_reloader=False,
    )
