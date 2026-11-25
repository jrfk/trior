"""Opt-in recv variants for the Trio 0.35.0 experiment."""

import trio
from trio._core._traps import CancelShieldedCheckpoint
from trio._socket import _SocketType

_STOCK_RECV = _SocketType.recv


async def _wait_and_recv(sock, args):
    while True:
        await trio.lowlevel.wait_readable(sock)
        try:
            return sock.recv(*args)
        except BlockingIOError:
            pass


async def _python_recv(self, *args, **kwargs):
    if kwargs:
        return await _STOCK_RECV(self, *args, **kwargs)
    sock = self._sock
    await trio.lowlevel.checkpoint_if_cancelled()
    try:
        data = sock.recv(*args)
    except BlockingIOError:
        pass
    except BaseException:
        await trio.lowlevel.cancel_shielded_checkpoint()
        raise
    else:
        await trio.lowlevel.cancel_shielded_checkpoint()
        return data
    return await _wait_and_recv(sock, args)


def install(mode):
    if trio.__version__ != "0.35.0":
        raise RuntimeError("This experiment requires Trio 0.35.0")
    if mode == "stock":
        _SocketType.recv = _STOCK_RECV
        return
    if mode == "python":
        _SocketType.recv = _python_recv
        return
    if mode != "rust":
        raise ValueError(mode)

    from trio_rust_poc._native import RecvAttempt

    async def rust_recv(self, *args, **kwargs):
        if kwargs:
            return await _STOCK_RECV(self, *args, **kwargs)
        sock = self._sock
        await trio.lowlevel.checkpoint_if_cancelled()
        data = await RecvAttempt(sock, args, CancelShieldedCheckpoint)
        if data is None:
            return await _wait_and_recv(sock, args)
        return data

    _SocketType.recv = rust_recv
