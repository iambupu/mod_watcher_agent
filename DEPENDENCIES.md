# Dependencies

本项目依赖分为后端 Python 依赖和前端 Node.js 依赖。

## Backend (Python)

依赖清单文件：
- `backend/pyproject.toml`

安装方式：

```bash
cd backend
pip install -e .[dev]
```

说明：
- 运行依赖在 `[project].dependencies`
- 开发/测试依赖在 `[project.optional-dependencies].dev`

## Frontend (Node.js)

依赖清单文件：
- `frontend/package.json`
- `frontend/package-lock.json`

安装方式：

```bash
cd frontend
npm install
```

说明：
- 运行依赖在 `dependencies`
- 开发依赖在 `devDependencies`

## Version Baseline

- Python: `>=3.11`
- Node.js: 建议使用当前 LTS 版本（18/20 均可）

