#!/usr/bin/env python3
# add_relative_path_header.py
from pathlib import Path

ROOT = Path.cwd()


def process_file(py_file: Path):
    rel_path = py_file.relative_to(ROOT)
    comment_line = f"# {rel_path.as_posix()}\n"

    lines = py_file.read_text(encoding="utf-8").splitlines(keepends=True)

    if not lines:
        py_file.write_text(comment_line, encoding="utf-8")
        return

    # Якщо вже є такий коментар — пропускаємо
    if lines[0].strip() == comment_line.strip():
        return

    # Якщо є shebang — вставляємо після нього
    if lines[0].startswith("#!"):
        if len(lines) > 1 and lines[1].strip() == comment_line.strip():
            return
        lines.insert(1, comment_line)
    else:
        lines.insert(0, comment_line)

    py_file.write_text("".join(lines), encoding="utf-8")


def main():
    for py_file in ROOT.rglob("*.py"):
        if py_file.is_file():
            process_file(py_file)


if __name__ == "__main__":
    main()
