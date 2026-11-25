import attrs
from _native_task_state import NativeTaskState
from trio._util import NoPublicConstructor

@attrs.define(eq=False, repr=False)
class Task(NativeTaskState, metaclass=NoPublicConstructor):
    def __new__(cls, *args, **kwargs):
        return super().__new__(cls)

    name: str
    coro: object
    _runner: object
    _schedule_points: int = 0

async def worker():
    return 1

coro = worker()
task = Task._create(name='worker', coro=coro, runner=object())
assert isinstance(task, NativeTaskState)
assert task._next_send_fn is None
assert task._next_send is None
task._next_send_fn = coro.send
task._next_send = 'outcome'
task._abort_func = lambda: None
task.custom_sleep_data = {'wait': 1}
assert task._next_send_fn.__self__ is coro
assert task._next_send == 'outcome'
assert task.custom_sleep_data == {'wait': 1}
assert task._abort_func is not None
assert task._schedule_points == 0
try:
    Task(name='x', coro=coro, runner=object())
except TypeError:
    pass
else:
    raise AssertionError('constructor was public')
coro.close()
print('attrs subclass and Trio-style metaclass work')
