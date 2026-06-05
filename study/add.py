def add(a, b):
    return a + b


def main():
    a = float(input("请输入第1个数字:"))
    b = float(input("请输入第2个数字:"))
    res = add(a, b)
    print("和为:", res)


if __name__ == "__main__":
    main()
