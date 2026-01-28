"""
远程 inotify 监控模块

通过 SSH 在 Linux 服务器上运行 inotifywait 命令，
实时接收文件变化事件，替代低效的轮询方式。
"""

import threading
import re
import time
import io
from pathlib import Path
from typing import Callable, Optional, List
from datetime import datetime

from backend.utils.logger import logger


class RemoteInotifyWatcher:
    """
    远程 inotify 文件监控器
    
    通过 SSH 在远程 Linux 服务器上运行 inotifywait，
    实时获取文件变化事件。
    
    要求远程服务器安装 inotify-tools：
    - Ubuntu/Debian: sudo apt-get install inotify-tools
    - CentOS/RHEL: sudo yum install inotify-tools
    """
    
    # inotifywait 事件类型映射
    EVENT_MAP = {
        'CREATE': 'created',
        'MODIFY': 'modified',
        'DELETE': 'deleted',
        'MOVED_FROM': 'moved_from',
        'MOVED_TO': 'moved_to',
        'CLOSE_WRITE': 'modified',  # 写入完成，视为修改
        'ATTRIB': 'modified',  # 属性变化
    }
    
    def __init__(
        self,
        ssh_client,  # paramiko.SSHClient
        watch_path: str,
        on_change: Callable[[str, str], None],  # callback(event_type, rel_path)
        exclude_patterns: Optional[List[str]] = None
    ):
        """
        初始化远程 inotify 监控器
        
        Args:
            ssh_client: 已连接的 paramiko SSHClient
            watch_path: 要监控的远程目录路径
            on_change: 文件变化回调函数，参数为 (event_type, rel_path)
            exclude_patterns: 排除的文件模式列表
        """
        self.ssh_client = ssh_client
        self.watch_path = watch_path.rstrip('/')
        self.on_change = on_change
        self.exclude_patterns = exclude_patterns or []
        
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._channel = None
        self._inotify_available = None
    
    def check_inotify_available(self) -> bool:
        """检查远程服务器是否安装了 inotifywait"""
        if self._inotify_available is not None:
            return self._inotify_available
        
        try:
            stdin, stdout, stderr = self.ssh_client.exec_command(
                'which inotifywait',
                timeout=10
            )
            result = stdout.read().decode().strip()
            self._inotify_available = bool(result)
            
            if self._inotify_available:
                logger.info(f"远程服务器支持 inotify: {result}")
            else:
                logger.warning("远程服务器未安装 inotify-tools，将使用轮询模式")
                logger.info("安装命令: sudo apt-get install inotify-tools (Debian/Ubuntu)")
                logger.info("安装命令: sudo yum install inotify-tools (CentOS/RHEL)")
            
            return self._inotify_available
        except Exception as e:
            logger.error(f"检查 inotify 可用性失败: {e}")
            self._inotify_available = False
            return False
    
    def start(self) -> bool:
        """
        启动远程 inotify 监控
        
        Returns:
            True 如果成功启动，False 如果远程不支持 inotify
        """
        if self._running:
            return True
        
        if not self.check_inotify_available():
            return False
        
        self._stop_event.clear()
        self._running = True
        
        self._thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._thread.start()
        
        logger.info(f"远程 inotify 监控已启动: {self.watch_path}")
        return True
    
    def stop(self):
        """停止远程 inotify 监控"""
        if not self._running:
            return
        
        self._running = False
        self._stop_event.set()
        
        # 关闭 SSH channel 以中断阻塞的读取
        if self._channel:
            try:
                self._channel.close()
            except Exception:
                pass
            self._channel = None
        
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._thread = None
        
        logger.info(f"远程 inotify 监控已停止: {self.watch_path}")
    
    def _build_inotify_command(self) -> str:
        """构建 inotifywait 命令"""
        # 监控的事件类型
        events = "create,modify,delete,move,close_write"
        
        # 基础命令
        cmd_parts = [
            'inotifywait',
            '-m',  # monitor mode, 持续监控
            '-r',  # recursive, 递归监控子目录
            '--format', '"%w%f|%e"',  # 输出格式: 完整路径|事件类型
            '-e', events,
        ]
        
        # 添加排除模式
        for pattern in self.exclude_patterns:
            # 转换通配符模式为正则表达式
            regex_pattern = pattern.replace('.', r'\.').replace('*', '.*').replace('?', '.')
            cmd_parts.extend(['--exclude', f'"{regex_pattern}"'])
        
        # 排除常见的临时文件和目录
        default_excludes = [
            r'\.git/',
            r'\.svn/',
            r'__pycache__/',
            r'\.pyc$',
            r'\.swp$',
            r'\.tmp$',
            r'~$',
            r'\.tongbu_trash/',
            r'\.tongbu_backup/',
        ]
        for pattern in default_excludes:
            cmd_parts.extend(['--exclude', f'"{pattern}"'])
        
        # 添加监控路径
        cmd_parts.append(f'"{self.watch_path}"')
        
        return ' '.join(cmd_parts)
    
    def _watch_loop(self):
        """监控循环"""
        retry_count = 0
        max_retries = 5
        retry_delay = 5
        
        while self._running and not self._stop_event.is_set():
            try:
                cmd = self._build_inotify_command()
                logger.debug(f"执行远程 inotify 命令: {cmd}")
                
                # 使用 exec_command 获取 channel
                transport = self.ssh_client.get_transport()
                if not transport or not transport.is_active():
                    logger.warning("SSH 连接已断开，等待重连...")
                    time.sleep(retry_delay)
                    continue
                
                self._channel = transport.open_session()
                self._channel.exec_command(cmd)
                
                # 设置超时以便定期检查 stop 事件
                self._channel.settimeout(1.0)
                
                retry_count = 0  # 重置重试计数
                buffer = ""
                
                while self._running and not self._stop_event.is_set():
                    try:
                        # 尝试读取数据
                        if self._channel.recv_ready():
                            data = self._channel.recv(4096).decode('utf-8', errors='ignore')
                            if not data:
                                break
                            
                            buffer += data
                            
                            # 按行处理
                            while '\n' in buffer:
                                line, buffer = buffer.split('\n', 1)
                                line = line.strip().strip('"')
                                if line:
                                    self._process_event(line)
                        
                        # 检查 channel 是否关闭
                        if self._channel.exit_status_ready():
                            exit_status = self._channel.recv_exit_status()
                            if exit_status != 0:
                                logger.warning(f"inotifywait 退出，状态码: {exit_status}")
                            break
                        
                        time.sleep(0.1)
                        
                    except OSError:
                        # 超时，继续循环
                        continue
                    except Exception as e:
                        logger.error(f"读取 inotify 输出失败: {e}")
                        break
                
            except Exception as e:
                logger.error(f"inotify 监控异常: {e}")
                retry_count += 1
                
                if retry_count >= max_retries:
                    logger.error(f"inotify 监控重试次数超过上限 ({max_retries})，停止监控")
                    break
                
                logger.info(f"将在 {retry_delay} 秒后重试 ({retry_count}/{max_retries})...")
                self._stop_event.wait(retry_delay)
            
            finally:
                if self._channel:
                    try:
                        self._channel.close()
                    except Exception:
                        pass
                    self._channel = None
    
    def _process_event(self, line: str):
        """处理 inotifywait 输出的事件行"""
        try:
            # 格式: /path/to/file|EVENT1,EVENT2
            if '|' not in line:
                return
            
            full_path, events_str = line.rsplit('|', 1)
            
            # 计算相对路径
            if full_path.startswith(self.watch_path):
                rel_path = full_path[len(self.watch_path):].lstrip('/')
            else:
                rel_path = full_path
            
            if not rel_path:
                return
            
            # 解析事件类型
            events = events_str.split(',')
            
            # 处理移动事件
            if 'MOVED_FROM' in events:
                self.on_change('deleted', rel_path)
                return
            
            if 'MOVED_TO' in events:
                self.on_change('created', rel_path)
                return
            
            # 处理其他事件
            for event in events:
                event = event.strip()
                if event in self.EVENT_MAP:
                    mapped_event = self.EVENT_MAP[event]
                    # 避免重复触发
                    if mapped_event:
                        self.on_change(mapped_event, rel_path)
                        break
            
        except Exception as e:
            logger.error(f"处理 inotify 事件失败: {line} - {e}")


def test_inotify_available(ssh_client) -> bool:
    """
    测试远程服务器是否支持 inotify
    
    Args:
        ssh_client: paramiko.SSHClient 实例
        
    Returns:
        True 如果支持 inotify
    """
    try:
        stdin, stdout, stderr = ssh_client.exec_command('which inotifywait', timeout=10)
        return bool(stdout.read().decode().strip())
    except Exception:
        return False
