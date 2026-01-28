import os
import stat
import hashlib
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

from backend.core.file_watcher import FileWatcher
from backend.core.eol_normalizer import TEXT_EXTENSIONS
from backend.models.database import get_db
from backend.models.sync_task import create_log
from backend.models.sync_state import get_all_file_states, upsert_file_state
from backend.utils.file_utils import should_exclude, should_include_extension, ensure_parent_dir
from backend.utils.logger import logger

# 尝试导入远程 inotify 模块
try:
    from backend.core.remote_inotify import RemoteInotifyWatcher
    INOTIFY_AVAILABLE = True
except ImportError:
    INOTIFY_AVAILABLE = False


def _normalize_bytes(content: bytes, target: str) -> bytes:
    if target == 'keep':
        return content
    normalized = content.replace(b'\r\n', b'\n')
    normalized = normalized.replace(b'\r', b'\n')
    if target == 'crlf':
        normalized = normalized.replace(b'\n', b'\r\n')
    return normalized


def _is_text_path(rel_path: str) -> bool:
    path = Path(rel_path)
    ext = path.suffix.lower()
    if ext in TEXT_EXTENSIONS:
        return True
    special_names = {'Makefile', 'Dockerfile', 'Jenkinsfile', 'README', 'LICENSE'}
    return path.name in special_names


class LocalEndpoint:
    def __init__(self, side: str, root: str, exclude_patterns, file_extensions, trash_dir, backup_dir):
        self.side = side
        self.type = 'local'
        self.root = Path(root)
        self.exclude_patterns = list(exclude_patterns or [])
        self.file_extensions = list(file_extensions or [])
        self.trash_dir = trash_dir
        self.backup_dir = backup_dir
        self._internal_dirs = {trash_dir, backup_dir}

    def _is_excluded(self, rel_path: str) -> bool:
        parts = rel_path.replace('\\', '/').split('/')
        if any(p in self._internal_dirs for p in parts):
            return True
        rel_os = rel_path.replace('/', os.sep)
        return should_exclude(rel_os, self.exclude_patterns)

    def _abs_path(self, rel_path: str) -> Path:
        return self.root / Path(rel_path)

    def list_files(self) -> Dict[str, Dict]:
        return dict(self.iter_files())

    def iter_files(self):
        """
        遍历文件并按需过滤（流式），用于轮询扫描时避免一次性构建超大字典导致卡顿。
        """
        for root, dirs, files in os.walk(self.root):
            rel_root = Path(root).relative_to(self.root)
            rel_root_str = rel_root.as_posix() if rel_root.as_posix() != '.' else ''
            dirs[:] = [
                d for d in dirs
                if not self._is_excluded(f"{rel_root_str}/{d}" if rel_root_str else d)
            ]
            for filename in files:
                rel_path = f"{rel_root_str}/{filename}" if rel_root_str else filename
                if self._is_excluded(rel_path):
                    continue
                if not should_include_extension(rel_path, self.file_extensions):
                    continue
                meta = self.get_meta(rel_path)
                if meta:
                    yield rel_path, meta

    def get_meta(self, rel_path: str) -> Optional[Dict]:
        abs_path = self._abs_path(rel_path)
        if not abs_path.exists():
            return None
        stat = abs_path.stat()
        return {'size': stat.st_size, 'mtime': stat.st_mtime}

    def read_bytes(self, rel_path: str) -> bytes:
        abs_path = self._abs_path(rel_path)
        with open(abs_path, 'rb') as f:
            return f.read()

    def write_bytes(self, rel_path: str, data: bytes):
        abs_path = self._abs_path(rel_path)
        ensure_parent_dir(abs_path)
        with open(abs_path, 'wb') as f:
            f.write(data)

    def copy_file(self, src_abs: Path, rel_path: str):
        dest_abs = self._abs_path(rel_path)
        ensure_parent_dir(dest_abs)
        import shutil
        shutil.copy2(src_abs, dest_abs)

    def move_to_trash(self, rel_path: str, ts: str):
        src_abs = self._abs_path(rel_path)
        if not src_abs.exists():
            return
        trash_abs = self._abs_path(f"{self.trash_dir}/{ts}/{rel_path}")
        ensure_parent_dir(trash_abs)
        import shutil
        shutil.move(str(src_abs), str(trash_abs))

    def backup_file(self, rel_path: str, ts: str):
        src_abs = self._abs_path(rel_path)
        if not src_abs.exists():
            return
        backup_abs = self._abs_path(f"{self.backup_dir}/{ts}/{rel_path}")
        ensure_parent_dir(backup_abs)
        import shutil
        shutil.copy2(src_abs, backup_abs)

    def cleanup(self, trash_retention_days: int, backup_retention_days: int):
        now = datetime.now()
        if trash_retention_days and trash_retention_days > 0:
            self._cleanup_dir(self.trash_dir, trash_retention_days, now)
        if backup_retention_days and backup_retention_days > 0:
            self._cleanup_dir(self.backup_dir, backup_retention_days, now)

    def _cleanup_dir(self, base_dir: str, retention_days: int, now: datetime):
        base = self._abs_path(base_dir)
        if not base.exists():
            return
        for entry in base.iterdir():
            if not entry.is_dir():
                continue
            ts = self._parse_ts(entry.name)
            if not ts:
                ts = datetime.fromtimestamp(entry.stat().st_mtime)
            if (now - ts).days >= retention_days:
                import shutil
                shutil.rmtree(entry, ignore_errors=True)

    @staticmethod
    def _parse_ts(name: str) -> Optional[datetime]:
        try:
            return datetime.strptime(name, '%Y%m%d_%H%M%S')
        except Exception:
            return None


