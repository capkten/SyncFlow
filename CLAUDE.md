# CLAUDE.md

此文件为 Claude Code (claude.ai/code) 在处理本仓库代码时提供指导。

## 语言与沟通
- **语言**：所有的沟通、文档、注释和 Docstrings 必须使用**中文**。
- **代码**：变量、函数、类名必须使用**英文**，并遵循 Python PEP 8 规范。
- **界面/输出**：用户可见的文本（CLI/Web 界面）必须使用**中文**。

## 构建与开发
- **环境搭建**：
  ```bash
  python -m venv venv
  # Windows: venv\Scripts\activate | Linux/macOS: source venv/bin/activate
  pip install -r requirements.txt
  # 复制 config.example.yaml 为 config.yaml (不要提交 config.yaml)
  ```
- **运行应用**：
  ```bash
  python backend/app.py
  ```
- **运行测试**：
  ```bash
  # 运行所有测试
  python tests/run_tests.py
  # 或使用 unittest
  python -m unittest discover -s tests -p "test_*.py"
  ```

## 架构概览
- **后端**：Python FastAPI (入口文件 `backend/app.py`)。
- **前端**：`frontend/` 目录下的静态资源，由后端提供服务。
- **数据**：SQLite 数据库 (`data/sync.db`) 和日志 (`logs/`) 为运行时产物（Git 已忽略）。
- **核心模块**：
  - `backend/core/`：包含文件监控、同步逻辑和换行符规范化处理。
  - `backend/config/`：配置加载 (`settings.py`)。
  - `backend/utils/`：通用工具函数。

## 代码规范
- **风格**：Python 使用 4 空格缩进。文件/函数使用 `snake_case`（蛇形命名），类使用 `PascalCase`（帕斯卡命名）。
- **范围**：保持改动聚焦。除非明确要求，否则避免无关的重构或批量格式化。
- **路径**：必须使用 `pathlib` 以确保 Windows/Linux 跨平台兼容性。
- **配置**：如果修改了 `config.yaml` 的结构，必须同步更新 `config.example.yaml`。

## 测试指南
- **要求**：新增功能和 Bug 修复必须包含测试。
- **隔离**：测试必须使用临时目录或临时数据库。**严禁**在测试中使用生产数据库 `data/sync.db`。
- **性能**：优先编写确定性的本地测试，避免依赖网络或远程主机的测试。

## Git 与提交规范
- **提交信息**：必须使用**中文**。格式：`主题：细节`（例如：`搭建项目框架：实现核心模块...`）。
- **分支命名**：建议使用 `feature/<描述>` 或 `fix/<描述>`。
- **安全**：**严禁**提交任何密钥（密码、Token）。敏感信息应放在 `config.yaml` 中（本地使用）。
