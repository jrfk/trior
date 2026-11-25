"""Experimental Trio-shaped API backed by an independent Rust scheduler."""

import contextvars
import math
import types
from collections import deque

from ._native import Runtime, Trap, WaitQueue

_runtime = contextvars.ContextVar("rust_trio_runtime")
_CHECKPOINT = Trap(0)
_PARK = Trap(3)
_SHIELDED_CHECKPOINT = Trap(4)


class WouldBlock(Exception):
    pass


class EndOfChannel(Exception):
    pass


class ClosedResourceError(Exception):
    pass


class BrokenResourceError(Exception):
    pass


async def _checkpoint_if_cancelled():
    if _runtime.get().is_cancelled():
        await checkpoint()


class _ParkingLot:
    def __init__(self):
        self.queue = WaitQueue()
        self.runtime = None

    async def park(self):
        runtime = _runtime.get()
        task = runtime.current_task_id()
        if self.runtime is not None and self.runtime is not runtime:
            raise RuntimeError("waiters belong to a different run")
        self.runtime = runtime
        self.queue.push(task)
        try:
            await _yield(_PARK)
        finally:
            self.queue.remove(task)
            if not len(self.queue):
                self.runtime = None

    def unpark(self):
        while len(self.queue):
            runtime = self.runtime
            task = self.queue.pop()
            if not len(self.queue):
                self.runtime = None
            if runtime.wake_parked(task):
                return runtime, task
        return None


class Event:
    def __init__(self):
        self._flag = False
        self._lot = _ParkingLot()

    def is_set(self):
        return self._flag

    def set(self):
        self._flag = True
        while self._lot.unpark() is not None:
            pass

    async def wait(self):
        if self._flag:
            await checkpoint()
        else:
            await self._lot.park()


class _AcquireRelease:
    async def __aenter__(self):
        await self.acquire()

    async def __aexit__(self, *_):
        self.release()

    async def acquire(self):
        await _checkpoint_if_cancelled()
        try:
            self.acquire_nowait()
        except WouldBlock:
            await self._lot.park()
        else:
            await _yield(_SHIELDED_CHECKPOINT)


class Lock(_AcquireRelease):
    def __init__(self):
        self._owner = None
        self._lot = _ParkingLot()

    def locked(self):
        return self._owner is not None

    def acquire_nowait(self):
        runtime = _runtime.get()
        owner = (runtime, runtime.current_task_id())
        if self._owner == owner:
            raise RuntimeError("lock is already held by this task")
        if self.locked():
            raise WouldBlock
        self._owner = owner

    def release(self):
        runtime = _runtime.get()
        if self._owner != (runtime, runtime.current_task_id()):
            raise RuntimeError("lock is not held by this task")
        self._owner = self._lot.unpark()


class Semaphore(_AcquireRelease):
    def __init__(self, initial_value, *, max_value=None):
        if not isinstance(initial_value, int) or (max_value is not None and not isinstance(max_value, int)):
            raise TypeError("semaphore values must be integers")
        if initial_value < 0 or (max_value is not None and initial_value > max_value):
            raise ValueError("invalid semaphore value")
        self._value = initial_value
        self._max = max_value
        self._lot = _ParkingLot()

    @property
    def value(self):
        return self._value

    @property
    def max_value(self):
        return self._max

    def acquire_nowait(self):
        if not self._value:
            raise WouldBlock
        self._value -= 1

    def release(self):
        if self._lot.unpark() is None:
            if self._max is not None and self._value >= self._max:
                raise ValueError("semaphore released too many times")
            self._value += 1


class _ChannelState:
    def __init__(self, capacity):
        self.capacity = capacity
        self.buffer = deque()
        self.send_count = self.receive_count = 1
        self.send_lot = _ParkingLot()
        self.receive_lot = _ParkingLot()
        self.senders = {}
        self.receivers = {}

    def wake(self, lot, pending, error, endpoint=None):
        for key, operation in list(pending.items()):
            if endpoint is None or operation[0] is endpoint:
                runtime, task = key
                if runtime.wake_parked(task):
                    operation[2] = error()
                    lot.queue.remove(task)
        if not len(lot.queue):
            lot.runtime = None


