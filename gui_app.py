
import os
import sys
import threading
import time
import socket
import uvicorn
import webview
import pystray
from PIL import Image
from multiprocessing import Process, freeze_support

# 将当前目录添加到 sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

from backend.app import app
from backend.utils.logger import logger

# 全局变量
window = None
tray_icon = None
server_port = None
is_exiting = False

def get_free_port():
    """获取一个空闲端口"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        _, port = s.getsockname()
        return port

def start_server(port):
    """启动后端服务"""
    # 禁用 uvicorn 的控制台日志，避免干扰
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="error")

def check_server_ready(port):
    """检查服务器是否就绪，然后跳转"""
    target_url = f"http://127.0.0.1:{port}"
    
    # 轮询等待端口响应
    start_time = time.time()
    while time.time() - start_time < 30: # 最多等待30秒
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                if s.connect_ex(('127.0.0.1', port)) == 0:
                    # 服务器已就绪，稍微停一下确保 app 加载完毕
                    time.sleep(1)
                    if window:
                        # 核心：在主线程中加载新 URL
                        # pywebview 的 load_url 是线程安全的（在大多数平台上）
                        webview.windows[0].load_url(target_url)
                    return
        except:
            pass
        time.sleep(0.5)

def on_window_closing():
    """拦截窗口关闭事件"""
    global is_exiting
    if is_exiting:
        return True # 允许关闭
    
    # 隐藏窗口而不是关闭
    if window:
        window.hide()
    
    # 显示提示气泡
    if tray_icon:
        tray_icon.notify("Tongbu Sync 已最小化到托盘运行", "后台运行中")
        
    return False # 阻止窗口关闭

def restore_window(icon, item):
    """从托盘恢复窗口"""
    if window:
        window.show()
        window.restore()

def quit_app(icon, item):
    """完全退出应用"""
    global is_exiting
    is_exiting = True
    
    # 停止托盘
    icon.stop()
    
    # 关闭 Webview 窗口
    if window:
        window.destroy()
        
    # Python 进程会在所有非 daemon 线程结束时退出

def resource_path(relative_path):
    """获取资源的绝对路径，兼容开发和PyInstaller打包环境"""
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包后的路径
        base_path = sys._MEIPASS
    else:
        # 开发环境路径
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

def setup_tray():
    """设置系统托盘"""
    global tray_icon
    
    # 使用 resource_path 查找图标
    icon_path = resource_path("icon.ico")
    
    # 尝试加载图标
    image = None
    if os.path.exists(icon_path):
        try:
            image = Image.open(icon_path)
        except Exception as e:
            logger.error(f"加载托盘图标失败: {e}")
    
    if image is None:
        # 如果加载失败或文件不存在，生成一个简单的图标
        image = Image.new('RGB', (64, 64), color = (73, 109, 137))
    
    menu = pystray.Menu(
        pystray.MenuItem("打开界面", restore_window, default=True),
        pystray.MenuItem("退出", quit_app)
    )
    
    tray_icon = pystray.Icon("TongbuSync", image, "双向文件同步助手", menu)
    tray_icon.run()

def main():
    global window, server_port
    
    freeze_support()
    
    # 1. 获取端口
    server_port = get_free_port()
    
    # 2. 启动各种后台线程
    
    # 后端服务线程
    t_server = threading.Thread(target=start_server, args=(server_port,), daemon=True)
    t_server.start()
    
    # 检查就绪线程 (用于从 Loading页 跳转到 主页)
    t_check = threading.Thread(target=check_server_ready, args=(server_port,), daemon=True)
    t_check.start()
    
    # 托盘线程 (pystray 需要在某些平台上运行在主线程，但在 Windows 上通常可以在子线程)
    # 为了避免与 pywebview 的主线程冲突，我们将托盘放在子线程
    t_tray = threading.Thread(target=setup_tray, daemon=True)
    t_tray.start()
    
    # 3. 准备 Loading 页面路径
    if getattr(sys, 'frozen', False):
        # 打包后，资源在 _internal/frontend 下
        base_path = os.path.join(sys._MEIPASS, 'frontend')
    else:
        # 开发模式
        base_path = os.path.join(current_dir, 'frontend')
        
    loading_file = os.path.join(base_path, 'loading.html')
    if not os.path.exists(loading_file):
        # 如果找不到 loading 文件，就先显示一个简单的 html 文本
        loading_url = "data:text/html,<h1>Loading...</h1>"
    else:
        loading_url = f"file://{os.path.abspath(loading_file)}"

    # 4. 创建窗口
    window = webview.create_window(
        title="Tongbu - 双向文件同步助手",
        url=loading_url, # 初始显示 Loading
        width=1200,
        height=800,
        min_size=(800, 600),
        resizable=True
    )
    
    # 绑定关闭事件
    window.events.closing += on_window_closing
    
    # 5. 启动 GUI (必须在主线程)
    webview.start(debug=False)

if __name__ == '__main__':
    main()
