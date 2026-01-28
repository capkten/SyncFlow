"""
文件同步助手 - 同步引擎核心模块
"""

import os
import shutil
import time
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Dict, Any, Callable

from backend.core.file_watcher import FileWatcher
from backend.core.eol_normalizer import normalize_line_endings, is_text_file
from backend.utils.logger import logger


class BaseSyncEngine(ABC):
    """
    同步引擎抽象基类
    
    定义同步引擎的标准接口，所有具体的同步实现（本地、SSH等）
    都必须继承此类并实现核心同步逻辑。
    """
    
    def __init__(self, task_config: Dict[str, Any]):
        """
        初始化同步引擎
        
        Args:
            task_config: 任务配置字典，包含源路径、目标路径、排除规则等
        """
        self.config = task_config
        self.name = task_config.get('name', '未命名任务')
        self.source_path = Path(task_config['source_path'])
        self.target_config = task_config['target']
        self.eol_normalize = task_config.get('eol_normalize', 'lf')
        self.exclude_patterns = task_config.get('exclude_patterns', [])
        self.file_extensions = task_config.get('file_extensions', [])
        self._stop_event = threading.Event()
        
        self.watcher: Optional[FileWatcher] = None
        self.is_running = False
        
    def start(self):
        """启动同步任务"""
        if self.is_running:
            logger.warning(f"任务 '{self.name}' 已在运行中")
            return
        self._stop_event.clear()

        # 检查源目录是否存在
        if not self.source_path.exists():
            logger.error(f"源目录不存在: {self.source_path}")
            return

        # 初始化文件监控器
        self.watcher = FileWatcher(
            watch_path=str(self.source_path),
            on_change=self._on_file_change,
            exclude_patterns=self.exclude_patterns,
            file_extensions=self.file_extensions
        )
        
        try:
            self.watcher.start()
            self.is_running = True
            logger.info(f"任务 '{self.name}' 已启动 - 监控目录: {self.source_path}")
        except Exception as e:
            logger.error(f"任务 '{self.name}' 启动失败: {e}")
            self.is_running = False

    def stop(self):
        """停止同步任务"""
        if not self.is_running:
            return
        self._stop_event.set()
            
        if self.watcher:
            self.watcher.stop()
            
        self.is_running = False
        logger.info(f"任务 '{self.name}' 已停止")

    def should_stop(self) -> bool:
        return self._stop_event.is_set()

    def _on_file_change(self, event_type: str, src_path: str, dest_path: str):
        """
        文件变化回调函数
        
        Args:
            event_type: 事件类型 ('created', 'modified', 'deleted', 'moved')
            src_path: 源文件路径
            dest_path: 目标文件路径（仅 moved 事件有效）
        """
        try:
            # 计算相对路径
            rel_path = Path(src_path).relative_to(self.source_path)
            
            logger.info(f"[{self.name}] 检测到变化: {event_type} - {rel_path}")
            
            # 调用具体实现的同步方法
            self.sync_file(event_type, str(rel_path), src_path, dest_path)
            
        except Exception as e:
            logger.error(f"[{self.name}] 处理文件事件失败: {e}")

    @abstractmethod
    def sync_file(self, event_type: str, rel_path: str, abs_src_path: str, abs_dest_path: str) -> bool:
        """
        执行单个文件的同步
        
        Args:
            event_type: 事件类型
            rel_path: 相对路径
            abs_src_path: 源文件绝对路径
            abs_dest_path: 目标文件绝对路径（仅 moved 有效）
        """
        pass

    @abstractmethod
    def sync_all(self, force: bool = False, callback: Optional[Callable[[str, str, str, Optional[str]], None]] = None) -> dict:
        """
        执行全量同步
        
        Args:
            force: 是否强制同步所有文件（忽略哈希比对）
            callback: 同步回调函数 (status, rel_path, src_path, error_msg)
            
        Returns:
            统计信息字典 {'synced': int, 'skipped': int, 'failed': int}
        """
        pass