class SshEndpoint:
    def __init__(self, side: str, transfer, root: str, exclude_patterns, file_extensions, trash_dir, backup_dir):
        self.side = side
        self.type = 'ssh'
        self.transfer = transfer
        self.root = root.rstrip('/')
        self.exclude_patterns = list(exclude_patterns or [])
        self.file_extensions = list(file_extensions or [])
        self.trash_dir = trash_dir
        self.backup_dir = backup_dir
        self._internal_dirs = {trash_dir, backup_dir}

    def _is_excluded(self, rel_path: str) -> bool:
        parts = rel_path.replace('\\', '/').split('/')
        if any(p in self._internal_dirs for p in parts):
            return True
        rel_os = rel_path.replace('/', os.sep)
        return should_exclude(rel_os, self.exclude_patterns)

    def _remote_path(self, rel_path: str) -> str:
        rel_posix = rel_path.replace('\\', '/')
        return f"{self.root}/{rel_posix}"

    def connect(self) -> bool:
        try:
            self.transfer.connect()
            if not self.transfer.exists(self.root):
                self.transfer.mkdir_p(self.root)
            return True
        except Exception as e:
            logger.error(f"SSH 连接失败: {e}")
            return False

    def list_files(self) -> Dict[str, Dict]:
        return dict(self.iter_files())

    def iter_files(self):
        """
        遍历远端文件并按需过滤（流式），避免轮询时长时间阻塞在一次性全量 list_files 上。
        """
        for rel_path, attr in self.transfer.iter_files(self.root):
            if self._is_excluded(rel_path):
                continue
            if not should_include_extension(rel_path, self.file_extensions):
                continue
            yield rel_path, {'size': attr.st_size, 'mtime': attr.st_mtime}

    def get_meta(self, rel_path: str) -> Optional[Dict]:
        try:
            attr = self.transfer.stat(self._remote_path(rel_path))
            return {'size': attr.st_size, 'mtime': attr.st_mtime}
        except FileNotFoundError:
            return None
        except Exception:
            return None

    def read_bytes(self, rel_path: str) -> bytes:
        return self.transfer.read_file_bytes(self._remote_path(rel_path))

    def write_bytes(self, rel_path: str, data: bytes):
        self.transfer.write_file_bytes(self._remote_path(rel_path), data)

    def upload_file(self, local_path: Path, rel_path: str):
        self.transfer.upload_file(str(local_path), self._remote_path(rel_path))

    def download_file(self, rel_path: str, local_path: Path):
        self.transfer.download_file(self._remote_path(rel_path), str(local_path))

    def move_to_trash(self, rel_path: str, ts: str):
        remote_src = self._remote_path(rel_path)
        remote_trash = self._remote_path(f"{self.trash_dir}/{ts}/{rel_path}")
        try:
            self.transfer.move_file(remote_src, remote_trash)
        except Exception:
            try:
                data = self.read_bytes(rel_path)
                self.write_bytes(f"{self.trash_dir}/{ts}/{rel_path}", data)
                self.transfer.delete_file(remote_src)
            except Exception as e:
                logger.error(f"回收站移动失败: {e}")

    def backup_file(self, rel_path: str, ts: str):
        try:
            data = self.read_bytes(rel_path)
            self.write_bytes(f"{self.backup_dir}/{ts}/{rel_path}", data)
        except Exception as e:
            logger.error(f"备份失败: {e}")

    def cleanup(self, trash_retention_days: int, backup_retention_days: int):
        now = datetime.now()
        if trash_retention_days and trash_retention_days > 0:
            self._cleanup_dir(self.trash_dir, trash_retention_days, now)
        if backup_retention_days and backup_retention_days > 0:
            self._cleanup_dir(self.backup_dir, backup_retention_days, now)

    def _cleanup_dir(self, base_dir: str, retention_days: int, now: datetime):
        remote_base = self._remote_path(base_dir)
        try:
            entries = self.transfer.listdir_attr(remote_base)
        except Exception:
            return
        for attr in entries:
            name = attr.filename
            if not name:
                continue
            if not attr or not hasattr(attr, 'st_mode'):
                continue
            if not stat.S_ISDIR(attr.st_mode):
                continue
            ts = self._parse_ts(name)
            if not ts:
                ts = datetime.fromtimestamp(attr.st_mtime)
            if (now - ts).days >= retention_days:
                self.transfer.remove_dir_recursive(f"{remote_base}/{name}")

    @staticmethod
    def _parse_ts(name: str) -> Optional[datetime]:
        try:
            return datetime.strptime(name, '%Y%m%d_%H%M%S')
        except Exception:
            return None


