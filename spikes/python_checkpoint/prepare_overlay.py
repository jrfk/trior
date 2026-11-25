"""Isolated Trio 0.35 scheduler experiment; never edits installed Trio."""
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
old = '''                    if msg is CancelShieldedCheckpoint:
                        runner.reschedule(task)
'''
new = '''                    if msg is CancelShieldedCheckpoint:
                        # Equivalent to Runner.reschedule(task), in this hot path.
                        assert task._runner is runner
                        assert task._next_send_fn is None
                        task._next_send_fn = task.coro.send
                        task._next_send = Value(None)
                        task._abort_func = None
                        task.custom_sleep_data = None
                        if not runner.runq and runner.is_guest:
                            runner.force_guest_tick_asap()
                        runner.runq.append(task)
                        if "task_scheduled" in runner.instruments:
                            runner.instruments.call("task_scheduled", task)
'''
assert text.count(old) == 1
target.write_text(text.replace(old, new, 1))
print(dest.parent)
