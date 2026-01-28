"""
文件监控模块 - 基于 watchdog
"""

from pathlib import Path
from typing import Callable, List
from watchdog.observers import Observer
from watchdog.events import (
    FileSystemEventHandler,
    FileSystemEvent,
    FileCreatedEvent,
    FileModifiedEvent,
    FileDeletedEvent,
    FileMovedEvent
)

from backend.utils.logger import logger
from backend.utils.file_utils import should_exclude, should_include_extension


class SyncEventHandler(FileSystemEventHandler):
    """文件同步事件处理器"""
    
    def __init__(
        self,
        on_change: Callable[[str, str, str], None],  # 回调函数 (event_type, src_path, dest_path)
        exclude_patterns: List[str] = None,
        file_extensions: List[str] = None,
        base_path: str = None
    ):
        """
        初始化事件处理器
        
        Args:
            on_change: 文件变化时的回调函数
            exclude_patterns: 排除规则列表
            file_extensions: 允许的文件扩展名列表
            base_path: 基础路径（用于计算相对路径）
        """
        super().__init__()
        self.on_change = on_change
        self.exclude_patterns = exclude_patterns or []
        self.file_extensions = file_extensions or []
        self.base_path = Path(base_path) if base_path else None
        
    def _should_process(self, file_path: str) -> bool:
        """检查文件是否应该处理"""
        # 忽略目录事件（只处理文件）
        if Path(file_path).is_dir():
            return False
        
        # 检查排除规则
        if should_exclude(file_path, self.exclude_patterns):
            logger.debug(f"文件被排除规则过滤: {file_path}")
            return False
        
        # 检查扩展名
        if not should_include_extension(file_path, self.file_extensions):
            logger.debug(f"文件扩展名不匹配: {file_path}")
            return False
        
        return True
    
    def on_created(self, event: FileCreatedEvent):
        """文件创建事件"""
        if event.is_directory:
            return
        
        if self._should_process(event.src_path):
            logger.info(f"检测到文件创建: {event.src_path}")
            self.on_change('created', event.src_path, '')
    
    def on_modified(self, event: FileModifiedEvent):
        """文件修改事件"""
        if event.is_directory:
            return
        
        if self._should_process(event.src_path):
            logger.info(f"检测到文件修改: {event.src_path}")
            self.on_change('modified', event.src_path, '')
    
    def on_deleted(self, event: FileDeletedEvent):
        """文件删除事件"""
        if event.is_directory:
            return
        
        # 删除事件不需要检查文件是否存在
        logger.info(f"检测到文件删除: {event.src_path}")
        self.on_change('deleted', event.src_path, '')
    
    def on_moved(self, event: FileMovedEvent):
        """文件移动/重命名事件"""
        if event.is_directory:
            return
        
        # 检查源文件和目标文件
        src_should_process = should_exclude(event.src_path, self.exclude_patterns) == False
        dest_should_process = self._should_process(event.dest_path)
        
        if src_should_process or dest_should_process:
            logger.info(f"检测到文件移动: {event.src_path} -> {event.dest_path}")
            self.on_change('moved', event.src_path, event.dest_path)


class FileWatcher:
    """文件监控器"""
    
    def __init__(
        self,
        watch_path: str,
        on_change: Callable[[str, str, str], None],
        exclude_patterns: List[str] = None,
        file_extensions: List[str] = None
    ):
        """
        初始化文件监控器
        
        Args:
            watch_path: 监控的目录路径
            on_change: 文件变化时的回调函数
            exclude_patterns: 排除规则列表
            file_extensions: 允许的文件扩展名列表
        """
        self.watch_path = Path(watch_path)
        if not self.watch_path.exists():
            raise ValueError(f"监控路径不存在: {watch_path}")
        
        self.event_handler = SyncEventHandler(
            on_change=on_change,
            exclude_patterns=exclude_patterns,
            file_extensions=file_extensions,
            base_path=str(self.watch_path)
        )
        
        self.observer = Observer()
        # watchdog 的 Observer/Emitter 线程在极端情况下可能无法及时退出。
        # 设为 daemon，避免阻塞 FastAPI/Uvicorn 进程退出。
        self.observer.daemon = True
        self.is_running = False
        
    def start(self):
        """启动监控"""
        if self.is_running:
            logger.warning("文件监控已在运行中")
            return
        
        self.observer.schedule(
            self.event_handler,
            str(self.watch_path),
            recursive=True
        )
        self.observer.start()
        self.is_running = True
        logger.info(f"开始监控目录: {self.watch_path}")
        
    def stop(self):
        """停止监控"""
        if not self.is_running:
            return
        
        self.observer.stop()
        # 避免 join 无限阻塞导致 Ctrl+C 无法退出
        self.observer.join(timeout=5)
        if self.observer.is_alive():
            logger.warning(f"文件监控线程未能在超时内退出: {self.watch_path}")
        self.is_running = False
        logger.info(f"停止监控目录: {self.watch_path}")
    
    def __enter__(self):
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


if __name__ == '__main__':
    # 测试代码
    import time
    
    def on_file_change(event_type: str, src_path: str, dest_path: str):
        print(f"[{event_type}] {src_path} -> {dest_path}")
    
    # 监控当前目录
    watcher = FileWatcher(
        watch_path='.',
        on_change=on_file_change,
        exclude_patterns=['*.pyc', '__pycache__', '.git']
    )
    
    try:
        watcher.start()
        print("文件监控已启动，按 Ctrl+C 停止...")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        watcher.stop()
        print("文件监控已停止")
