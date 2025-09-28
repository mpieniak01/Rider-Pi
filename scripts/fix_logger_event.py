import pathlib
import re
import sys

# Pliki do poprawy – dopisz/usuń według potrzeb
FILES = [
    "apps/voice/capture.py",
    "apps/voice/tts.py",
    "apps/voice/service_impl.py",
    "apps/voice/svc_audio.py",
    "apps/voice/chat.py",
    "apps/voice/kws.py",
    "apps/voice/common.py",
]

# Wzorzec: (self.)?logger.(debug|info|warning|error)("TAG", <tu zaczynają się keyword-args>)
# Zmieniamy NA: logger.event("TAG", <keyword-args...>)
PATTERN = re.compile(
    r'((?:self\.)?logger)\.(debug|info|warning|error)\(\s*("([^"\\]|\\.)*")\s*,\s*([A-Za-z_][A-Za-z0-9_]*\s*=)',
    re.DOTALL,
)


def fix_text(txt: str) -> tuple[str, int]:
    count = 0

    def _repl(m):
        nonlocal count
        count += 1
        # \1 = logger / self.logger, \3 = "TAG", \5 = pierwszy keyword=
        return f"{m.group(1)}.event({m.group(3)}, {m.group(5)}"

    new = PATTERN.sub(_repl, txt)
    return new, count


def main():
    total = 0
    for p in FILES:
        path = pathlib.Path(p)
        if not path.exists() or path.suffix == ".bak":
            continue
        src = path.read_text(encoding="utf-8")
        dst, n = fix_text(src)
        if n:
            path.write_text(dst, encoding="utf-8")
            print(f"[fixed] {p}: {n} occurrence(s) changed")
            total += n
    print(f"Done. Total changes: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