class _ChannelEndpoint:
    def __init__(self, state):
        self._state = state
        self._closed = False

    def _check(self):
        if self._closed:
            raise ClosedResourceError

    def __enter__(self):
        self._check()
        return self

    def __exit__(self, *_):
        self.close()

    async def __aenter__(self):
        return self.__enter__()

    async def __aexit__(self, *_):
        await self.aclose()

    async def aclose(self):
        self.close()
        await _yield(_SHIELDED_CHECKPOINT)

    async def _park(self, lot, pending, value=None):
        runtime = _runtime.get()
        key = (runtime, runtime.current_task_id())
        operation = [self, value, None]
        pending[key] = operation
        try:
            await lot.park()
            if operation[2] is not None:
                raise operation[2]
            return operation[1]
        finally:
            del pending[key]


class MemorySendChannel(_ChannelEndpoint):
    def clone(self):
        self._check()
        self._state.send_count += 1
        return MemorySendChannel(self._state)

    def send_nowait(self, value):
        self._check()
        state = self._state
        if not state.receive_count:
            raise BrokenResourceError
        receiver = state.receive_lot.unpark()
        if receiver is not None:
            state.receivers[receiver][1] = value
        elif len(state.buffer) < state.capacity:
            state.buffer.append(value)
        else:
            raise WouldBlock

    async def send(self, value):
        await _checkpoint_if_cancelled()
        try:
            self.send_nowait(value)
        except WouldBlock:
            await self._park(self._state.send_lot, self._state.senders, value)
        else:
            await _yield(_SHIELDED_CHECKPOINT)

    def close(self):
        if self._closed:
            return
        self._closed = True
        state = self._state
        state.send_count -= 1
        state.wake(state.send_lot, state.senders, ClosedResourceError, self)
        if not state.send_count:
            state.wake(state.receive_lot, state.receivers, EndOfChannel)


class MemoryReceiveChannel(_ChannelEndpoint):
    def clone(self):
        self._check()
        self._state.receive_count += 1
        return MemoryReceiveChannel(self._state)

    def receive_nowait(self):
        self._check()
        state = self._state
        sender = state.send_lot.unpark()
        if sender is not None:
            state.buffer.append(state.senders[sender][1])
        if state.buffer:
            return state.buffer.popleft()
        if not state.send_count:
            raise EndOfChannel
        raise WouldBlock

    async def receive(self):
        await _checkpoint_if_cancelled()
        try:
            value = self.receive_nowait()
        except WouldBlock:
            return await self._park(self._state.receive_lot, self._state.receivers)
        else:
            await _yield(_SHIELDED_CHECKPOINT)
            return value

    def close(self):
        if self._closed:
            return
        self._closed = True
        state = self._state
        state.receive_count -= 1
        state.wake(state.receive_lot, state.receivers, ClosedResourceError, self)
        if not state.receive_count:
            state.wake(state.send_lot, state.senders, BrokenResourceError)
            state.buffer.clear()

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return await self.receive()
        except EndOfChannel:
            raise StopAsyncIteration from None


class open_memory_channel:
    @classmethod
    def __class_getitem__(cls, item):
        return cls

    def __new__(cls, max_buffer_size):
        if not isinstance(max_buffer_size, int) and max_buffer_size != math.inf:
            raise TypeError("max_buffer_size must be an integer or infinity")
        if max_buffer_size < 0:
            raise ValueError("max_buffer_size must be nonnegative")
        state = _ChannelState(max_buffer_size)
        return MemorySendChannel(state), MemoryReceiveChannel(state)


class Cancelled(BaseException):
    def __init__(self, scope):
        self.scope = scope
        super().__init__("cancelled")


@types.coroutine
def _yield(trap):
    return (yield trap)


async def checkpoint():
    await _yield(_CHECKPOINT)


