"""Experimental nonblocking Unix socket adapter; no async DNS yet."""
import socket as _socket
from socket import AF_INET, AF_INET6, AF_UNIX, SOCK_STREAM, SOCK_DGRAM, SOL_SOCKET, SO_ERROR
from . import lowlevel


class SocketType:
    def __init__(self, sock):
        self._sock = sock
        sock.setblocking(False)

    def fileno(self):
        return self._sock.fileno()

    def close(self):
        if self.fileno() >= 0:
            try:
                lowlevel.notify_closing(self)
            except LookupError:
                pass
            self._sock.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def bind(self, address):
        self._sock.bind(address)

    def listen(self, backlog=128):
        self._sock.listen(backlog)

    def getsockname(self):
        return self._sock.getsockname()

    def setsockopt(self, *args):
        return self._sock.setsockopt(*args)

    def shutdown(self, how):
        return self._sock.shutdown(how)

    async def _call(self, method, writable, *args):
        await lowlevel.checkpoint_if_cancelled()
        try:
            result = method(*args)
        except BlockingIOError:
            wait = lowlevel.wait_writable if writable else lowlevel.wait_readable
            while True:
                await wait(self)
                try:
                    return method(*args)
                except BlockingIOError:
                    continue
        except BaseException:
            await lowlevel.cancel_shielded_checkpoint()
            raise
        await lowlevel.cancel_shielded_checkpoint()
        return result

    async def recv(self, size, flags=0):
        return await self._call(self._sock.recv, False, size, flags)

    async def recv_into(self, buffer, nbytes=0, flags=0):
        return await self._call(self._sock.recv_into, False, buffer, nbytes, flags)

    async def send(self, data, flags=0):
        return await self._call(self._sock.send, True, data, flags)

    async def accept(self):
        sock, addr = await self._call(self._sock.accept, False)
        return SocketType(sock), addr


def from_stdlib_socket(sock):
    return SocketType(sock)


def socket(family=AF_INET, type=SOCK_STREAM, proto=0, fileno=None):
    return SocketType(_socket.socket(family, type, proto, fileno=fileno))


def socketpair(*args, **kwargs):
    a, b = _socket.socketpair(*args, **kwargs)
    return SocketType(a), SocketType(b)
