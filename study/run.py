import subprocess


def main() -> None:
    r1 = subprocess.run(
        ["echo", "Hello World"],
        capture_output=True,  # 输出到 Python
        text=True,
        check=False,
    )

    r2 = subprocess.run(
        ["ls", "-l"],
        capture_output=True,
        text=True,
        cwd=".",
        check=False,
    )

    # rg 搜索命令
    r3 = subprocess.run(
        ["rg", "-n", "--no-heading", "-g", "*.py", "--", "test", "."],
        capture_output=True,
        text=True,
        check=False,
    )

    print(r1.stdout)
    print(r2.stdout)
    print(r3.stdout)


if __name__ == "__main__":
    main()
