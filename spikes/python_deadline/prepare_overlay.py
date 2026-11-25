"""Isolated Trio 0.35 deadline-setter experiment."""
import hashlib
from pathlib import Path
import shutil
import trio

root = Path(__file__).resolve().parent
source = Path(trio.__file__).parent
run = source / '_core' / '_run.py'
assert trio.__version__ == '0.35.0'
assert hashlib.sha256(run.read_bytes()).hexdigest() == '0354771966e15f5549a6d6b3cfaba8b666a429712c54af367c368c27c8edcb7b'
dest = root / 'overlay' / 'trio'
if dest.exists():
    shutil.rmtree(dest)
shutil.copytree(source, dest, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
target = dest / '_core' / '_run.py'
text = target.read_text()
start = text.index('    @contextmanager\n    @enable_ki_protection\n    def _might_change_registered_deadline(')
finish = text.index('    @property\n    def deadline(', start)
existing = text[start:finish]
registration = existing[existing.index('            old = self._registered_deadline\n'):]
registration = ''.join(line[4:] if line.startswith('    ') else line
                       for line in registration.splitlines(keepends=True))
replacement = '''    @contextmanager
    @enable_ki_protection
    def _might_change_registered_deadline(self) -> Iterator[None]:
        try:
            yield
        finally:
            self._sync_registered_deadline()

    def _sync_registered_deadline(self) -> None:
''' + registration
text = text[:start] + replacement + text[finish:]
old = '''    @deadline.setter
    def deadline(self, new_deadline: float) -> None:
        if isnan(new_deadline):
            raise ValueError("deadline must not be NaN")
        if self._relative_deadline != inf:
            assert self._deadline == inf
            raise RuntimeError(
                "Unentered relative cancel scope does not have an absolute deadline."
            )
        with self._might_change_registered_deadline():
            self._deadline = float(new_deadline)
'''
new = '''    @deadline.setter
    def deadline(self, new_deadline: float) -> None:
        if isnan(new_deadline):
            raise ValueError("deadline must not be NaN")
        if self._relative_deadline != inf:
            assert self._deadline == inf
            raise RuntimeError(
                "Unentered relative cancel scope does not have an absolute deadline."
            )
        self._assign_deadline_without_contextmanager(new_deadline)

    @enable_ki_protection
    def _assign_deadline_without_contextmanager(self, new_deadline: float) -> None:
        try:
            self._deadline = float(new_deadline)
        finally:
            self._sync_registered_deadline()
'''
assert text.count(old) == 1
target.write_text(text.replace(old, new, 1))
print(dest.parent)
