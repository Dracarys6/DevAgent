from pathlib import Path

p1 = Path("./input/xxx.txt")  # 相对路径
base_dir = Path("/Users/dracarys/projects/DevAgent/input")
path = base_dir / "test.txt"

print("路径:", p1)
print("绝对路径:", p1.resolve())
print("路径:", path)
print("绝对路径:", path.resolve())
print("路径是否存在:", path.exists())
print("是否是目录:", path.is_dir())
print("是否是文件:", path.is_file())

with open(path, "r", encoding="utf-8") as f:
    content = f.read()
print(content)

# 或者用 pathlib.Path
try:
    content = path.read_text(encoding="utf-8")
    print(content)
except FileNotFoundError:
    print("文件不存在")
except PermissionError:
    print("无权限读取")
