from sample_app import UploadConfig, UploadManager


def test_small_upload_uses_min_timeout():
    manager = UploadManager(UploadConfig(min_timeout_seconds=3))

    timeout = manager.build_upload_timeout(size_mb=4, bandwidth_mb_s=10)

    assert timeout == 3


def test_large_upload_uses_dynamic_timeout():
    manager = UploadManager()

    timeout = manager.build_upload_timeout(size_mb=80, bandwidth_mb_s=10)

    assert timeout >= 12
