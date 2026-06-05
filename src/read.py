from pathlib import Path

from devagent.tools.file_tools import read_file_safe


def main() -> None:
    workspace = Path.cwd()
    sample_path = Path("input/test.txt")
    print(read_file_safe(sample_path, start_line=1, end_line=20, workspace=workspace))


if __name__ == "__main__":
    main()
