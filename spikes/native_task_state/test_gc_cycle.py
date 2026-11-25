"""Regression: Python-visible Task state must not leak a self cycle."""
import gc
import weakref
import trio
from _native_task_state import NativeTaskState

assert issubclass(trio.lowlevel.Task, NativeTaskState)

class Recorder(trio.abc.Instrument):
    def __init__(self):
        self.refs = []

    def task_exited(self, task):
        if task.name.endswith('child'):
            task.custom_sleep_data = task
            self.refs.append(weakref.ref(task))

async def child():
    pass

async def main():
    async with trio.open_nursery() as nursery:
        nursery.start_soon(child)

recorder = Recorder()
trio.run(main, instruments=[recorder])
assert len(recorder.refs) == 1
assert recorder.refs[0]() is not None
gc.collect()
assert recorder.refs[0]() is None
print('native Task self cycle collected')
