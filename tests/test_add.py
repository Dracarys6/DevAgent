from study.add import add

# 测试函数必须以 test_ 开头
def test_add_normal():
    assert add(1, 2) == 3   # 1+2=3 正确

def test_add_zero():
    assert add(0, 0) == 0   # 0+0=0 正确

def test_add_negative():
    assert add(-1, 1) == 0  # -1+1=0 正确
