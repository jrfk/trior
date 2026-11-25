import socket
import pytest
import trio
import trior

@pytest.mark.parametrize("api", [trio, trior])
def test_readiness(api):
    async def main():
        a, b = socket.socketpair()
        with a, b:
            a.setblocking(False)
            b.setblocking(False)
            async def read():
                await api.lowlevel.wait_readable(a)
                assert a.recv(5) == b"hello"
            async with api.open_nursery() as n:
                n.start_soon(read)
                await api.sleep(0.01)
                await api.lowlevel.wait_writable(b)
                b.send(b"hello")
    api.run(main)

@pytest.mark.parametrize("api", [trio, trior])
def test_cancel_reregister(api):
    async def main():
        a, b = socket.socketpair()
        with a, b:
            async def read():
                with api.CancelScope(deadline=api.current_time()+0.01) as scope:
                    await api.lowlevel.wait_readable(a)
                assert scope.cancelled_caught
                b.send(b"x")
                await api.lowlevel.wait_readable(a)
                assert a.recv(1) == b"x"
            await read()
    api.run(main)

@pytest.mark.parametrize("api", [trio, trior])
def test_close_busy(api):
    async def main():
        a, b = api.socket.socketpair()
        with a, b:
            async def read():
                with pytest.raises(api.ClosedResourceError):
                    await a.recv(1)
            async with api.open_nursery() as n:
                n.start_soon(read)
                await api.sleep(0.01)
                with pytest.raises(api.BusyResourceError):
                    await api.lowlevel.wait_readable(a)
                a.close()
    api.run(main)

@pytest.mark.parametrize("api", [trio, trior])
def test_socketpair(api):
    async def main():
        a, b = api.socket.socketpair()
        with a, b:
            async def writer():
                for _ in range(100):
                    assert await b.send(b"x") == 1
            async with api.open_nursery() as n:
                n.start_soon(writer)
                total = 0
                while total < 100:
                    total += len(await a.recv(100))
    api.run(main)

@pytest.mark.parametrize("api", [trio, trior])
def test_readiness_under_ready_load(api):
    async def main():
        a, b = socket.socketpair()
        with a, b:
            done = api.Event()
            async def busy():
                while not done.is_set():
                    await api.lowlevel.checkpoint()
            async def reader():
                await api.lowlevel.wait_readable(a)
                assert a.recv(1) == b"x"
                done.set()
            with api.CancelScope(deadline=api.current_time()+1) as scope:
                async with api.open_nursery() as n:
                    n.start_soon(busy)
                    n.start_soon(reader)
                    await api.sleep(0.01)
                    b.send(b"x")
            assert not scope.cancelled_caught
            assert done.is_set()
    api.run(main)

@pytest.mark.parametrize("api", [trio, trior])
def test_independent_read_write_waiters(api):
    async def main():
        a, b = socket.socketpair()
        with a, b:
            a.setblocking(False)
            b.setblocking(False)
            flags = []
            async def reader():
                await api.lowlevel.wait_readable(a)
                flags.append(a.recv(1))
            async def writer():
                await api.lowlevel.wait_writable(a)
                flags.append(b"write")
            async with api.open_nursery() as n:
                n.start_soon(reader)
                n.start_soon(writer)
                await api.sleep(0.01)
                b.send(b"r")
            assert set(flags) == {b"r", b"write"}
    api.run(main)

@pytest.mark.parametrize("api", [trio, trior])
def test_peer_eof(api):
    async def main():
        a, b = api.socket.socketpair()
        with a, b:
            async def reader():
                assert await a.recv(1) == b""
            async with api.open_nursery() as n:
                n.start_soon(reader)
                await api.sleep(0.001)
                b.close()
    api.run(main)


@pytest.mark.parametrize("api", [trio, trior])
def test_registration_churn(api):
    async def main():
        for _ in range(40):
            a, b = api.socket.socketpair()
            with a, b:
                async def reader():
                    with api.CancelScope() as scope:
                        scope.cancel()
                        await api.lowlevel.wait_readable(a)
                    assert scope.cancelled_caught
                    assert await a.recv(1) == b"x"
                async with api.open_nursery() as n:
                    n.start_soon(reader)
                    await b.send(b"x")
    api.run(main)


@pytest.mark.parametrize("api", [trio, trior])
def test_more_than_event_batch(api):
    async def main():
        pairs = [socket.socketpair() for _ in range(300)]
        async def reader(a):
            await api.lowlevel.wait_readable(a)
            assert a.recv(1) == b"x"
        try:
            with api.CancelScope(deadline=api.current_time()+2) as scope:
                async with api.open_nursery() as n:
                    for a, b in pairs:
                        a.setblocking(False)
                        n.start_soon(reader, a)
                    await api.sleep(0.01)
                    for a, b in pairs:
                        b.send(b"x")
            assert not scope.cancelled_caught
        finally:
            for a, b in pairs:
                a.close()
                b.close()
    api.run(main)
