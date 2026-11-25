"""Build a temporary Trio 0.35 source fork with NativeTaskState as Task base."""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import shutil
import trio

EXPECTED = '0354771966e15f5549a6d6b3cfaba8b666a429712c54af367c368c27c8edcb7b'
source_root = Path(trio.__file__).parent
source = source_root / '_core' / '_run.py'
assert trio.__version__ == '0.35.0'
assert hashlib.sha256(source.read_bytes()).hexdigest() == EXPECTED
out = Path(__file__).resolve().parent / 'overlay' / 'trio'
if out.exists():
    shutil.rmtree(out)
shutil.copytree(source_root, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
p = out / '_core' / '_run.py'
s = p.read_text()
assert s.count('import attrs\n') == 1
s = s.replace('import attrs\n', 'import attrs\nfrom _native_task_state import NativeTaskState, reschedule_native\n', 1)
needle = 'class Task(metaclass=NoPublicConstructor):  # type: ignore[explicit-any]\n'
assert s.count(needle) == 1
s = s.replace(needle,
              'class Task(NativeTaskState, metaclass=NoPublicConstructor):  # type: ignore[explicit-any]\n'
              '    def __new__(cls, *args: object, **kwargs: object) -> Task:\n'
              '        return super().__new__(cls)\n\n', 1)
for field in ('_next_send_fn', '_next_send', '_abort_func', 'custom_sleep_data'):
    lines = s.splitlines(keepends=True)
    matches = [i for i, line in enumerate(lines) if line.startswith(f'    {field}:')]
    assert len(matches) == 1, (field, matches)
    del lines[matches[0]]
    s = ''.join(lines)
start = s.index('        if next_send is _NO_SEND:\n', s.index('    def reschedule('))
end = s.index('\n    def spawn_impl(', start)
s = s[:start] + '''        if next_send is _NO_SEND:
            next_send = Value(None)
        reschedule_native(self, task, next_send)
''' + s[end:]
if os.environ.get('TASK_SPIKE_BATCH') == '1':
    s = s.replace('from _native_task_state import NativeTaskState, reschedule_native',
                  'from _native_task_state import NativeTaskState, reschedule_native, run_batch_fast as run_native_batch')
    begin = s.index('            while batch:\n')
    finish = s.index('\n    except GeneratorExit:', begin)
    s = s[:begin] + '            run_native_batch(runner, batch, sys.modules[__name__])\n' + s[finish:]
if os.environ.get('TASK_SPIKE_QUEUE') == '1':
    s = s.replace('from _native_task_state import NativeTaskState, reschedule_native',
                  'from _native_task_state import NativeRunQueue, NativeTaskState, reschedule_native', 1)
    needle = '    runq: deque[Task] = attrs.Factory(deque)'
    assert s.count(needle) == 1
    s = s.replace(needle, '    runq: NativeRunQueue = attrs.Factory(NativeRunQueue)', 1)
    needle = '            batch = list(runner.runq)\n            runner.runq.clear()'
    assert s.count(needle) == 1
    s = s.replace(needle, '            batch = runner.runq.take_batch()', 1)
if os.environ.get('TASK_SPIKE_DIRECT_QUEUE') == '1':
    assert os.environ.get('TASK_SPIKE_QUEUE') == '1'
    assert os.environ.get('TASK_SPIKE_BATCH') == '1'
    s = s.replace('run_batch_fast as run_native_batch',
                  'run_batch_fast as run_native_batch, run_queue_fast as run_native_queue', 1)
    start = s.index('            batch = runner.runq.take_batch()\n')
    end = s.index('            run_native_batch(runner, batch, sys.modules[__name__])\n', start)
    end += len('            run_native_batch(runner, batch, sys.modules[__name__])\n')
    s = s[:start] + '''            if _ALLOW_DETERMINISTIC_SCHEDULING:
                batch = runner.runq.take_batch()
                batch.sort(key=lambda t: t._counter)
                _r.shuffle(batch)
                run_native_batch(runner, batch, sys.modules[__name__])
            else:
                batch = runner.runq.take_batch_queue()
                run_native_queue(runner, batch, sys.modules[__name__], _r.random() < 0.5)
''' + s[end:]
p.write_text(s)
print(out.parent)
