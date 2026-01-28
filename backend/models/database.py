"""
数据库连接和初始化
"""

from sqlalchemy import create_engine, text, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager

from backend.utils.logger import logger

# 创建基类
Base = declarative_base()

# 全局引擎和会话工厂
engine = None
SessionLocal = None


def init_database(database_url: str = "sqlite:///./data/sync.db"):
    """
    初始化数据库
    
    Args:
        database_url: 数据库连接字符串
    """
    global engine, SessionLocal
    
    logger.info(f"初始化数据库: {database_url}")
    
    # 如果是 SQLite，确保数据库文件所在目录存在
    if database_url.startswith("sqlite"):
        from pathlib import Path
        # 提取数据库文件路径（去掉 sqlite:/// 前缀）
        db_path = database_url.replace("sqlite:///", "")
        db_file = Path(db_path)
        
        # 创建父目录
        if not db_file.parent.exists():
            db_file.parent.mkdir(parents=True, exist_ok=True)
            logger.info(f"创建数据库目录: {db_file.parent}")
    
    # 创建引擎
    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False, "timeout": 30} if database_url.startswith("sqlite") else {},
        echo=False  # 设置为 True 可以看到 SQL 语句
    )

    # SQLite 并发读写优化：WAL + busy_timeout（避免多线程下偶发 database is locked 导致事件丢失）
    if database_url.startswith("sqlite"):
        def _set_sqlite_pragma(dbapi_connection, connection_record):  # noqa: ARG001
            try:
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("PRAGMA busy_timeout=5000")
                cursor.close()
            except Exception:
                pass

        event.listen(engine, "connect", _set_sqlite_pragma)
    
    # 创建会话工厂
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    # 创建所有表
    from backend.models import sync_task
    from backend.models import sync_state
    Base.metadata.create_all(bind=engine)
    
    # 轻量迁移：为已存在的表补充新字段（SQLite）
    if database_url.startswith("sqlite"):
        with engine.connect() as conn:
            try:
                columns = conn.execute(text("PRAGMA table_info(sync_task_settings)")).fetchall()
                existing = {row[1] for row in columns}
                if 'trash_retention_days' not in existing:
                    conn.execute(text("ALTER TABLE sync_task_settings ADD COLUMN trash_retention_days INTEGER DEFAULT 7"))
                if 'backup_retention_days' not in existing:
                    conn.execute(text("ALTER TABLE sync_task_settings ADD COLUMN backup_retention_days INTEGER DEFAULT 7"))
                conn.commit()
            except Exception:
                pass
    logger.info("✓ 数据库初始化完成")


@contextmanager
def get_db() -> Session:
    """
    获取数据库会话（上下文管理器）
    
    用法:
        with get_db() as db:
            db.query(...)
    """
    if SessionLocal is None:
        raise RuntimeError("数据库未初始化，请先调用 init_database()")
    
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db_session() -> Session:
    """
    获取数据库会话（用于依赖注入）
    
    用法:
        db = next(get_db_session())
        try:
            db.query(...)
        finally:
            db.close()
    """
    if SessionLocal is None:
        raise RuntimeError("数据库未初始化，请先调用 init_database()")
    
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
