"""Experimental Trio-compatible Unix descriptor readiness API."""
import operator
from trio_rust_poc.runtime import (
    ClosedResourceError, _runtime, _yield, _PARK, _SHIELDED_CHECKPOINT,
    _checkpoint_if_cancelled, checkpoint,
)


class BusyResourceError(Exception):
    pass


def _fd(resource):
    return operator.index(resource if isinstance(resource, int) else resource.fileno())


async def _wait(resource, writable):
    await _checkpoint_if_cancelled()
    fd = _fd(resource)
    runtime = _runtime.get()
    if not runtime.register_io(fd, writable):
        raise BusyResourceError("another task is waiting on this descriptor")
    try:
        await _yield(_PARK)
        if runtime.io_closed():
            raise ClosedResourceError("descriptor closed while waiting")
    finally:
        runtime.unregister_io()


async def wait_readable(resource):
    await _wait(resource, False)


async def wait_writable(resource):
    await _wait(resource, True)


def notify_closing(resource):
    _runtime.get().notify_closing(_fd(resource))


async def cancel_shielded_checkpoint():
    await _yield(_SHIELDED_CHECKPOINT)


checkpoint_if_cancelled = _checkpoint_if_cancelled
