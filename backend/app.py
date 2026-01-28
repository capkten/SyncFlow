"""
文件同步助手 - FastAPI 主应用
"""

import sys
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.config.settings import load_config
from backend.models.database import init_database
from backend.core.task_manager import task_manager
from backend.utils.logger import setup_logger, logger
from backend.api import tasks, logs, config, ws
from backend.utils.realtime import ws_hub
import asyncio


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时执行
    logger.info("=" * 60)
    logger.info("文件同步助手启动中...")
    logger.info("=" * 60)
    
    # 加载配置
    app_config = load_config()
    logger.info(f"配置加载完成: {app_config.global_.database_path}")
    
    # 初始化数据库
    init_database(f"sqlite:///{app_config.global_.database_path}")

    # 绑定 WebSocket 推送事件循环
    ws_hub.set_loop(asyncio.get_running_loop())
    
    # 从数据库加载并启动任务
    task_manager.load_tasks_from_db()
    
    logger.info("✓ 文件同步助手启动完成")
    logger.info(f"Web 界面: http://{app_config.global_.web_host}:{app_config.global_.web_port}")
    logger.info("=" * 60)

    try:
        yield
    finally:
        # 关闭时执行（确保 Ctrl+C / CancelledError 也能清理后台线程）
        logger.info("文件同步助手关闭中...")
        task_manager.stop_all()
        logger.info("✓ 文件同步助手已关闭")


# 创建 FastAPI 应用
app = FastAPI(
    title="文件同步助手",
    description="跨平台文件实时同步工具",
    version="1.0.0",
    lifespan=lifespan
)

# CORS 中间件（允许前端跨域访问）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册 API 路由
app.include_router(tasks.router)
app.include_router(logs.router)
app.include_router(config.router)
app.include_router(ws.router)

# 健康检查接口（必须在静态文件挂载之前）
@app.get("/api/health")
def health_check():
    """健康检查"""
    return {
        "status": "ok",
        "message": "文件同步助手运行正常",
        "running_tasks": len(task_manager.runners)
    }

# 挂载静态文件（前端界面）- 必须放在最后，否则会覆盖 API 路由
frontend_path = Path(__file__).parent.parent / "frontend"
if frontend_path.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_path / "static")), name="static")
    app.mount("/", StaticFiles(directory=str(frontend_path), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    
    # 加载配置
    config = load_config()
    
    # 设置日志
    setup_logger(
        log_level=config.global_.log_level,
        log_dir="./logs"
    )
    
    # 启动服务
    uvicorn.run(
        app,  # 直接传递 app 对象
        host=config.global_.web_host,
        port=config.global_.web_port,
        reload=False,  # 生产环境设置为 False
        log_level=config.global_.log_level.lower()
    )
