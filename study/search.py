from pathlib import Path

from devagent.tools.search_tools import search_code


def main() -> None:
    workspace = Path.cwd()
    result = search_code("test", workspace, file_pattern="*.py", max_chars=500)
    print(result)


if __name__ == "__main__":
    main()
