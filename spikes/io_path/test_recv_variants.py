"""Compare the recv variants at the scheduling and cancellation boundary."""

import pytest
import trio
import trio.testing

from recv_variants import install


@pytest.fixture(params=("stock", "python", "rust"))
def variant(request):
    install(request.param)
    try:
        yield
    finally:
        install("stock")


def test_preexisting_cancellation_does_not_consume_data(variant):
    async def main():
        left, right = trio.socket.socketpair()
        with left, right:
            await right.send(b"x")
            with trio.CancelScope() as scope:
                scope.cancel()
                await left.recv(1)
                pytest.fail("cancelled receive returned normally")
            assert scope.cancelled_caught
            assert await left.recv(1) == b"x"

    trio.run(main)


def test_immediate_success_yields_and_delivers_data_before_cancellation(variant):
    class CancelOnYield(trio.abc.Instrument):
        task = None
        scope = None

        def after_task_step(self, task):
            if task is self.task:
                self.scope.cancel()

    async def main():
        left, right = trio.socket.socketpair()
        with left, right:
            await right.send(b"x")
            with trio.CancelScope() as scope:
                instrument.task = trio.lowlevel.current_task()
                instrument.scope = scope
                assert await left.recv(1) == b"x"
                assert scope.cancel_called
                instrument.task = None
                await trio.lowlevel.checkpoint()
                pytest.fail("cancellation was not delivered at the next checkpoint")
            assert scope.cancelled_caught

    instrument = CancelOnYield()
    trio.run(main, instruments=[instrument])


def test_blocked_receive_is_woken_on_close(variant):
    async def main():
        left, right = trio.socket.socketpair()
        with left, right:
            async def receiver():
                with pytest.raises(trio.ClosedResourceError):
                    await left.recv(1)

            async with trio.open_nursery() as nursery:
                nursery.start_soon(receiver)
                await trio.testing.wait_all_tasks_blocked()
                left.close()

    trio.run(main)


def test_recv_error_and_eof(variant):
    async def main():
        left, right = trio.socket.socketpair()
        with left, right:
            with pytest.raises(ValueError, match="negative"):
                await left.recv(-1)
            right.close()
            assert await left.recv(1) == b""

    trio.run(main)


def test_stop_iteration_from_index_is_not_a_result(variant):
    class InvalidSize:
        def __index__(self):
            raise StopIteration("no size")

    async def main():
        left, right = trio.socket.socketpair()
        with left, right:
            with pytest.raises(RuntimeError, match="coroutine raised StopIteration") as exc:
                await left.recv(InvalidSize())
            assert isinstance(exc.value.__cause__, StopIteration)

    trio.run(main)
