# Repository Guidelines

## Project Structure & Module Organization

- `backend/`: Python FastAPI 后端（同步引擎、文件监控、API、SQLite 模型）。
- `frontend/`: 前端静态资源（`frontend/index.html`, `frontend/static/`）。
- `tests/`: Python `unittest` 单元测试（命名 `test_*.py`）。
- 运行时目录（已在 `.gitignore` 中忽略）：`data/`（SQLite DB）、`logs/`（日志）。
- 配置：从 `config.example.yaml` 复制为 `config.yaml`（本地使用，勿提交）。

## Build, Test, and Development Commands

```powershell
# Windows: 创建并激活虚拟环境
python -m venv venv
venv\Scripts\activate

# Linux/macOS:
# python -m venv venv
# source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 生成本地配置
Copy-Item config.example.yaml config.yaml

# 启动服务（默认端口见 config.yaml）
python backend/app.py

# 健康检查（可选）
# curl http://localhost:8888/api/health
# Invoke-WebRequest -Uri http://localhost:8888/api/health -UseBasicParsing
```

## Language & Documentation

- 沟通与文档默认使用中文。
- 代码注释与 Docstrings 必须使用中文；标识符（变量/函数/类）使用英文并遵循通用风格（Python PEP 8）。
- UI/CLI 输出信息原则上使用中文。

## Coding Style & Naming Conventions

- Python：4 空格缩进；文件/函数 `snake_case`；类 `PascalCase`。
- 文件名建议使用英文，保证跨平台兼容性。
- 保持改动聚焦：避免“顺手重构/批量格式化”导致无关 diff（除非明确要求）。

## Architecture Overview

- 后端入口：`backend/app.py`；配置加载：`backend/config/settings.py`。
- 核心逻辑：`backend/core/`；数据模型：`backend/models/`；工具函数：`backend/utils/`。
- 前端为静态资源目录：`frontend/`（通常由后端提供页面与 API）。

## Testing Guidelines

```powershell
# 运行全部测试
python tests\run_tests.py

# 或 unittest discovery
python -m unittest discover -s tests -p "test_*.py"
```

- 新增功能/修复缺陷需同步补充测试；优先小而确定性的用例（避免依赖网络与真实远端机器）。
- 测试应使用临时目录/临时 DB（不要复用仓库内 `data/sync.db`），避免与本地运行实例互相影响。

## Commit & Pull Request Guidelines

- Commit message：使用中文、简洁说明修改点；可用 `：` 追加细节（示例：`搭建项目框架：实现核心模块...`）。
- 分支建议：`feature/<desc>`、`fix/<desc>`（主分支 `main`/`master`）。
- PR：描述变更目的与影响、复现/验证步骤、涉及的配置项（尤其是 `config.yaml`）、必要时附 UI 截图/录屏。

## Configuration Tips

- `config.yaml` 常用项：`global.web_port`、`global.log_level`、`global.database_path`。
- `sync_tasks[].target.type` 支持 `local` / `ssh`；SSH 优先配置 `ssh_key_path`，避免在仓库内保存密码。
- 如调整配置结构，请同步更新 `config.example.yaml`，并在 PR 说明迁移方式。

## Security & Configuration Tips

- 不要提交任何密钥/口令。敏感信息放在 `config.yaml`（已忽略），SSH 优先使用密钥而非密码。
- `data/`、`logs/` 为运行时产物；如需排查问题，可在 PR 中附关键日志片段（避免包含敏感信息）。
