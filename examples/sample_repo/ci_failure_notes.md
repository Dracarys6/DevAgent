# CI 失败人工基线

失败测试：tests/test_uploader.py::test_large_upload_uses_dynamic_timeout
错误现象：大文件上传 timeout 仍为 3 秒，低于预期动态 timeout
根因文件：src/sample_app/uploader.py
根因函数：UploadManager.build_upload_timeout
关键证据：
    1. pytest 断言显示 assert 3 >= 12
    2. build_upload_timeout 固定返回 min_timeout_seconds
    3. estimate_upload_timeout 已提供计算基础但未被使用
修复方向：
    使用 estimate_upload_timeout * safety_factor，并与 min_timeout_seconds 取 max

人工诊断步骤基线：
    1. 运行 pytest 看到 test_large_upload_uses_dynamic_timeout 失败
    2. 读取断言信息 assert 3 >= 12
    3. 打开 src/sample_app/uploader.py
    4. 定位 UploadManager.build_upload_timeout
    5. 对比 estimate_upload_timeout，发现动态耗时计算未被使用
