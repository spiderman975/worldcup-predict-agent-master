import logging


def configure_logging() -> None:
    """配置简洁的控制台日志，便于本地调试预测流程。"""

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