class BidirectionalTaskRunner:
    def __init__(self, task, endpoints: Dict[str, Dict], settings):
        self.task_id = task.id
        self.task_name = task.name
        self.exclude_patterns = task.exclude_patterns or []
        self.file_extensions = task.file_extensions or []
        self.eol_normalize = task.eol_normalize or 'keep'
        self.poll_interval = settings.poll_interval_seconds if settings and settings.poll_interval_seconds else 1.5  # 默认 1.5 秒
        self.trash_dir = settings.trash_dir if settings and settings.trash_dir else '.tongbu_trash'
        self.backup_dir = settings.backup_dir if settings and settings.backup_dir else '.tongbu_backup'

        self.endpoints = {}
        for side, ep in endpoints.items():
            if ep['type'] == 'local':
                self.endpoints[side] = LocalEndpoint(
                    side=side,
                    root=ep['path'],
                    exclude_patterns=self.exclude_patterns,
                    file_extensions=self.file_extensions,
                    trash_dir=ep.get('trash_dir') or self.trash_dir,
                    backup_dir=ep.get('backup_dir') or self.backup_dir
                )
            else:
                from backend.core.transfer import SSHTransfer
                transfer = SSHTransfer(
                    host=ep.get('host'),
                    port=ep.get('port', 22),
                    username=ep.get('username'),
                    password=ep.get('password'),
                    key_filename=ep.get('ssh_key_path')
                )
                self.endpoints[side] = SshEndpoint(
                    side=side,
                    transfer=transfer,
                    root=ep['path'],
                    exclude_patterns=self.exclude_patterns,
                    file_extensions=self.file_extensions,
                    trash_dir=ep.get('trash_dir') or self.trash_dir,
                    backup_dir=ep.get('backup_dir') or self.backup_dir
                )

        self.is_running = False
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._poll_threads = []
        self._cleanup_thread = None
        self._init_thread = None
        self._init_done = threading.Event()
        self._watchers = {}
        self._state_cache = {}
        self._suppress = {'a': {}, 'b': {}}
        self._suppress_window = 2
        self._cleanup_interval = 3600
        self._trash_retention_days = settings.trash_retention_days if settings and settings.trash_retention_days is not None else 7
        self._backup_retention_days = settings.backup_retention_days if settings and settings.backup_retention_days is not None else 7
        self._hash_algo = 'md5'
        # 远端轮询补偿：部分 SFTP/文件系统 mtime 分辨率较低（秒级），可能出现"内容变了但 size/mtime 不变"。
        # 为避免漏同步，轮询时会在预算内对部分文件做内容一致性校验（对比两端 hash）。
        self._hash_check_max_size = 2 * 1024 * 1024  # 2MB
        self._hash_budget_per_scan = 50
        self._poll_tick = {'a': 0, 'b': 0}
        self._poll_heartbeat_every = 12
        
        # 批量同步相关配置
        self._batch_queue = []  # 待同步的文件路径队列
        self._batch_lock = threading.Lock()
        self._batch_event = threading.Event()  # 通知批量处理线程有新任务
        self._batch_thread = None
        self._batch_delay = 0.5  # 收集事件的等待时间（秒），短暂等待以收集更多事件
        self._batch_max_wait = 2.0  # 最长等待时间
        self._batch_max_parallel = 8  # 最大并行同步数
        
        # 远程 inotify 监控器
        self._inotify_watchers = {}
        
        # 同步状态跟踪（避免轮询和同步冲突）
        self._syncing = threading.Event()  # 标记是否正在同步

    def _is_suppressed(self, side: str, rel_path: str) -> bool:
        ts = self._suppress.get(side, {}).get(rel_path)
        if not ts:
            return False
        if time.time() > ts:
            self._suppress[side].pop(rel_path, None)
            return False
        return True

    def _mark_suppressed(self, side: str, rel_path: str):
        self._suppress.setdefault(side, {})[rel_path] = time.time() + self._suppress_window

    def _load_state(self):
        with get_db() as db:
            rows = get_all_file_states(db, self.task_id)
            self._state_cache = {k: self._row_to_state(v) for k, v in rows.items()}

    def _row_to_state(self, row):
        return {
            'a_meta': row.a_meta or {},
            'b_meta': row.b_meta or {},
            'a_deleted': row.a_deleted,
            'b_deleted': row.b_deleted,
            'a_seen_at': row.a_seen_at,
            'b_seen_at': row.b_seen_at,
            'last_winner': row.last_winner,
            'last_sync_at': row.last_sync_at
        }

    def _save_state(self, rel_path: str, state: Dict):
        with get_db() as db:
            upsert_file_state(db, self.task_id, rel_path, {
                'a_meta': state.get('a_meta') or {},
                'b_meta': state.get('b_meta') or {},
                'a_deleted': state.get('a_deleted', False),
                'b_deleted': state.get('b_deleted', False),
                'a_seen_at': state.get('a_seen_at'),
                'b_seen_at': state.get('b_seen_at'),
                'last_winner': state.get('last_winner'),
                'last_sync_at': state.get('last_sync_at')
            })

    def start(self):
        if self.is_running:
            return
        self._stop_event.clear()
        self._init_done.clear()

        # 基本校验/连接（避免在这里做重型全量初始化，防止阻塞 FastAPI 启动与 API 响应）
        for side, endpoint in self.endpoints.items():
            if endpoint.type == 'local' and not endpoint.root.exists():
                raise ValueError(f"监控路径不存在: {endpoint.root}")
            if endpoint.type == 'ssh':
                if not endpoint.connect():
                    raise RuntimeError("SSH 连接失败")

        # 先启动本地 watcher（轻量）
        for side, endpoint in self.endpoints.items():
            if endpoint.type != 'local':
                continue
            watcher = FileWatcher(
                watch_path=str(endpoint.root),
                on_change=lambda event_type, src, dest, s=side: self._on_local_event(s, event_type, src, dest),
                exclude_patterns=list(self.exclude_patterns) + [endpoint.trash_dir, endpoint.backup_dir],
                file_extensions=self.file_extensions
            )
            watcher.start()
            self._watchers[side] = watcher

        # 标记运行中后，再异步执行首次基线同步与 SSH 轮询线程启动
        self.is_running = True
        
        # 启动批量同步处理线程
        self._batch_thread = threading.Thread(target=self._batch_sync_loop, daemon=False)
        self._batch_thread.start()
        
        self._init_thread = threading.Thread(target=self._init_background, daemon=False)
        self._init_thread.start()
        logger.info(f"✓ 任务已启动(初始化中): {self.task_name}")

    def stop(self):
        if not self.is_running:
            self._stop_event.set()
            return
        self._stop_event.set()

        # 先关闭 SSH 连接，避免轮询线程卡在网络 IO 无法退出
        for endpoint in self.endpoints.values():
            if endpoint.type == 'ssh':
                try:
                    endpoint.transfer.close()
                except Exception:
                    pass

        for watcher in self._watchers.values():
            try:
                watcher.stop()
            except Exception:
                pass

        if self._init_thread and self._init_thread.is_alive():
            try:
                self._init_thread.join(timeout=10)
            except Exception:
                pass

        for t in self._poll_threads:
            try:
                t.join(timeout=10)
            except Exception:
                pass
        if self._cleanup_thread:
            try:
                self._cleanup_thread.join(timeout=10)
            except Exception:
                pass
        
        # 停止批量同步线程
        self._batch_event.set()  # 唤醒线程以便退出
        if self._batch_thread and self._batch_thread.is_alive():
            try:
                self._batch_thread.join(timeout=5)
            except Exception:
                pass
        self._batch_thread = None
        
        # 停止远程 inotify 监控器
        for watcher in self._inotify_watchers.values():
            try:
                watcher.stop()
            except Exception:
                pass
        self._inotify_watchers = {}
        
        self._watchers = {}
        self._poll_threads = []
        self.is_running = False
        logger.info(f"✓ 任务已停止: {self.task_name}")

    def _init_background(self):
        """
        后台初始化，避免在 FastAPI lifespan/startup 阶段阻塞。
        """
        try:
            self._load_state()
            self._init_done.set()

            # 启动清理线程
            self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=False)
            self._cleanup_thread.start()

            # 对于 SSH 端点，优先尝试使用 inotify 实时监控
            for side, endpoint in self.endpoints.items():
                if endpoint.type != 'ssh':
                    continue
                
                # 尝试启动 inotify 监控
                inotify_started = False
                if INOTIFY_AVAILABLE:
                    try:
                        inotify_watcher = RemoteInotifyWatcher(
                            ssh_client=endpoint.transfer.ssh,
                            watch_path=endpoint.root,
                            on_change=lambda event_type, rel_path, s=side: self._on_remote_event(s, event_type, rel_path),
                            exclude_patterns=self.exclude_patterns
                        )
                        if inotify_watcher.start():
                            self._inotify_watchers[side] = inotify_watcher
                            inotify_started = True
                            logger.info(f"✓ 远端 inotify 监控已启动: side={side}")
                    except Exception as e:
                        logger.warning(f"启动远端 inotify 失败，回退到轮询模式: {e}")
                
                # 如果 inotify 不可用，使用轮询作为回退
                if not inotify_started:
                    t = threading.Thread(target=self._poll_loop, args=(side, endpoint), daemon=False)
                    t.start()
                    self._poll_threads.append(t)
                    logger.info(f"远端轮询已启动: side={side}, interval={self.poll_interval}s")

            # 仅在首次运行（无任何状态）时进行基线同步，避免每次启动都全量遍历导致“卡住/无响应”
            if not self._state_cache and not self._stop_event.is_set():
                self._initial_sync()
        except Exception as e:
            logger.error(f"双向任务初始化失败: {e}")

    def _on_remote_event(self, side: str, event_type: str, rel_path: str):
        """
        处理远程 inotify 事件
        """
        endpoint = self.endpoints.get(side)
        if not endpoint:
            return
        
        if self._is_suppressed(side, rel_path):
            return
        
        try:
            if event_type == 'deleted':
                self._handle_meta_change(side, rel_path, None, deleted=True, seen_at=datetime.now(), endpoint=endpoint)
            else:
                meta = endpoint.get_meta(rel_path)
                if meta:
                    self._handle_meta_change(side, rel_path, meta, deleted=False, seen_at=datetime.now(), endpoint=endpoint, hash_budget=None)
        except Exception as e:
            logger.error(f"处理远端 inotify 事件失败: side={side}, type={event_type}, path={rel_path} - {e}")

    def _poll_loop(self, side: str, endpoint: SshEndpoint):
        """轮询循环，智能避开同步进行时的重复检测"""
        while not self._stop_event.is_set():
            try:
                # 如果正在同步，等待同步完成后再轮询
                if self._syncing.is_set():
                    self._stop_event.wait(0.5)
                    continue
                
                if self._init_done.is_set():
                    start = time.time()
                    scanned, missing = self._scan_endpoint(side, endpoint)
                    self._poll_tick[side] = (self._poll_tick.get(side, 0) + 1) % 10_000_000
                    if self._poll_tick[side] % self._poll_heartbeat_every == 0:
                        cost_ms = int((time.time() - start) * 1000)
                        logger.info(f"远端轮询心跳: side={side}, scanned={scanned}, missing={missing}, cost={cost_ms}ms")
            except Exception as e:
                logger.error(f"远端扫描失败: {e}")
            self._stop_event.wait(self.poll_interval)

    def _cleanup_loop(self):
        while not self._stop_event.is_set():
            try:
                self._cleanup_endpoints()
            except Exception as e:
                logger.error(f"清理失败: {e}")
            self._stop_event.wait(self._cleanup_interval)

    def _cleanup_endpoints(self):
        for endpoint in self.endpoints.values():
            endpoint.cleanup(self._trash_retention_days, self._backup_retention_days)

    def _scan_endpoint(self, side: str, endpoint):
        now = datetime.now()
        hash_budget = {'remain': self._hash_budget_per_scan}
        with self._lock:
            state_snapshot = dict(self._state_cache)
        known_paths = set(state_snapshot.keys())

        seen_paths = set()
        iterator = getattr(endpoint, "iter_files", None)
        if not iterator:
            # 兜底：旧实现
            current = endpoint.list_files()
            iterator = current.items

        scanned = 0
        for rel_path, meta in iterator():
            if self._stop_event.is_set():
                return scanned, 0
            seen_paths.add(rel_path)
            scanned += 1
            self._handle_meta_change(side, rel_path, meta, deleted=False, seen_at=now, endpoint=endpoint, hash_budget=hash_budget)

        # 删除检测：之前存在，现在不在
        missing = known_paths - seen_paths
        for rel_path in missing:
            if self._stop_event.is_set():
                return scanned, len(missing)
            state = state_snapshot.get(rel_path) or {}
            key_meta = f"{side}_meta"
            key_deleted = f"{side}_deleted"
            key_seen = f"{side}_seen_at"
            # 只对“曾经在该端出现过/同步写入过”的文件做缺失判定，避免把“尚未扫描到的另一端”误判为删除。
            if not state.get(key_meta) and not state.get(key_deleted) and not state.get(key_seen):
                continue
            self._handle_meta_change(side, rel_path, None, deleted=True, seen_at=now, endpoint=endpoint, hash_budget=hash_budget)
        return scanned, len(missing)

    def _on_local_event(self, side: str, event_type: str, src_path: str, dest_path: str):
        endpoint = self.endpoints[side]
        try:
            rel_src = str(Path(src_path).relative_to(endpoint.root).as_posix())
        except Exception:
            return
        if self._is_suppressed(side, rel_src):
            return
        try:
            if event_type == 'moved' and dest_path:
                try:
                    rel_dest = str(Path(dest_path).relative_to(endpoint.root).as_posix())
                except Exception:
                    rel_dest = None
                self._handle_meta_change(side, rel_src, None, deleted=True, seen_at=datetime.now(), endpoint=endpoint)
                if rel_dest:
                    meta = endpoint.get_meta(rel_dest)
                    if meta:
                        self._handle_meta_change(side, rel_dest, meta, deleted=False, seen_at=datetime.now(), endpoint=endpoint, hash_budget=None)
                return

            if event_type == 'deleted':
                self._handle_meta_change(side, rel_src, None, deleted=True, seen_at=datetime.now(), endpoint=endpoint)
                return

            meta = endpoint.get_meta(rel_src)
            if meta:
                self._handle_meta_change(side, rel_src, meta, deleted=False, seen_at=datetime.now(), endpoint=endpoint, hash_budget=None)
        except Exception as e:
            # watchdog 回调线程异常默认不会在主线程显式展示，这里必须打日志便于定位问题（如 sqlite 锁）
            logger.error(f"处理本地事件失败: side={side}, type={event_type}, path={rel_src} - {e}")

    def _consume_hash_budget(self, budget: Optional[Dict], units: int = 1) -> bool:
        if not budget:
            return True
        remain = int(budget.get('remain') or 0)
        if remain < units:
            return False
        budget['remain'] = remain - units
        return True

    def _handle_meta_change(self, side: str, rel_path: str, meta: Optional[Dict], deleted: bool, seen_at: datetime, endpoint, hash_budget: Optional[Dict] = None):
        needs_reconcile = False
        info_message = None
        with self._lock:
            state = self._state_cache.get(rel_path, {
                'a_meta': {},
                'b_meta': {},
                'a_deleted': False,
                'b_deleted': False,
                'a_seen_at': None,
                'b_seen_at': None,
                'last_winner': None,
                'last_sync_at': None
            })

            key_meta = f"{side}_meta"
            key_deleted = f"{side}_deleted"
            key_seen = f"{side}_seen_at"

            if deleted:
                if state.get(key_deleted) and not state.get(key_meta):
                    return
                state[key_meta] = {}
                state[key_deleted] = True
                state[key_seen] = seen_at
                needs_reconcile = True
            else:
                if self._meta_changed(state.get(key_meta, {}), meta):
                    new_hash = self._compute_hash(endpoint, rel_path)
                    meta = dict(meta or {})
                    if new_hash:
                        meta['hash'] = new_hash
                    old_hash = (state.get(key_meta, {}) or {}).get('hash')
                    if old_hash and new_hash and old_hash == new_hash:
                        state[key_meta] = meta
                        state[key_deleted] = False
                        state[key_seen] = seen_at
                        self._state_cache[rel_path] = state
                        self._save_state(rel_path, state)
                        return
                    state[key_meta] = meta or {}
                    state[key_deleted] = False
                    state[key_seen] = seen_at
                    needs_reconcile = True
                else:
                    # 元信息未变化：对 SSH 轮询增加“内容差异”补偿，避免 mtime/size 分辨率不足导致漏同步。
                    if not deleted and getattr(endpoint, 'type', None) == 'ssh':
                        old_meta = state.get(key_meta, {}) or {}
                        other = 'b' if side == 'a' else 'a'
                        other_ep = self.endpoints.get(other)
                        other_meta = state.get(f"{other}_meta", {}) or {}
                        other_deleted = bool(state.get(f"{other}_deleted", False))
                        size = (meta or {}).get('size') or old_meta.get('size') or 0
                        if (
                            other_ep
                            and not other_deleted
                            and other_meta
                            and size
                            and size <= self._hash_check_max_size
                            and self._consume_hash_budget(hash_budget, units=2)
                        ):
                            remote_hash = self._compute_hash(endpoint, rel_path)
                            local_hash = self._compute_hash(other_ep, rel_path)
                            if remote_hash and local_hash and remote_hash != local_hash:
                                meta2 = dict(meta or {})
                                meta2['hash'] = remote_hash
                                state[key_meta] = meta2
                                state[key_deleted] = False
                                state[key_seen] = seen_at
                                needs_reconcile = True
                                info_message = f"检测到内容差异(元信息未变)，触发同步: {side} -> {other} | {rel_path}"
                            else:
                                # 仅补齐 hash，提升后续判断精度；不更新 seen_at，避免误触发同步。
                                if not old_meta.get('hash') and remote_hash and self._consume_hash_budget(hash_budget, units=0):
                                    old_meta2 = dict(old_meta)
                                    old_meta2['hash'] = remote_hash
                                    state[key_meta] = old_meta2
                                    self._state_cache[rel_path] = state
                                    self._save_state(rel_path, state)
                                    return
                        else:
                            return
                    return

            self._state_cache[rel_path] = state
            self._save_state(rel_path, state)

        if info_message:
            logger.info(info_message)
        if needs_reconcile:
            self._reconcile(rel_path)

    def _meta_changed(self, old_meta: Dict, new_meta: Optional[Dict]) -> bool:
        if not old_meta and not new_meta:
            return False
        if not old_meta or not new_meta:
            return True
        old_hash = old_meta.get('hash')
        new_hash = new_meta.get('hash')
        if old_hash and new_hash:
            return old_hash != new_hash
        return old_meta.get('size') != new_meta.get('size') or old_meta.get('mtime') != new_meta.get('mtime')

    def _compute_hash(self, endpoint, rel_path: str) -> Optional[str]:
        try:
            if endpoint.type == 'local':
                abs_path = endpoint._abs_path(rel_path)
                if not abs_path.exists():
                    return None
                if self.eol_normalize == 'keep' or not _is_text_path(rel_path):
                    return self._hash_file(abs_path)
                content = abs_path.read_bytes()
                content = _normalize_bytes(content, self.eol_normalize)
                return hashlib.new(self._hash_algo, content).hexdigest()
            else:
                content = endpoint.read_bytes(rel_path)
                if self.eol_normalize != 'keep' and _is_text_path(rel_path):
                    content = _normalize_bytes(content, self.eol_normalize)
                return hashlib.new(self._hash_algo, content).hexdigest()
        except Exception:
            return None

    def _hash_file(self, abs_path: Path) -> str:
        hasher = hashlib.new(self._hash_algo)
        with open(abs_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                hasher.update(chunk)
        return hasher.hexdigest()

    def _batch_sync_loop(self):
        """
        批量同步处理线程：收集短时间内的事件，然后批量执行同步
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        while not self._stop_event.is_set():
            # 等待有新事件或超时
            self._batch_event.wait(timeout=self._batch_delay)
            self._batch_event.clear()
            
            if self._stop_event.is_set():
                break
            
            # 再等一小段时间收集更多事件
            time.sleep(0.1)
            
            # 取出所有待同步的路径
            with self._batch_lock:
                if not self._batch_queue:
                    continue
                paths_to_sync = list(set(self._batch_queue))  # 去重
                self._batch_queue.clear()
            
            if not paths_to_sync:
                continue
            
            # 准备同步任务
            sync_tasks = []
            for rel_path in paths_to_sync:
                task_info = self._prepare_sync_task(rel_path)
                if task_info:
                    sync_tasks.append(task_info)
            
            if not sync_tasks:
                continue
            
            # 标记正在同步，暂停轮询
            self._syncing.set()
            
            try:
                logger.info(f"批量同步开始: {len(sync_tasks)} 个文件")
                start_time = time.time()
                
                # 并行执行同步（限制并发数）
                with ThreadPoolExecutor(max_workers=self._batch_max_parallel) as executor:
                    futures = {
                        executor.submit(self._sync_side, task['winner'], task['loser'], task['rel_path']): task
                        for task in sync_tasks
                    }
                    
                    completed = 0
                    failed = 0
                    for future in as_completed(futures):
                        try:
                            future.result()
                            completed += 1
                        except Exception as e:
                            failed += 1
                            task = futures[future]
                            logger.error(f"批量同步失败: {task['rel_path']} - {e}")
                
                elapsed = time.time() - start_time
                logger.info(f"批量同步完成: 成功 {completed}, 失败 {failed}, 耗时 {elapsed:.2f}s")
            finally:
                # 同步完成，恢复轮询
                self._syncing.clear()
    
    def _prepare_sync_task(self, rel_path: str) -> Optional[Dict]:
        """
        准备单个同步任务，返回同步所需的信息
        """
        if not self._init_done.is_set():
            return None
        with self._lock:
            state = self._state_cache.get(rel_path)
        if not state:
            return None

        last_sync = state.get('last_sync_at')
        a_changed = state.get('a_seen_at') and (not last_sync or state['a_seen_at'] > last_sync)
        b_changed = state.get('b_seen_at') and (not last_sync or state['b_seen_at'] > last_sync)

        if not a_changed and not b_changed:
            return None

        winner = None
        if a_changed and b_changed:
            if state['a_seen_at'] >= state['b_seen_at']:
                winner = 'a'
            else:
                winner = 'b'
        elif a_changed:
            winner = 'a'
        elif b_changed:
            winner = 'b'

        loser = 'b' if winner == 'a' else 'a'
        return {'winner': winner, 'loser': loser, 'rel_path': rel_path}
    
    def _reconcile(self, rel_path: str):
        """
        将文件加入批量同步队列，而不是立即同步
        """
        if not self._init_done.is_set():
            return
        
        with self._batch_lock:
            if rel_path not in self._batch_queue:
                self._batch_queue.append(rel_path)
        
        # 通知批量处理线程有新任务
        self._batch_event.set()

    def _sync_side(self, winner: str, loser: str, rel_path: str, stats: Optional[Dict] = None):
        with self._lock:
            state = self._state_cache.get(rel_path, {})
            winner_deleted = state.get(f"{winner}_deleted", False)
            winner_meta = state.get(f"{winner}_meta", {})
            loser_meta = state.get(f"{loser}_meta", {})
            loser_deleted = state.get(f"{loser}_deleted", False)

        winner_ep = self.endpoints[winner]
        loser_ep = self.endpoints[loser]
        now = datetime.now()
        ts = now.strftime('%Y%m%d_%H%M%S')

        try:
            logger.info(f"开始同步: {winner} -> {loser} | {rel_path}")
            if winner_deleted:
                if not loser_deleted and loser_meta:
                    loser_ep.move_to_trash(rel_path, ts)
                    self._mark_suppressed(loser, rel_path)
                new_loser_meta = {}
                new_loser_deleted = True
            else:
                if loser_meta and not loser_deleted:
                    if self._meta_changed(loser_meta, winner_meta):
                        loser_ep.backup_file(rel_path, ts)
                self._copy_between(winner_ep, loser_ep, rel_path)
                self._mark_suppressed(loser, rel_path)
                new_loser_meta = loser_ep.get_meta(rel_path) or {}
                if new_loser_meta:
                    new_hash = self._compute_hash(loser_ep, rel_path)
                    if new_hash:
                        new_loser_meta['hash'] = new_hash
                new_loser_deleted = False

            with self._lock:
                state = self._state_cache.get(rel_path, {})
                state[f"{loser}_meta"] = new_loser_meta
                state[f"{loser}_deleted"] = new_loser_deleted
                state[f"{loser}_seen_at"] = now
                state['last_winner'] = winner
                state['last_sync_at'] = now
                self._state_cache[rel_path] = state
                self._save_state(rel_path, state)

            event_type = 'deleted' if winner_deleted else 'modified'
            with get_db() as db:
                create_log(db, {
                    'task_id': self.task_id,
                    'event_type': event_type,
                    'file_path': rel_path,
                    'dest_path': None,
                    'status': 'success',
                    'error_message': None
                })
            if stats is not None:
                stats['synced'] = stats.get('synced', 0) + 1
            logger.info(f"同步完成: {winner} -> {loser} | {rel_path}")
        except Exception as e:
            logger.error(f"同步失败: {rel_path} - {e}")
            with get_db() as db:
                create_log(db, {
                    'task_id': self.task_id,
                    'event_type': 'modified',
                    'file_path': rel_path,
                    'dest_path': None,
                    'status': 'failed',
                    'error_message': str(e)
                })
            if stats is not None:
                stats['failed'] = stats.get('failed', 0) + 1

    def _copy_between(self, src_ep, dst_ep, rel_path: str):
        if src_ep.type == 'local' and dst_ep.type == 'local':
            src_abs = src_ep._abs_path(rel_path)
            if self.eol_normalize == 'keep' or not _is_text_path(rel_path):
                dst_ep.copy_file(src_abs, rel_path)
            else:
                content = src_ep.read_bytes(rel_path)
                content = _normalize_bytes(content, self.eol_normalize)
                dst_ep.write_bytes(rel_path, content)
            return

        if src_ep.type == 'local' and dst_ep.type == 'ssh':
            src_abs = src_ep._abs_path(rel_path)
            if self.eol_normalize == 'keep' or not _is_text_path(rel_path):
                dst_ep.upload_file(src_abs, rel_path)
            else:
                content = src_ep.read_bytes(rel_path)
                content = _normalize_bytes(content, self.eol_normalize)
                dst_ep.write_bytes(rel_path, content)
            return

        if src_ep.type == 'ssh' and dst_ep.type == 'local':
            if self.eol_normalize == 'keep' or not _is_text_path(rel_path):
                dest_abs = dst_ep._abs_path(rel_path)
                ensure_parent_dir(dest_abs)
                src_ep.download_file(rel_path, dest_abs)
            else:
                content = src_ep.read_bytes(rel_path)
                content = _normalize_bytes(content, self.eol_normalize)
                dst_ep.write_bytes(rel_path, content)
            return

        if src_ep.type == 'ssh' and dst_ep.type == 'ssh':
            content = src_ep.read_bytes(rel_path)
            if self.eol_normalize != 'keep' and _is_text_path(rel_path):
                content = _normalize_bytes(content, self.eol_normalize)
            dst_ep.write_bytes(rel_path, content)

    def _initial_sync(self, stats: Optional[Dict] = None):
        a_ep = self.endpoints['a']
        b_ep = self.endpoints['b']
        a_files = a_ep.list_files()
        if self._stop_event.is_set():
            return
        b_files = b_ep.list_files()
        now = datetime.now()

        all_paths = set(a_files.keys()) | set(b_files.keys())
        for rel_path in all_paths:
            if self._stop_event.is_set():
                return
            a_meta = a_files.get(rel_path)
            b_meta = b_files.get(rel_path)
            if a_meta and not b_meta:
                state = {
                    'a_meta': a_meta,
                    'b_meta': {},
                    'a_deleted': False,
                    'b_deleted': True,
                    'a_seen_at': now,
                    'b_seen_at': None,
                    'last_winner': None,
                    'last_sync_at': None
                }
                with self._lock:
                    self._state_cache[rel_path] = state
                    self._save_state(rel_path, state)
                self._sync_side('a', 'b', rel_path, stats=stats)
            elif b_meta and not a_meta:
                state = {
                    'a_meta': {},
                    'b_meta': b_meta,
                    'a_deleted': True,
                    'b_deleted': False,
                    'a_seen_at': None,
                    'b_seen_at': now,
                    'last_winner': None,
                    'last_sync_at': None
                }
                with self._lock:
                    self._state_cache[rel_path] = state
                    self._save_state(rel_path, state)
                self._sync_side('b', 'a', rel_path, stats=stats)
            elif a_meta and b_meta:
                # 性能优化：首次基线同步不对全量文件做 hash（大仓库会极慢，且会阻塞启动/请求）
                # 后续变更由 watcher/轮询触发，再按需 hash 精确判断。
                state = {
                    'a_meta': a_meta,
                    'b_meta': b_meta,
                    'a_deleted': False,
                    'b_deleted': False,
                    'a_seen_at': now,
                    'b_seen_at': now,
                    'last_winner': None,
                    'last_sync_at': now
                }
                with self._lock:
                    self._state_cache[rel_path] = state
                    self._save_state(rel_path, state)

    def sync_all(self, force: bool = False) -> dict:
        stats = {'synced': 0, 'skipped': 0, 'failed': 0}
        self._initial_sync(stats=stats)
        return stats
