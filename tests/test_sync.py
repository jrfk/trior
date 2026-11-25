import pytest
import trio
from trior import _runtime as runtime


@pytest.fixture(params=[trio, runtime], ids=["trio", "rust"])
def api(request):
    return request.param


def test_event_broadcast(api):
    async def main():
        event = api.Event()
        arrived = []
        completed = []

        async def worker(i):
            arrived.append(i)
            await event.wait()
            completed.append(i)

        async with api.open_nursery() as nursery:
            for i in range(100):
                nursery.start_soon(worker, i)
            while len(arrived) < 100:
                await api.sleep(0)
            assert not completed
            event.set()
        assert sorted(completed) == list(range(100))
        assert event.is_set()
        await event.wait()
    api.run(main)


def test_event_cancelled_waiter(api):
    async def main():
        event = api.Event()
        with api.CancelScope(deadline=api.current_time() + 0.005) as scope:
            await event.wait()
        assert scope.cancelled_caught
        event.set()
        await event.wait()
    api.run(main)


def test_lock_and_semaphore(api):
    async def main():
        for primitive, limit in [(api.Lock(), 1), (api.Semaphore(3, max_value=3), 3)]:
            active = peak = count = 0

            async def worker():
                nonlocal active, peak, count
                for _ in range(10):
                    async with primitive:
                        active += 1
                        peak = max(peak, active)
                        await api.sleep(0)
                        assert active <= limit
                        active -= 1
                        count += 1

            async with api.open_nursery() as nursery:
                for _ in range(30):
                    nursery.start_soon(worker)
            assert count == 300 and peak == limit
    api.run(main)


def test_lock_cancelled_waiter(api):
    async def main():
        lock = api.Lock()
        await lock.acquire()
        scopes = []

        async def waiter():
            with api.CancelScope() as scope:
                scopes.append(scope)
                async with lock:
                    pytest.fail("cancelled waiter acquired lock")
            assert scope.cancelled_caught

        async with api.open_nursery() as nursery:
            nursery.start_soon(waiter)
            while not scopes:
                await api.sleep(0)
            scopes[0].cancel()
            lock.release()
        assert not lock.locked()
        async with lock:
            assert lock.locked()
    api.run(main)


def test_granted_lock_survives_cancellation_until_next_checkpoint(api):
    async def main():
        lock = api.Lock()
        await lock.acquire()
        scopes = []
        acquired = []

        async def waiter():
            with api.CancelScope() as scope:
                scopes.append(scope)
                async with lock:
                    acquired.append(True)
                    await api.sleep(0)
            assert scope.cancelled_caught

        async with api.open_nursery() as nursery:
            nursery.start_soon(waiter)
            while not scopes:
                await api.sleep(0)
            lock.release()
            scopes[0].cancel()
        assert acquired == [True] and not lock.locked()
    api.run(main)


@pytest.mark.parametrize("capacity", [0, 1, 64])
def test_channel_delivery_and_close(api, capacity):
    async def main():
        send, receive = api.open_memory_channel[int](capacity)
        results = []

        async def producer():
            async with send:
                for n in range(500):
                    await send.send(n)

        async with api.open_nursery() as nursery:
            nursery.start_soon(producer)
            async with receive:
                async for value in receive:
                    results.append(value)
        assert results == list(range(500))
    api.run(main)


def test_channel_nowait_and_clone(api):
    async def main():
        send, receive = api.open_memory_channel[int](1)
        clone = send.clone()
        send.close()
        clone.send_nowait(42)
        with pytest.raises(api.WouldBlock):
            clone.send_nowait(43)
        clone.close()
        assert receive.receive_nowait() == 42
        with pytest.raises(api.EndOfChannel):
            receive.receive_nowait()
        receive.close()
        with pytest.raises(api.ClosedResourceError):
            await receive.receive()
    api.run(main)


def test_closing_receiver_wakes_sender(api):
    async def main():
        send, receive = api.open_memory_channel(0)
        started = api.Event()

        async def worker():
            started.set()
            with pytest.raises(api.BrokenResourceError):
                await send.send("data")

        async with api.open_nursery() as nursery:
            nursery.start_soon(worker)
            await started.wait()
            receive.close()
        send.close()
    api.run(main)


def test_cancelled_channel_send_does_not_deliver(api):
    async def main():
        send, receive = api.open_memory_channel(0)
        with api.CancelScope(deadline=api.current_time() + 0.005) as scope:
            await send.send(1)
        assert scope.cancelled_caught
        with pytest.raises(api.WouldBlock):
            receive.receive_nowait()
        send.close()
        receive.close()
    api.run(main)
