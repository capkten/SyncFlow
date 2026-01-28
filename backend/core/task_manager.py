"""
任务管理器 - 管理多个同步任务的运行
"""

import threading
from typing import Dict, Optional
from pathlib import Path
import os

from backend.core.file_watcher import FileWatcher
from backend.core.sync_engine import LocalSyncEngine, SshSyncEngine
from backend.core.bidirectional import BidirectionalTaskRunner
from backend.models.database import get_db
from backend.models.sync_task import SyncTask, create_log
from backend.models.sync_state import get_task_settings, get_endpoints
from backend.utils.logger import logger
from backend.utils.crypto import decrypt_secret
from backend.utils.realtime import ws_hub
from backend.utils.file_utils import should_exclude, should_include_extension


class TaskRunner:
    """单个任务运行器"""
    
    def __init__(self, task: SyncTask):
        """
        初始化任务运行器
        
        Args:
            task: SyncTask 数据库模型对象
        """
        # 在 Session 关闭前，提取并保存所有需要的属性值
        # 这样可以避免 SQLAlchemy "not bound to Session" 错误
        self.task_id = task.id
        self.task_name = task.name
        
        # 构建任务配置字典（在 Session 内完成）
        self.task_config = {
            'name': task.name,
            'source_path': task.source_path,
            'target': {
                'type': task.target_type,
                'path': task.target_path,
                'host': task.target_host,
                'port': task.target_port,
                'username': task.target_username,
                'password': decrypt_secret(task.target_password),
                'ssh_key_path': task.target_ssh_key_path
            },
            'eol_normalize': task.eol_normalize,
            'exclude_patterns': task.exclude_patterns or [],
            'file_extensions': task.file_extensions or []
        }
        
        # 保存常用属性的快捷引用
        self.source_path = task.source_path
        self.target_type = task.target_type
        self.exclude_patterns = task.exclude_patterns or []
        self.file_extensions = task.file_extensions or []
        
        self.watcher: Optional[FileWatcher] = None
        self.sync_engine = None
        self.is_running = False
        self._lock = threading.Lock()
        self._scan_stop = threading.Event()
        self._scan_thread: Optional[threading.Thread] = None
        self._scan_interval_seconds = 5
        self._last_mtimes: Dict[str, float] = {}
        
        # 批量同步相关配置
        self._batch_queue = []  # 待同步的事件队列: [(event_type, rel_path, src_path, dest_path), ...]
        self._batch_lock = threading.Lock()
        self._batch_event = threading.Event()
        self._batch_thread: Optional[threading.Thread] = None
        self._batch_delay = 0.5  # 收集事件的等待时间
        self._batch_max_parallel = 4  # 最大并行同步数

    def _create_sync_engine(self):
        """根据任务配置创建同步引擎"""
        if self.target_type == 'local':
            # 本地同步
            self.sync_engine = LocalSyncEngine(self.task_config)
            
        elif self.target_type == 'ssh':
            # SSH 远程同步
            self.sync_engine = SshSyncEngine(self.task_config)
            # 注意：TaskRunner 自己负责 FileWatcher；这里仅建立 SSH 连接，避免重复启动监控线程
            try:
                ok = self.sync_engine.connect()
                if not ok:
                    raise ConnectionError("SSH 连接失败")
            except Exception as e:
                logger.error(f"建立 SSH 连接失败: {e}")
                raise
        else:
            raise ValueError(f"不支持的目标类型: {self.target_type}")

    def _scan_once(self) -> None:
        """
        扫描源目录一次，修复 watchdog 可能漏掉的事件。

        说明：部分工具（如 git checkout、原子写入、批量生成文件）可能导致 watchdog 丢事件，
        通过定时扫描可确保“本地变更最终会同步到远端”。
        """
        if not self.sync_engine:
            return
        source_root = Path(self.source_path)
        current: Dict[str, float] = {}

        for root, dirs, files in os.walk(source_root):
            if self._scan_stop.is_set():
                return

            # 过滤目录（基于绝对路径过滤即可）
            dirs[:] = [d for d in dirs if not should_exclude(Path(root) / d, self.exclude_patterns)]

            for filename in files:
                abs_path = Path(root) / filename
                if should_exclude(abs_path, self.exclude_patterns):
                    continue
                if not should_include_extension(abs_path, self.file_extensions):
                    continue
                try:
                    rel_path = str(abs_path.relative_to(source_root))
                except Exception:
                    continue
                try:
                    mtime = abs_path.stat().st_mtime
                except FileNotFoundError:
                    continue

                current[rel_path] = mtime
                last_mtime = self._last_mtimes.get(rel_path)
                if last_mtime is None:
                    try:
                        self.sync_engine.sync_file('created', rel_path, str(abs_path), '')
                    except Exception as e:
                        logger.error(f"扫描同步失败(created): {rel_path} - {e}")
                elif mtime != last_mtime:
                    try:
                        self.sync_engine.sync_file('modified', rel_path, str(abs_path), '')
                    except Exception as e:
                        logger.error(f"扫描同步失败(modified): {rel_path} - {e}")

        # 删除检测：之前存在，现在不存在
        for rel_path in list(self._last_mtimes.keys()):
            if self._scan_stop.is_set():
                return
            if rel_path not in current:
                abs_path = source_root / rel_path
                try:
                    self.sync_engine.sync_file('deleted', rel_path, str(abs_path), '')
                except Exception as e:
                    logger.error(f"扫描同步失败(deleted): {rel_path} - {e}")

        self._last_mtimes = current

    def _scan_loop(self) -> None:
        while not self._scan_stop.is_set():
            if not self.is_running:
                return
            try:
                with self._lock:
                    self._scan_once()
            except Exception as e:
                logger.error(f"扫描线程异常: {e}")
            self._scan_stop.wait(self._scan_interval_seconds)
    
    def _on_file_change(self, event_type: str, src_path: str, dest_path: str):
        """
        文件变化回调函数 - 将事件加入批量队列
        """
        if not self.sync_engine:
            return
        
        try:
            rel_path = str(Path(src_path).relative_to(self.source_path))
        except ValueError:
            return
        
        with self._batch_lock:
            self._batch_queue.append((event_type, rel_path, src_path, dest_path))
        
        # 通知批量处理线程
        self._batch_event.set()
    
    def _batch_sync_loop(self):
        """
        批量同步处理线程
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import time
        
        while not self._scan_stop.is_set():
            # 等待新事件或超时
            self._batch_event.wait(timeout=self._batch_delay)
            self._batch_event.clear()
            
            if self._scan_stop.is_set():
                break
            
            # 等待一小段时间收集更多事件
            time.sleep(0.1)
            
            # 取出所有待同步的事件
            with self._batch_lock:
                if not self._batch_queue:
                    continue
                events = list(self._batch_queue)
                self._batch_queue.clear()
            
            if not events:
                continue
            
            # 去重：同一文件只处理最新的事件
            unique_events = {}
            for ev in events:
                unique_events[ev[1]] = ev  # 用 rel_path 作为 key，保留最后一个事件
            events = list(unique_events.values())
            
            logger.info(f"批量同步开始: {len(events)} 个文件")
            start_time = time.time()
            
            # 並行执行同步
            completed = 0
            failed = 0
            
            with ThreadPoolExecutor(max_workers=self._batch_max_parallel) as executor:
                futures = {
                    executor.submit(self._sync_single_file, *ev): ev
                    for ev in events
                }
                
                for future in as_completed(futures):
                    try:
                        future.result()
                        completed += 1
                    except Exception as e:
                        failed += 1
                        ev = futures[future]
                        logger.error(f"批量同步失败: {ev[1]} - {e}")
            
            elapsed = time.time() - start_time
            logger.info(f"批量同步完成: 成功 {completed}, 失败 {failed}, 耗时 {elapsed:.2f}s")
    
    def _sync_single_file(self, event_type: str, rel_path: str, src_path: str, dest_path: str):
        """
        同步单个文件
        """
        status = 'success'
        error_message = None
        
        try:
            with self._lock:
                if not self.sync_engine:
                    return
                ok = self.sync_engine.sync_file(event_type, rel_path, src_path, dest_path)
                if ok is False:
                    if hasattr(self.sync_engine, 'should_stop') and self.sync_engine.should_stop():
                        status = 'skipped'
                        error_message = '任务已停止'
                    else:
                        raise RuntimeError("同步失败")
        except Exception as e:
            status = 'failed'
            error_message = str(e)
            logger.error(f"处理文件变化失败: {e}")
        
        try:
            with get_db() as db:
                create_log(db, {
                    'task_id': self.task_id,
                    'event_type': event_type,
                    'file_path': src_path,
                    'dest_path': dest_path if event_type == 'moved' else None,
                    'status': status,
                    'error_message': error_message
                })
        except Exception as e:
            logger.error(f"记录日志失败: {e}")
    
    def start(self):
        """启动任务"""
        if self.is_running:
            logger.warning(f"任务已在运行: {self.task_name}")
            return
        
        try:
            logger.info(f"启动任务: {self.task_name}")
            
            # 创建同步引擎
            self._create_sync_engine()
            
            # 创建文件监控器
            self.watcher = FileWatcher(
                watch_path=self.source_path,
                on_change=self._on_file_change,
                exclude_patterns=self.exclude_patterns,
                file_extensions=self.file_extensions
            )
            
            # 启动监控
            self.watcher.start()
            self.is_running = True

            # 启动批量同步处理线程
            self._scan_stop.clear()
            self._batch_thread = threading.Thread(target=self._batch_sync_loop, daemon=True)
            self._batch_thread.start()

            # 启动兜底扫描线程（避免 watchdog 漏事件导致不同步）
            self._scan_thread = threading.Thread(target=self._scan_loop, daemon=True)
            self._scan_thread.start()
            
            logger.info(f"✓ 任务已启动: {self.task_name}")
            
        except Exception as e:
            logger.error(f"✗ 启动任务失败: {self.task_name} - {e}")
            self.stop()
            raise
    
    def stop(self):
        """停止任务"""
        if not self.is_running:
            return
        
        logger.info(f"停止任务: {self.task_name}")
        self._scan_stop.set()
        
        # 停止文件监控
        if self.watcher:
            self.watcher.stop()
            self.watcher = None
        
        # 停止同步引擎（包括关闭 SSH 连接）
        if self.sync_engine:
            self.sync_engine.stop()
            self.sync_engine = None

        if self._scan_thread and self._scan_thread.is_alive():
            self._scan_thread.join(timeout=2)
        self._scan_thread = None
        
        # 停止批量同步线程
        self._batch_event.set()  # 唤醒线程
        if self._batch_thread and self._batch_thread.is_alive():
            self._batch_thread.join(timeout=2)
        self._batch_thread = None
        
        self.is_running = False
        
        logger.info(f"✓ 任务已停止: {self.task_name}")
    
    def sync_all(self, force: bool = False) -> dict:
        """
        执行全量同步
        
        Args:
            force: 是否强制同步所有文件
            
        Returns:
            统计信息字典
        """
        if not self.sync_engine:
            self._create_sync_engine()
        
        # 定义回调函数记录日志
        def log_callback(status: str, rel_path: str, src_path: str, error_msg: Optional[str] = None):
            try:
                # 仅记录失败的日志，避免全量同步时产生海量成功日志
                # 如果用户希望看所有日志，可以去掉 status == 'failed' 条件
                if status == 'failed':
                    with get_db() as db:
                        create_log(db, {
                            'task_id': self.task_id,
                            'event_type': 'sync_all',
                            'file_path': src_path,
                            'status': status,
                            'error_message': error_msg
                        })
            except Exception as e:
                logger.error(f"记录日志失败: {e}")

        # 将回调传递给 sync_all
        return self.sync_engine.sync_all(force=force, callback=log_callback)


class TaskManager:
    """任务管理器 - 管理所有同步任务"""
    
    def __init__(self):
        self.runners: Dict[int, TaskRunner] = {}  # task_id -> TaskRunner
        self._lock = threading.Lock()
    
    def load_tasks_from_db(self):
        """从数据库加载所有启用的任务"""
        with get_db() as db:
            from backend.models.sync_task import get_all_tasks
            tasks = get_all_tasks(db, enabled_only=True)
            
            for task in tasks:
                if task.auto_start:
                    try:
                        self.start_task(task.id)
                    except Exception as e:
                        logger.error(f"自动启动任务失败: {task.name} - {e}")
    
    def start_task(self, task_id: int):
        """
        启动指定任务
        
        Args:
            task_id: 任务 ID
        """
        with self._lock:
            if task_id in self.runners:
                logger.warning(f"任务已在运行: {task_id}")
                return
            
            # 从数据库加载任务
            with get_db() as db:
                from backend.models.sync_task import get_task
                task = get_task(db, task_id)
                
                if not task:
                    raise ValueError(f"任务不存在: {task_id}")
                
                if not task.enabled:
                    raise ValueError(f"任务未启用: {task.name}")
                
                settings = get_task_settings(db, task_id)
                mode = settings.mode if settings else "one_way"
                
                if mode == "two_way":
                    endpoints = get_endpoints(db, task_id)
                    if not endpoints:
                        endpoints = {
                            'a': {
                                'type': 'local',
                                'path': task.source_path
                            },
                            'b': {
                                'type': task.target_type,
                                'path': task.target_path,
                                'host': task.target_host,
                                'port': task.target_port,
                                'username': task.target_username,
                                'password': decrypt_secret(task.target_password),
                                'ssh_key_path': task.target_ssh_key_path
                            }
                        }
                    else:
                        endpoints = {
                            side: {
                                'type': ep.type,
                                'path': ep.path,
                                'host': ep.host,
                                'port': ep.port,
                                'username': ep.username,
                                'password': decrypt_secret(ep.password),
                                'ssh_key_path': ep.ssh_key_path,
                                'trash_dir': ep.trash_dir,
                                'backup_dir': ep.backup_dir
                            }
                            for side, ep in endpoints.items()
                        }
                    runner = BidirectionalTaskRunner(task, endpoints, settings)
                else:
                    runner = TaskRunner(task)
                
                runner.start()
                self.runners[task_id] = runner
                ws_hub.publish_task_status({
                    'task_id': task.id,
                    'name': task.name,
                    'enabled': task.enabled,
                    'is_running': True
                })
    
    def stop_task(self, task_id: int):
        """
        停止指定任务
        
        Args:
            task_id: 任务 ID
        """
        with self._lock:
            runner = self.runners.get(task_id)
            if runner:
                runner.stop()
                del self.runners[task_id]
                ws_hub.publish_task_status({
                    'task_id': task_id,
                    'is_running': False
                })
            else:
                logger.warning(f"任务未在运行: {task_id}")
    
    def restart_task(self, task_id: int):
        """重启任务"""
        self.stop_task(task_id)
        self.start_task(task_id)
    
    def sync_task_all(self, task_id: int, force: bool = False) -> dict:
        """
        执行任务的全量同步
        
        Args:
            task_id: 任务 ID
            force: 是否强制同步
            
        Returns:
            统计信息字典
        """
        runner = self.runners.get(task_id)
        if runner:
            return runner.sync_all(force=force)
        
        with get_db() as db:
            from backend.models.sync_task import get_task
            task = get_task(db, task_id)
            
            if not task:
                raise ValueError(f"任务不存在: {task_id}")
            
            settings = get_task_settings(db, task_id)
            mode = settings.mode if settings else "one_way"
            
            if mode == "two_way":
                endpoints = get_endpoints(db, task_id)
                if not endpoints:
                    endpoints = {
                        'a': {
                            'type': 'local',
                            'path': task.source_path
                        },
                        'b': {
                            'type': task.target_type,
                            'path': task.target_path,
                            'host': task.target_host,
                            'port': task.target_port,
                            'username': task.target_username,
                                'password': decrypt_secret(task.target_password),
                            'ssh_key_path': task.target_ssh_key_path
                        }
                    }
                else:
                    endpoints = {
                        side: {
                            'type': ep.type,
                            'path': ep.path,
                            'host': ep.host,
                            'port': ep.port,
                            'username': ep.username,
                                'password': decrypt_secret(ep.password),
                            'ssh_key_path': ep.ssh_key_path,
                            'trash_dir': ep.trash_dir,
                            'backup_dir': ep.backup_dir
                        }
                        for side, ep in endpoints.items()
                    }
                temp_runner = BidirectionalTaskRunner(task, endpoints, settings)
                return temp_runner.sync_all(force=force)
            else:
                temp_runner = TaskRunner(task)
                return temp_runner.sync_all(force=force)
    
    def get_task_status(self, task_id: int) -> dict:
        """
        获取任务状态
        
        Args:
            task_id: 任务 ID
            
        Returns:
            状态字典
        """
        runner = self.runners.get(task_id)
        return {
            'task_id': task_id,
            'is_running': runner.is_running if runner else False
        }
    
    def get_all_status(self) -> list:
        """获取所有任务状态"""
        with get_db() as db:
            from backend.models.sync_task import get_all_tasks
            tasks = get_all_tasks(db)
            
            return [
                {
                    'task_id': task.id,
                    'name': task.name,
                    'enabled': task.enabled,
                    'is_running': task.id in self.runners
                }
                for task in tasks
            ]
    
    def stop_all(self):
        """停止所有任务"""
        logger.info("停止所有任务...")
        task_ids = list(self.runners.keys())
        for task_id in task_ids:
            self.stop_task(task_id)
        logger.info("✓ 所有任务已停止")


# 全局任务管理器实例
task_manager = TaskManager()
