import pytest
import trio
import trior


@pytest.mark.parametrize("api", [trio, trior])
def test_start_value_and_scope_transfer(api):
    async def worker(*, task_status):
        await api.sleep(0)
        task_status.started(42)
        await stopped.wait()
        done.append(True)

    async def main():
        nonlocal stopped
        stopped = api.Event()
        async with api.open_nursery() as nursery:
            with api.CancelScope() as scope:
                assert await nursery.start(worker) == 42
                scope.cancel()
            stopped.set()
        assert done == [True]

    stopped = None
    done = []
    api.run(main)


@pytest.mark.parametrize("api", [trio, trior])
def test_prestart_failure_is_direct(api):
    async def worker(*, task_status):
        await api.sleep(0)
        raise ValueError("initialization failed")

    async def main():
        async with api.open_nursery() as nursery:
            with pytest.raises(ValueError, match="initialization failed"):
                await nursery.start(worker)
            await api.sleep(0)

    api.run(main)


@pytest.mark.parametrize("api", [trio, trior])
def test_missing_started(api):
    async def worker(*, task_status):
        pass

    async def main():
        async with api.open_nursery() as nursery:
            with pytest.raises(RuntimeError, match="without calling"):
                await nursery.start(worker)

    api.run(main)


@pytest.mark.parametrize("api", [trio, trior])
def test_cancel_start_waits_for_cleanup(api):
    async def worker(*, task_status):
        try:
            await api.sleep_forever()
        finally:
            cleaned.append(True)

    async def main():
        async with api.open_nursery() as nursery:
            with api.CancelScope(deadline=api.current_time()+0.01) as scope:
                await nursery.start(worker)
            assert scope.cancelled_caught
            assert cleaned == [True]

    cleaned = []
    api.run(main)


@pytest.mark.parametrize("api", [trio, trior])
def test_nested_child_can_signal_started(api):
    async def worker(*, task_status):
        async def descendant():
            task_status.started("nested")
            await release.wait()
            done.append(True)
        async with api.open_nursery() as nursery:
            nursery.start_soon(descendant)

    async def main():
        nonlocal release
        release = api.Event()
        async with api.open_nursery() as nursery:
            with api.CancelScope() as scope:
                assert await nursery.start(worker) == "nested"
                scope.cancel()
            release.set()
        assert done == [True]

    release = None
    done = []
    api.run(main)


@pytest.mark.parametrize("api", [trio, trior])
def test_poststart_failure_goes_to_nursery(api):
    async def worker(*, task_status):
        task_status.started()
        await api.sleep(0)
        raise ValueError("after start")

    async def main():
        with pytest.raises(BaseExceptionGroup) as info:
            async with api.open_nursery() as nursery:
                await nursery.start(worker)
        assert any(isinstance(item, ValueError) for item in info.value.exceptions)

    api.run(main)


@pytest.mark.parametrize("api", [trio, trior])
def test_task_status_ignored(api):
    async def worker(*, task_status=api.TASK_STATUS_IGNORED):
        task_status.started(1)
        task_status.started(2)

    api.run(worker)


@pytest.mark.parametrize("api", [trio, trior])
def test_duplicate_started(api):
    async def worker(*, task_status):
        task_status.started(1)
        with pytest.raises(RuntimeError, match="twice"):
            task_status.started(2)

    async def main():
        async with api.open_nursery() as nursery:
            assert await nursery.start(worker) == 1

    api.run(main)


@pytest.mark.parametrize("api", [trio, trior])
def test_start_many(api):
    async def main():
        release = api.Event()
        async def worker(i, *, task_status):
            task_status.started(i)
            await release.wait()
        async with api.open_nursery() as nursery:
            for i in range(600):
                assert await nursery.start(worker, i) == i
            release.set()
    api.run(main)


@pytest.mark.parametrize("api", [trio, trior])
def test_start_after_cancellation_does_not_escape(api):
    async def main():
        exited = api.Event()
        async def worker(*, task_status):
            try:
                await api.sleep_forever()
            finally:
                task_status.started()
                exited.set()
        async with api.open_nursery() as nursery:
            with api.CancelScope(deadline=api.current_time()+0.01) as scope:
                await nursery.start(worker)
            assert scope.cancelled_caught
            assert exited.is_set()

    api.run(main)
