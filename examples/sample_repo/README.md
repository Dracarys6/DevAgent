# Sample Repo：可复现 CI 失败样例

这是 DevAgent 第 6 周研发效能业务 Demo 使用的被诊断仓库。

它模拟一次上传 timeout 回归：

```text
UploadManager 原本应该根据文件大小和带宽动态计算 timeout。
当前实现错误地固定返回 min_timeout_seconds。
小文件测试通过，大文件测试稳定失败。
```

## 运行测试

从 DevAgent 项目根目录运行：

```bash
.venv/bin/pytest examples/sample_repo/tests -q
```

或进入样例仓库运行：

```bash
cd examples/sample_repo
../../.venv/bin/pytest -q
```

预期结果：

```text
1 failed, 1 passed
```

失败测试：

```text
tests/test_uploader.py::test_large_upload_uses_dynamic_timeout
```

核心断言：

```text
assert 3 >= 12
```

## 根因

根因位于：

```text
src/sample_app/uploader.py
UploadManager.build_upload_timeout
```

当前实现固定返回最小 timeout：

```python
return self.config.min_timeout_seconds
```

正确方向是使用 `estimate_upload_timeout(size_mb, bandwidth_mb_s)` 计算预计耗时，乘以 `safety_factor`，再和 `min_timeout_seconds` 取较大值。
