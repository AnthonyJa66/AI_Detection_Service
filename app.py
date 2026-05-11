"""应用启动入口。

负责创建 Flask 应用并按 settings.json 中的服务配置启动 Web 服务。
"""

from app import create_app


app = create_app()


if __name__ == "__main__":
    app.run(
        host=app.config["APP_SETTINGS"]["server"]["host"],
        port=app.config["APP_SETTINGS"]["server"]["port"],
        debug=app.config["APP_SETTINGS"]["server"]["debug"],
    )