class LocalSyncEngine(BaseSyncEngine):
    """
    本地同步引擎
    
    实现本地目录之间的文件同步。
    """
    
    def __init__(self, task_config: Dict[str, Any]):
        super().__init__(task_config)
        self.target_root = Path(self.target_config['path'])
        
        # 确保目标根目录存在
        if not self.target_root.exists():
            try:
                self.target_root.mkdir(parents=True, exist_ok=True)
                logger.info(f"创建目标目录: {self.target_root}")
            except Exception as e:
                logger.error(f"创建目标目录失败: {e}")

    def sync_file(self, event_type: str, rel_path: str, abs_src_path: str, abs_dest_path: str) -> bool:
        """实现本地文件同步逻辑"""
        if self.should_stop():
            return False
        target_file = self.target_root / rel_path
        
        if event_type == 'deleted':
            self._handle_delete(target_file)
        elif event_type == 'moved':
            rel_dest = Path(abs_dest_path).relative_to(self.source_path)
            target_dest = self.target_root / rel_dest
            self._handle_move(target_file, target_dest)
        else:
            self._handle_copy(abs_src_path, target_file)
        return True

    def _handle_copy(self, src: str, dest: Path):
        """处理文件复制（包含换行符处理）"""
        # 确保目标父目录存在
        dest.parent.mkdir(parents=True, exist_ok=True)
        
        src_path = Path(src)
        
        # 检查是否需要统一换行符
        need_normalize = self.eol_normalize != 'keep' and is_text_file(src_path)
        
        if need_normalize:
            # 读取内容并转换
            logger.debug(f"正在同步文本文件 (EOL: {self.eol_normalize}): {src}")
            content = normalize_line_endings(
                src_path, 
                target=self.eol_normalize, 
                in_place=False
            )
            
            # 写入目标文件
            with open(dest, 'wb') as f:
                f.write(content)
            
            # 尝试复制权限和时间戳（虽然时间戳会被修改覆盖，但权限保留）
            try:
                shutil.copymode(src, dest)
            except Exception:
                pass
        else:
            # 二进制文件或保持原样，直接复制
            logger.debug(f"正在复制文件: {src}")
            shutil.copy2(src, dest)
            
        logger.info(f"✓ 同步成功: {dest.name}")

    def _handle_delete(self, target: Path):
        """处理文件删除"""
        if target.exists():
            target.unlink()
            logger.info(f"🗑️ 删除成功: {target.name}")
        else:
            logger.debug(f"文件不存在，跳过删除: {target}")

    def _handle_move(self, src_target: Path, dest_target: Path):
        """处理文件移动"""
        # 如果源目标文件不存在，可能是已经被删除了，尝试直接复制新位置
        if not src_target.exists():
            logger.warning(f"移动源文件不存在: {src_target}，将忽略移动操作")
            return
            
        # 确保目标目录存在
        dest_target.parent.mkdir(parents=True, exist_ok=True)
        
        # 移动文件
        shutil.move(str(src_target), str(dest_target))
        logger.info(f"🔄 移动成功: {src_target.name} -> {dest_target.name}")

    def sync_all(self, force: bool = False, callback: Optional[Callable[[str, str, str, Optional[str]], None]] = None) -> dict:
        """
        执行全量同步（本地）
        
        遍历源目录下的所有文件，逐一同步到目标目录
        """
        from backend.utils.file_utils import should_exclude, should_include_extension
        
        stats = {'synced': 0, 'skipped': 0, 'failed': 0}
        
        logger.info(f"[{self.name}] 开始全量同步: {self.source_path} -> {self.target_root}")
        
        # 遍历源目录所有文件
        for root, dirs, files in os.walk(self.source_path):
            if self.should_stop():
                logger.info(f"[{self.name}] 同步已取消")
                stats['aborted'] = True
                break
            # 过滤目录
            dirs[:] = [d for d in dirs if not should_exclude(Path(root) / d, self.exclude_patterns)]
            
            for filename in files:
                if self.should_stop():
                    logger.info(f"[{self.name}] 同步已取消")
                    stats['aborted'] = True
                    break
                src_file = Path(root) / filename
                rel_path = src_file.relative_to(self.source_path)
                
                # 检查排除规则
                if should_exclude(rel_path, self.exclude_patterns):
                    stats['skipped'] += 1
                    continue
                
                # 检查文件扩展名
                if not should_include_extension(src_file, self.file_extensions):
                    stats['skipped'] += 1
                    continue
                
                # 同步文件
                target_file = self.target_root / rel_path
                try:
                    self._handle_copy(str(src_file), target_file)
                    stats['synced'] += 1
                    if callback:
                        callback('success', str(rel_path), str(src_file), None)
                except Exception as e:
                    logger.error(f"同步失败: {rel_path} - {e}")
                    stats['failed'] += 1
                    if callback:
                        callback('failed', str(rel_path), str(src_file), str(e))
        
        logger.info(f"[{self.name}] 全量同步完成 - 成功: {stats['synced']}, 跳过: {stats['skipped']}, 失败: {stats['failed']}")
        return stats


