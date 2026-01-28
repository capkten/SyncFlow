"""
文件同步助手 - SSH 传输模块

封装 Paramiko 客户端，提供 SSH/SFTP 连接管理和文件操作。
"""

import os
import stat
import time
import threading
from pathlib import Path
from typing import Optional, Union, BinaryIO, Iterator, Tuple

import paramiko
from paramiko import SSHClient, SFTPClient, AutoAddPolicy, RejectPolicy, WarningPolicy

from backend.utils.logger import logger


class SSHTransfer:
    """SSH 传输客户端"""
    
    def __init__(self, host, port, username, password=None, key_filename=None,
                 host_key_policy: Optional[str] = None, known_hosts_path: Optional[str] = None):
        self.host = host
        self.port = int(port)
        self.username = username
        self.password = password
        # 如果 key_filename 是空字符串，设为 None，避免 paramiko 报错
        self.key_filename = key_filename if key_filename else None
        if host_key_policy is None or known_hosts_path is None:
            try:
                from backend.config.settings import load_config
                config = load_config()
                if host_key_policy is None:
                    host_key_policy = config.global_.ssh_host_key_policy
                if known_hosts_path is None:
                    known_hosts_path = config.global_.ssh_known_hosts_path
            except Exception:
                pass
        self.host_key_policy = host_key_policy or 'reject'
        self.known_hosts_path = known_hosts_path
        
        self.ssh: Optional[SSHClient] = None
        self.sftp: Optional[SFTPClient] = None
        # Paramiko/SFTPClient 非线程安全：双向同步存在“轮询扫描线程”和“同步线程”并发访问同一连接的情况。
        # 用 RLock 确保同一连接上的 SFTP 操作不并发，避免卡死/无响应。
        self._io_lock = threading.RLock()
        
    def connect(self):
        """建立 SSH 和 SFTP 连接"""
        if self.ssh is not None:
            return

        try:
            self.ssh = SSHClient()
            if self.known_hosts_path:
                path = Path(self.known_hosts_path)
                if path.exists():
                    self.ssh.load_host_keys(str(path))
                else:
                    self.ssh.load_system_host_keys()
            else:
                self.ssh.load_system_host_keys()
            policy_map = {
                'auto': AutoAddPolicy(),
                'reject': RejectPolicy(),
                'warning': WarningPolicy()
            }
            policy = policy_map.get(self.host_key_policy, RejectPolicy())
            self.ssh.set_missing_host_key_policy(policy)
            
            logger.info(f"正在连接 SSH: {self.username}@{self.host}:{self.port}")
            self.ssh.connect(
                hostname=self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                key_filename=self.key_filename,
                timeout=10,
                banner_timeout=10
            )
            
            self.sftp = self.ssh.open_sftp()
            try:
                # 防止网络抖动时 SFTP 调用无期限阻塞
                self.sftp.get_channel().settimeout(30)
            except Exception:
                pass
            try:
                transport = self.ssh.get_transport()
                if transport:
                    transport.set_keepalive(30)
            except Exception as e:
                logger.debug(f"设置 SSH keepalive 失败: {e}")
            logger.info("SSH/SFTP 连接成功")
            if isinstance(policy, AutoAddPolicy) and self.known_hosts_path:
                path = Path(self.known_hosts_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                self.ssh.save_host_keys(str(path))
            
        except Exception as e:
            self.ssh = None
            self.sftp = None
            raise ConnectionError(f"SSH 连接失败: {e}")

    def close(self):
        """关闭连接"""
        if self.sftp:
            try:
                self.sftp.close()
            except Exception as e:
                logger.debug(f"SFTP 连接关闭失败: {e}")
            self.sftp = None
            
        if self.ssh:
            try:
                self.ssh.close()
            except Exception as e:
                logger.debug(f"SSH 连接关闭失败: {e}")
            self.ssh = None
            logger.info("SSH 连接已关闭")

    def ensure_connected(self):
        """确保连接可用，不可用则重连"""
        try:
            if self.ssh and self.ssh.get_transport() and self.ssh.get_transport().is_active():
                return
        except Exception as e:
            logger.debug(f"SSH 连接状态检查失败: {e}")
            
        logger.warning("SSH 连接已断开，尝试重连...")
        self.close()
        self.connect()

    def stat(self, remote_path: str):
        self.ensure_connected()
        with self._io_lock:
            return self.sftp.stat(remote_path)

    def iter_files(self, remote_root: str) -> Iterator[Tuple[str, paramiko.SFTPAttributes]]:
        self.ensure_connected()
        root = remote_root.rstrip('/')
        stack = [("", root)]
        while stack:
            rel_base, current = stack.pop()
            try:
                with self._io_lock:
                    entries = self.sftp.listdir_attr(current)
            except FileNotFoundError:
                continue
            for attr in entries:
                name = attr.filename
                rel_path = f"{rel_base}/{name}" if rel_base else name
                remote_path = f"{current}/{name}"
                if stat.S_ISDIR(attr.st_mode):
                    stack.append((rel_path, remote_path))
                else:
                    yield rel_path, attr

    def listdir_attr(self, remote_path: str):
        self.ensure_connected()
        try:
            with self._io_lock:
                return self.sftp.listdir_attr(remote_path)
        except FileNotFoundError:
            return []

    def remove_dir_recursive(self, remote_path: str):
        self.ensure_connected()
        try:
            with self._io_lock:
                entries = self.sftp.listdir_attr(remote_path)
        except FileNotFoundError:
            return
        for attr in entries:
            name = attr.filename
            child = f"{remote_path.rstrip('/')}/{name}"
            if stat.S_ISDIR(attr.st_mode):
                self.remove_dir_recursive(child)
            else:
                try:
                    with self._io_lock:
                        self.sftp.remove(child)
                except Exception:
                    pass
        try:
            with self._io_lock:
                self.sftp.rmdir(remote_path)
        except Exception:
            pass

    def read_file_bytes(self, remote_path: str) -> bytes:
        self.ensure_connected()
        with self._io_lock:
            with self.sftp.open(remote_path, 'rb') as f:
                return f.read()

    def write_file_bytes(self, remote_path: str, data: bytes):
        self.ensure_connected()
        remote_dir = os.path.dirname(remote_path)
        if remote_dir and not self.exists(remote_dir):
            self.mkdir_p(remote_dir)
        with self._io_lock:
            with self.sftp.open(remote_path, 'wb') as f:
                f.write(data)

    def download_file(self, remote_path: str, local_path: str):
        self.ensure_connected()
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        with self._io_lock:
            self.sftp.get(remote_path, local_path)

    def exists(self, remote_path: str) -> bool:
        """检查远程文件是否存在"""
        self.ensure_connected()
        try:
            with self._io_lock:
                self.sftp.stat(remote_path)
            return True
        except FileNotFoundError:
            return False

    def is_dir(self, remote_path: str) -> bool:
        """检查远程路径是否为目录"""
        self.ensure_connected()
        try:
            with self._io_lock:
                attr = self.sftp.stat(remote_path)
            return stat.S_ISDIR(attr.st_mode)
        except FileNotFoundError:
            return False

    def mkdir_p(self, remote_path: str):
        """递归创建远程目录"""
        self.ensure_connected()
        if remote_path == '/' or remote_path == '.':
            return
            
        if self.exists(remote_path):
            if self.is_dir(remote_path):
                return
            else:
                raise FileExistsError(f"{remote_path} 已存在且不是目录")
        
        parent = os.path.dirname(remote_path.rstrip('/'))
        if parent:
            self.mkdir_p(parent)
            
        try:
            with self._io_lock:
                self.sftp.mkdir(remote_path)
        except OSError:
            # 并发情况下可能刚被创建
            pass

    def upload_file(self, local_file: Union[str, BinaryIO], remote_path: str):
        """上传文件"""
        self.ensure_connected()
        
        # 确保目录存在
        remote_dir = os.path.dirname(remote_path)
        if not self.exists(remote_dir):
            self.mkdir_p(remote_dir)
            
        try:
            with self._io_lock:
                if isinstance(local_file, str):
                    self.sftp.put(local_file, remote_path)
                else:
                    # 传入的是文件对象（例如 BytesIO），直接 putfo
                    self.sftp.putfo(local_file, remote_path)
        except Exception as e:
            raise IOError(f"文件上传失败: {e}")

    def delete_file(self, remote_path: str):
        """删除远程文件"""
        self.ensure_connected()
        try:
            with self._io_lock:
                self.sftp.remove(remote_path)
        except FileNotFoundError:
            pass
        except Exception as e:
            raise IOError(f"文件删除失败: {e}")

    def move_file(self, remote_src: str, remote_dest: str):
        """移动/重命名远程文件"""
        self.ensure_connected()
        
        # 确保目标目录存在
        remote_dest_dir = os.path.dirname(remote_dest)
        if not self.exists(remote_dest_dir):
            self.mkdir_p(remote_dest_dir)
            
        try:
            # POSIX rename：如果目标存在，通常会覆盖，但 paramiko 行为依赖服务端
            # 为安全起见，先删目标（如果存在）
            try:
                with self._io_lock:
                    self.sftp.remove(remote_dest)
            except Exception as e:
                logger.debug(f"远程目标清理失败: {e}")
                
            with self._io_lock:
                self.sftp.rename(remote_src, remote_dest)
        except Exception as e:
            raise IOError(f"文件移动失败: {e}")
