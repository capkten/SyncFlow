# 文件同步助手

一个轻量级的跨平台文件同步工具，支持 Windows 和 Linux 之间的实时文件同步。

## ✨ 主要功能

- 🔄 **实时监控**：基于 watchdog 实现文件系统事件监控
- 🌐 **多种传输方式**：支持本地同步和 SSH 远程同步
- 📝 **换行符统一**：自动处理 Windows/Linux 换行符差异（CRLF ↔ LF）
- 🎯 **智能过滤**：支持排除规则和文件扩展名过滤
- 🖥️ **Web 管理界面**：提供友好的任务管理和日志查看界面
- 📊 **实时日志**：WebSocket 实时推送同步状态

## 🚀 快速开始

### 1. 安装依赖

```bash
# 创建虚拟环境（推荐）
python -m venv venv
source venv/bin/activate  # Linux
# 或
venv\Scripts\activate     # Windows

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置同步任务

复制配置示例文件：
```bash
cp config.example.yaml config.yaml
```

编辑 `config.yaml`，配置您的同步任务：

```yaml
global:
  log_level: INFO
  web_port: 8888

sync_tasks:
  - name: "我的项目同步"
    source_path: "D:/projects/my-app"
    target:
      type: "ssh"
      host: "192.168.1.100"
      port: 22
      username: "user"
      password: "your_password"
      path: "/home/user/my-app"
    enabled: true
    auto_start: true
    eol_normalize: "lf"         # 统一为 LF 换行符
    exclude_patterns:
      - "*.pyc"
      - "__pycache__"
      - ".git"
      - "node_modules"
```

### 3. 启动服务

```bash
python backend/app.py
```

### 4. 访问 Web 界面

打开浏览器访问：`http://localhost:8888`

## 📖 核心特性说明

### 换行符统一处理 ⭐

本工具的一大特色是自动处理 Windows 和 Linux 之间的换行符差异：

- **问题**：Windows 使用 CRLF (`\r\n`)，Linux 使用 LF (`\n`)，导致 Git 频繁报告文件修改
- **解决**：同步前自动统一换行符，支持三种模式：
  - `lf`：统一为 Unix 风格（推荐）
  - `crlf`：统一为 Windows 风格
  - `keep`：保持原样不处理

### 多文件夹同步

支持配置多个独立的同步任务，每个任务可以：
- 设置不同的源目录和目标目录
- 使用不同的传输方式（本地/SSH）
- 配置不同的排除规则和换行符策略

### 智能排除规则

支持 glob 模式的排除规则：
```yaml
exclude_patterns:
  - "*.pyc"           # 排除所有 .pyc 文件
  - "__pycache__"     # 排除 __pycache__ 目录
  - ".git"            # 排除 .git 目录
  - "*.log"           # 排除日志文件
```

## 🛠️ 技术栈

- **后端**：Python + FastAPI
- **文件监控**：watchdog
- **SSH 传输**：paramiko
- **数据库**：SQLite + SQLAlchemy
- **前端**：Vue.js 3 + Element Plus
- **日志**：loguru

## 📂 项目结构

```
文件同步助手/
├── backend/                # 后端服务
│   ├── app.py             # 主应用入口
│   ├── config/            # 配置模块
│   ├── core/              # 核心功能
│   │   ├── eol_normalizer.py  # 换行符处理 ⭐
│   │   ├── file_watcher.py    # 文件监控
│   │   └── sync_engine.py     # 同步引擎
│   ├── api/               # API 路由
│   └── utils/             # 工具函数
├── frontend/              # Web 前端界面
├── config.yaml            # 用户配置
└── requirements.txt       # Python 依赖
```

## 📝 开发进度

- [x] 换行符统一处理模块
- [x] 文件工具函数
- [x] 配置管理
- [x] 日志系统
- [ ] 文件监控（watchdog）
- [ ] 本地同步引擎
- [ ] SSH 远程传输
- [ ] FastAPI 后端 API
- [ ] Vue.js 前端界面
- [ ] WebSocket 实时日志

## ⚠️ 注意事项

1. **首次使用**：建议先在测试目录验证功能
2. **SSH 认证**：可使用密码或 SSH 密钥（密钥更安全）
3. **大文件同步**：首次同步大量文件可能需要较长时间
4. **网络要求**：SSH 模式需要目标主机开启 SSH 服务（端口22）

## 📄 许可证

MIT License

---

**文件同步助手** - 让跨平台开发更轻松 🚀