async def sleep(seconds):
    seconds = float(seconds)
    if math.isnan(seconds) or seconds < 0:
        raise ValueError("sleep duration must be non-negative")
    if not seconds:
        await checkpoint()
    else:
        await _yield(Trap(1, seconds))


async def sleep_forever():
    await sleep(math.inf)

def current_time():
    return _runtime.get().current_time()

async def sleep_until(deadline):
    await sleep(max(0, deadline - current_time()))


class CancelScope:
    def __init__(self, *, deadline=math.inf, shield=False):
        self._runtime = None
        self._id = None
        self._entered = False
        self._cancel_called = False
        self.cancelled_caught = False
        self.deadline = deadline
        self.shield = shield

    @property
    def deadline(self):
        return self._deadline

    @deadline.setter
    def deadline(self, value):
        value = float(value)
        if math.isnan(value):
            raise ValueError("deadline must not be NaN")
        if self._runtime is not None:
            self._runtime.set_deadline(self._id, value)
        self._deadline = value

    @property
    def shield(self):
        return self._shield

    @shield.setter
    def shield(self, value):
        if not isinstance(value, bool):
            raise TypeError("shield must be a bool")
        if self._runtime is not None:
            self._runtime.set_shield(self._id, value)
        self._shield = value

    def __enter__(self):
        if self._entered:
            raise RuntimeError("CancelScope cannot be reused")
        runtime = _runtime.get()
        self._id = runtime.open_scope(self.shield, self.deadline)
        self._runtime = runtime
        self._entered = True
        if self._cancel_called:
            self._runtime.cancel(self._id)
        return self

    @property
    def cancel_called(self):
        return self._cancel_called or (
            self._runtime is not None and self._runtime.cancelled(self._id)
        )

    def cancel(self):
        self._cancel_called = True
        if self._runtime is not None:
            self._runtime.cancel(self._id)

    def __exit__(self, exc_type, exc, traceback):
        self._cancel_called = self._runtime.close_scope(self._id)
        self._runtime = None
        self.cancelled_caught = isinstance(exc, Cancelled) and exc.scope == self._id
        return self.cancelled_caught


class Nursery:
    def __init__(self, shield=False):
        self.cancel_scope = CancelScope(shield=shield)
        self._active = False

    async def __aenter__(self):
        self.cancel_scope.__enter__()
        self._active = True
        return self

    def start_soon(self, async_fn, *args, name=None):
        if not self._active:
            raise RuntimeError("nursery closed")
        coro = async_fn(*args)
        if not isinstance(coro, types.CoroutineType):
            raise TypeError("expected an async function")
        try:
            self.cancel_scope._runtime.spawn(
                self.cancel_scope._id, coro, contextvars.copy_context()
            )
        except BaseException:
            coro.close()
            raise

    async def __aexit__(self, exc_type, exc, traceback):
        if exc is not None:
            self.cancel_scope.cancel()
        runtime = self.cancel_scope._runtime
        scope = self.cancel_scope._id
        await _yield(Trap(2, group=scope))
        self._active = False
        errors = runtime.errors(scope)
        suppressed = self.cancel_scope.__exit__(exc_type, exc, traceback)
        if exc is not None and not isinstance(exc, Cancelled):
            errors.insert(0, exc)
        if errors:
            raise BaseExceptionGroup("Exceptions from Trio nursery", errors) from None
        if exc is not None:
            return suppressed
        if runtime.is_cancelled():
            await checkpoint()
        return False


def open_nursery(*, shield=False):
    return Nursery(shield=shield)


def run(async_fn, *args):
    if _runtime.get(None) is not None:
        raise RuntimeError("nested run")
    runtime = Runtime()
    token = _runtime.set(runtime)
    try:
        coro = async_fn(*args)
        if not isinstance(coro, types.CoroutineType):
            raise TypeError("expected an async function")
        return runtime.run(coro, contextvars.copy_context(), Cancelled)
    finally:
        _runtime.reset(token)