class SshSyncEngine(BaseSyncEngine):
    """
    SSH 远程同步引擎
    
    通过 SSH/SFTP 协议将本地文件同步到远程服务器。
    """
    
    def __init__(self, task_config: Dict[str, Any]):
        super().__init__(task_config)
        
        # 初始化 SSH 传输客户端
        target = self.target_config
        self.transfer = None
        
        try:
            from backend.core.transfer import SSHTransfer
            self.transfer = SSHTransfer(
                host=target['host'],
                port=target.get('port', 22),
                username=target['username'],
                password=target.get('password'),
                key_filename=target.get('ssh_key_path')
            )
        except ImportError:
            logger.error("无法导入 SSHTransfer，请检查依赖")
            
        self.remote_root = target['path']

    def connect(self) -> bool:
        """
        建立 SSH/SFTP 连接（不启动文件监控）。

        Returns:
            是否连接成功
        """
        if not self.transfer:
            logger.error("无法初始化 SSH 传输模块，无法连接")
            return False

        try:
            self.transfer.connect()
            # 检查远程根目录是否存在
            if not self.transfer.exists(self.remote_root):
                self.transfer.mkdir_p(self.remote_root)
            return True
        except Exception as e:
            logger.error(f"SSH 连接失败: {e}")
            return False

    def start(self):
        """启动前先建立连接"""
        if not self.connect():
            return
                
        super().start()

    def stop(self):
        """停止后关闭连接"""
        super().stop()
        if self.transfer:
            self.transfer.close()

    def sync_file(self, event_type: str, rel_path: str, abs_src_path: str, abs_dest_path: str) -> bool:
        """实现远程文件同步逻辑"""
        if not self.transfer:
            raise RuntimeError("SSH 未连接，无法同步")
        if self.should_stop():
            return False
        self.transfer.ensure_connected()

        # 构造远程路径 (使用 forward slash，即使是在 Windows 上运行)
        # pathlib 在 Windows 上会使用反斜杠，需转换为正斜杠
        remote_rel_path = rel_path.replace('\\', '/')
        remote_target = f"{self.remote_root.rstrip('/')}/{remote_rel_path}"
        
        try:
            if event_type == 'deleted':
                self.transfer.delete_file(remote_target)
                logger.info(f"🗑️ 远程删除成功: {remote_rel_path}")
                
            elif event_type == 'moved':
                # 计算移动后的远程路径
                rel_dest = str(Path(abs_dest_path).relative_to(self.source_path)).replace('\\', '/')
                remote_dest = f"{self.remote_root.rstrip('/')}/{rel_dest}"
                
                try:
                    self.transfer.move_file(remote_target, remote_dest)
                    logger.info(f"🔄 远程移动成功: {remote_rel_path} -> {rel_dest}")
                except Exception:
                    # 如果移动失败（例如跨文件系统），尝试先删后传
                    self.transfer.delete_file(remote_target)
                    self._handle_upload(abs_dest_path, remote_dest)
                    
            else:
                # created 或 modified
                self._handle_upload(abs_src_path, remote_target)
                
        except Exception as e:
            logger.error(f"[{self.name}] 远程同步失败 ({rel_path}): {e}")
            try:
                self.transfer.ensure_connected()
            except Exception as reconnect_error:
                logger.warning(f"SSH 重连失败: {reconnect_error}")
            raise
        return True

    def _handle_upload(self, src: str, remote_path: str):
        """处理文件上传（包含换行符处理）"""
        src_path = Path(src)
        
        # 检查是否需要统一换行符
        need_normalize = self.eol_normalize != 'keep' and is_text_file(src_path)
        
        if need_normalize:
            # 读取内容并转换
            logger.debug(f"正在同步文本文件 (EOL: {self.eol_normalize}): {src}")
            content = normalize_line_endings(
                src_path, 
                target=self.eol_normalize, 
                in_place=False
            )
            
            # 使用 BytesIO 包装内容上传
            from io import BytesIO
            file_obj = BytesIO(content)
            self.transfer.upload_file(file_obj, remote_path)
        else:
            # 二进制文件或保持原样，直接上传本地文件路径
            logger.debug(f"正在上传文件: {src}")
            self.transfer.upload_file(src, remote_path)
            
        logger.info(f"✓ 远程同步成功: {os.path.basename(remote_path)}")

    def sync_all(self, force: bool = False, callback: Optional[Callable[[str, str, str, Optional[str]], None]] = None) -> dict:
        """
        执行全量同步（SSH远程）
        
        遍历源目录下的所有文件，逐一上传到远程服务器
        """
        from backend.utils.file_utils import should_exclude, should_include_extension
        
        stats = {'synced': 0, 'skipped': 0, 'failed': 0}
        
        logger.info(f"[{self.name}] 开始全量同步: {self.source_path} -> {self.remote_root}")
        if self.transfer:
            self.transfer.ensure_connected()
        
        # 遍历源目录所有文件
        for root, dirs, files in os.walk(self.source_path):
            if self.should_stop():
                logger.info(f"[{self.name}] 同步已取消")
                stats['aborted'] = True
                break
            # 过滤目录
            dirs[:] = [d for d in dirs if not should_exclude(Path(root) / d, self.exclude_patterns)]
            
            for filename in files:
                if self.should_stop():
                    logger.info(f"[{self.name}] 同步已取消")
                    stats['aborted'] = True
                    break
                src_file = Path(root) / filename
                rel_path = src_file.relative_to(self.source_path)
                
                # 检查排除规则
                if should_exclude(rel_path, self.exclude_patterns):
                    stats['skipped'] += 1
                    continue
                
                # 检查文件扩展名
                if not should_include_extension(src_file, self.file_extensions):
                    stats['skipped'] += 1
                    continue
                
                # 构造远程路径
                remote_rel_path = str(rel_path).replace('\\', '/')
                remote_target = f"{self.remote_root.rstrip('/')}/{remote_rel_path}"
                
                # 同步文件
                try:
                    self._handle_upload(str(src_file), remote_target)
                    stats['synced'] += 1
                    if callback:
                        callback('success', str(rel_path), str(src_file), None)
                except Exception as e:
                    logger.error(f"远程同步失败: {rel_path} - {e}")
                    stats['failed'] += 1
                    try:
                        self.transfer.ensure_connected()
                    except Exception:
                        pass
                    if callback:
                        callback('failed', str(rel_path), str(src_file), str(e))
        
        logger.info(f"[{self.name}] 全量同步完成 - 成功: {stats['synced']}, 跳过: {stats['skipped']}, 失败: {stats['failed']}")
        return stats
