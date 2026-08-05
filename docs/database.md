# DevAgent 数据库设计

## 目标与边界

DevAgent 使用 SQLite 为本地单服务提供持久化地基。领域服务依赖 Repository / Store
契约，不直接依赖 `sqlite3.Connection`、表名或 SQL。应用装配层负责选择内存或数据库
adapter，`SQLiteDatabase` 只管理连接、PRAGMA、migration 和显式事务。

当前实现使用 Python 标准库 `sqlite3`，没有引入 ORM。该选择适合本地部署和低到中等
写并发，不表示 SQLite adapter 可以无成本替换成 PostgreSQL；可替换的是领域契约，SQL
方言、并发控制和 upsert 仍属于 adapter 实现。

## 模块结构

```text
Manager / Service
       |
       v
Repository / Store Protocol
       |
       +-- InMemory adapter
       |
       +-- SQLite adapter (后续逐领域接入)
                  |
                  v
          SQLiteDatabase
          - connection
          - transaction
          - migrations
```

`src/devagent/storage/database.py` 提供：

- `SQLiteSettings`：数据库文件和锁等待时间。
- `SQLiteDatabase.connect()`：创建独立短连接并配置 PRAGMA。
- `SQLiteDatabase.transaction()`：显式 BEGIN、COMMIT、ROLLBACK 和关闭连接。
- `SQLiteDatabase.initialize()`：启用 WAL 并应用 migration。

`src/devagent/storage/migrations.py` 提供不可变 migration、checksum 校验和 Schema v1。
`apply_migrations()` 自己拥有完整事务，必须在没有活动事务的连接上调用；它同时兼容
`sqlite3` 默认 tuple row 和 `SQLiteDatabase` 配置的 `sqlite3.Row`。

## 连接配置

每个连接都启用：

```sql
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
```

文件数据库初始化时启用：

```sql
PRAGMA journal_mode = WAL;
```

连接设置 `sqlite3.Row`，方便 Repository 按列名读取。连接按操作创建并及时关闭，不跨线程
共享。`busy_timeout` 只能吸收短暂写锁竞争，不能补救长事务或高并发写入架构。
连接配置和显式事务都在 `BaseException` 边界清理资源，确保普通异常以及
`KeyboardInterrupt` / `SystemExit` 等进程控制异常不会留下未关闭连接或未回滚事务。

## Schema v1

| 表 | 用途 | 关键约束 |
| --- | --- | --- |
| `schema_migrations` | 记录版本、名称和 checksum | `version` 主键 |
| `agent_tasks` | 任务配置、状态与错误 | 状态 CHECK、步数正数 |
| `agent_events` | 事件 envelope 与完整 JSON | 外键、`(task_id, sequence_id)` 唯一 |
| `tool_calls` | 工具调用输入、结果和耗时 | `(task_id, tool_call_id)` 复合主键 |
| `permission_requests` | 待审批请求及处理结果 | 状态和决策 CHECK |
| `permission_policies` | 可复用权限策略 | enabled 和决策 CHECK |
| `eval_runs` | 评测配置、指标和完整结果 | schema_valid CHECK |
| `webhook_deliveries` | GitHub webhook 幂等状态 | delivery 主键、状态 CHECK |
| `github_review_publications` | PR 评论发布状态 | PR head 唯一、delivery 外键 |

稳定且常查询的 envelope 字段单独建列，多态或演进频繁的完整对象保存为 JSON。JSON 写入
前必须经过 Pydantic 校验和现有敏感字段脱敏；本地数据库不能保存 API key、token、密码或
Authorization 明文。

`webhook_deliveries.event_name` 和 `repository_full_name` 在 Schema v1 中允许为空，因为
现有 `WebhookDeliveryStore.claim(delivery_id)` 契约只保证传入 delivery ID。SQLite adapter
可以直接实现当前幂等接口；应用层未来扩展元数据时再填充这两列，不能为了满足 `NOT NULL`
约束伪造业务值。`state` 仍受 `processing` / `completed` CHECK 约束。

## Migration 规则

初始化过程在单个事务中完成：

1. 创建 `schema_migrations`。
2. 读取已应用版本及 checksum。
3. 拒绝程序无法识别的更高版本。
4. 拒绝同版本名称或 checksum 漂移。
5. 顺序执行缺失 migration 并记录版本。
6. 任一 SQL 失败时回滚该次 migration 的 DDL 和版本记录。

Migration 不允许嵌套在业务事务中。否则 migration 内部的 commit / rollback 会改变调用方
事务的所有权，使业务写入和 schema 变更产生无法解释的原子性边界。

已经发布的 migration 不允许原地修改。Schema 变化必须新增连续版本，否则旧数据库和新
数据库可能在同一个版本号下形成不同结构。

## 事务边界

事务只包含短时间数据库读写：

```text
外部 LLM / Git / Shell / HTTP 调用
  -> 获得结果
  -> BEGIN
  -> 写事件、工具结果和任务状态
  -> COMMIT
```

不要在事务中等待外部调用。数据库 rollback 无法撤销已经发生的网络副作用，长事务还会
持有写锁并放大请求排队。未来跨多个 Repository 的原子操作应复用同一个 transaction
connection，或在其上增加 Unit of Work。

## 验证

```bash
uv run pytest tests/storage -q
uv run ruff check src/devagent/storage tests/storage
uv run ruff format --check src/devagent/storage tests/storage
uv run pytest -q
```

关闭重开测试必须使用新的 `SQLiteDatabase` 和连接读取已提交记录，以验证数据真正落盘，
而不只是同一个 connection 的可见性。
