<div align="center">
  <img src="icon.ico" alt="SyncFlow Logo" width="120" height="120">
  <h1>SyncFlow (同步�?</h1>
  
  <p>
    <strong>A Modern, Real-time Bidirectional File Synchronization Tool</strong><br>
    现代化、实时的文件双向同步工具
  </p>

  <p>
    <a href="#english">English</a> �?<a href="#chinese">中文</a>
  </p>

  <img src="https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/Vue.js-3.x-4FC08D?style=flat-square&logo=vue.js&logoColor=white" />
  <img src="https://img.shields.io/badge/FastAPI-0.109+-009688?style=flat-square&logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/Platform-Windows%20%7C%20Linux-lightgrey?style=flat-square" />
  <br><br>
</div>

<hr>

<a name="english"></a>
## 🇬🇧 English Introduction

**SyncFlow** is a powerful file synchronization tool designed for seamless developer workflows. While supporting standard local-to-local synchronization, its core strength lies in **Local-to-Remote (SSH/SFTP)** synchronization with real-time capabilities.

Unlike traditional tools that rely heavily on slow polling, SyncFlow integrates **Remote Inotify** support. It runs a lightweight listener on your remote Linux server to push file change events instantly, ensuring your local and remote environments are always in sync with millisecond latency.

### �?Key Features

*   **🔄 Bidirectional & One-way Sync**: Flexible synchronization modes to fit your workflow.
*   **�?Real-time Detection**:
    *   **Local**: Uses `watchdog` to monitor file system events.
    *   **Remote**: Uses `inotifywait` (via SSH) for instant updates on Linux servers.
    *   **Smart Polling**: Automatic fallback to optimized polling (1.5s interval) if inotify is unavailable.
*   **🚀 High Performance**:
    *   **Batch Processing**: Aggregates rapid file changes to prevent sync storms.
    *   **Concurrent Sync**: Multi-threaded transfer engine handles multiple files simultaneously.
*   **🖥�?Modern Desktop App**:
    *   Packaged as a native **Windows application** (no Python installation required).
    *   **System Tray** support for background running.
    *   Beautiful, responsive user interface built with **Vue 3** and **Element Plus**.
*   **🛡�?Robustness**:
    *   Trash can & Backup support.
    *   Intelligent conflict resolution.
    *   Automatic network reconnection.

---

### 📥 Usage

#### Method 1: Desktop Application (Recommended for Windows)
1. Download the latest release package.
2. Unzip and run `TongbuSync.exe`.
3. The app will minimize to the system tray. Click the tray icon to open the UI.

#### Method 2: Running from Source
1. **Prerequisites**: Python 3.10+, Node.js (optional, for frontend dev).
2. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
3. **Run the GUI**:
   ```bash
   python gui_app.py
   ```
   Or run the backend server only (Headless mode):
   ```bash
   python backend/app.py
   ```

### 🔨 Building from Source
To package the application into a standalone `.exe` file:
```bash
pip install pyinstaller pywebview pystray Pillow
python -m PyInstaller --clean -y TongbuSync.spec
```
The output file will be in `dist/TongbuSync/`.

### 🐧 Remote Server Setup (Optional)
For the best experience, install `inotify-tools` on your remote Linux server to enable real-time pushing:
*   **Ubuntu/Debian**: `sudo apt-get install inotify-tools`
*   **CentOS/RHEL**: `sudo yum install inotify-tools`

---

<br>
<hr>
<br>

<a name="chinese"></a>
## 🇨🇳 中文介绍

**SyncFlow (同步助手)** 是一款专为开发者打造的现代化文件同步工具。它不仅支持本地文件夹之间的同步，更专注于高效的 **本地 <-> 远程 (SSH/SFTP)** 开发场景�?

与传统依赖低效轮询的工具不同，Tongbu Sync 实现�?**远程 Inotify 集成**。它通过 SSH 在远�?Linux 服务器上运行轻量级监听器，实时推送文件变更事件，实现了毫秒级的双向同步体验�?

### �?核心特�?

*   **🔄 双向与单向同�?*: 支持镜像备份或双向实时协作模式�?
*   **�?极致实时�?*:
    *   **本地监控**: 基于 `watchdog` 系统级文件监控�?
    *   **远程监控**: 优先使用 `inotifywait` (SSH) 实时捕获远程变更�?
    *   **智能兜底**: 若远程不支持 inotify，自动降级为高频轮询�?.5秒间隔，同步时自动避让）�?
*   **🚀 高性能引擎**:
    *   **批量处理**: 智能合并短时间内的多次修改，避免重复同步�?
    *   **并发传输**: 多线程传输引擎，海量小文件同步更迅速�?
*   **🖥�?原生桌面体验**:
    *   提供独立�?**Windows 桌面应用** (无需安装 Python)�?
    *   支持 **系统托盘** 最小化，后台静默运行�?
    *   基于 **Vue 3 + Element Plus** 的现代化管理界面�?
*   **🛡�?安全可靠**:
    *   支持回收站和版本备份，防止误删�?
    *   断网自动重连与错误重试机制�?

---

### 📥 使用指南

#### 方式一：直接运行桌面版 (Windows 推荐)
1. 下载最新发布的压缩包�?
2. 解压后直接双击运�?`TongbuSync.exe`�?
3. 程序启动后会显示 Loading 动画，并在系统托盘显示图标�?

#### 方式二：源码运行
1. **环境准备**: Python 3.10+�?
2. **安装依赖**:
   ```bash
   pip install -r requirements.txt
   ```
3. **启动应用**:
   ```bash
   # 启动桌面�?(带独立窗�?
   python gui_app.py
   
   # 或仅启动 Web 后端 (浏览器访�?http://localhost:8888)
   python backend/app.py
   ```

### 🔨 打包构建
如果您想自己构建 Windows 可执行文件：
```bash
# 安装打包工具
pip install pyinstaller pywebview pystray Pillow

# 执行打包
python -m PyInstaller --clean -y TongbuSync.spec
```
构建完成后，可执行文件位�?`dist/TongbuSync/` 目录下�?

### 🐧 远程服务器配�?(可�?
为了获得最佳的远程同步体验，建议在您的 Linux 服务器上安装 `inotify-tools`�?
*   **Ubuntu/Debian**: `sudo apt-get install inotify-tools`
*   **CentOS/RHEL**: `sudo yum install inotify-tools`
*   如果未安装，软件会自动回退到轮询模式，依然可用，但延迟稍高 (�?1-2 �?�?

---

## 📜 License

This project is licensed under the MIT License.
