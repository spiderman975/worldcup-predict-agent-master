from app.db.session import Base, engine


def init_db() -> None:
    """创建 SQLite 表结构。MVP 启动时自动执行，降低本地运行门槛。"""

    Base.metadata.create_all(bind=engine)
