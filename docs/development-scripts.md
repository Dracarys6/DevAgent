# DevAgent 开发脚本

## 目标

`scripts/` 提供项目本地开发的统一入口，确保 Python 命令始终使用项目虚拟环境，
并让后端测试、前端静态检查和生产构建可以重复执行。脚本支持 macOS 和 Linux，
应从任意工作目录调用。

## 环境初始化

```bash
./scripts/setup.sh
```

该脚本会：

- 检查 Python 3.11+、Node.js 和 npm；
- 在缺失时创建 `.venv`；
- 安装 `requirements.txt` 和 editable Python 项目；
- 使用 `npm ci` 按 lockfile 安装前端依赖。

如需选择特定 Python，可设置 `PYTHON_BIN`：

```bash
PYTHON_BIN=python3.12 ./scripts/setup.sh
```

## 启动开发服务

```bash
./scripts/start.sh
```

脚本同时启动 FastAPI 和 Vite，等待两个服务就绪后默认打开浏览器。使用
`--no-open` 可禁止打开浏览器，按 `Ctrl+C` 会统一停止前后端。

## 运行测试

默认只运行后端测试：

```bash
./scripts/test.sh
```

可以将测试路径和 pytest 参数直接传给脚本：

```bash
./scripts/test.sh tests/api/test_health.py -q
```

前端检查或完整检查：

```bash
./scripts/test.sh --frontend
./scripts/test.sh --all
```

## 提交前检查

```bash
./scripts/check.sh
```

该脚本依次检查所有 Shell 脚本的语法、Git diff 格式、完整后端测试、前端 lint
和前端生产构建。任何步骤失败都会立即返回非零状态码，适合作为提交前的统一检查入口。
