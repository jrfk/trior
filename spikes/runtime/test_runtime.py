import contextvars
import math
import gc
import weakref

import pytest
import trio
from trio_rust_poc import runtime


def test_runtime_resources_bounded_during_churn():
    async def main():
        native = runtime._runtime.get()

        async def child():
            with runtime.CancelScope() as scope:
                for offset in range(20):
                    scope.deadline = runtime.current_time() + 60 + offset
                await runtime.sleep(0)

        with runtime.CancelScope(deadline=runtime.current_time() + 30):
            for _ in range(100):
                async with runtime.open_nursery() as nursery:
                    for _ in range(100):
                        nursery.start_soon(child)
                tasks, scopes, timers, deadlines = native.resource_counts()
                assert (tasks, scopes, timers) == (1, 1, 0)
                assert deadlines <= 66

    runtime.run(main)


def test_closed_scope_does_not_keep_runtime_and_preserves_cancelled():
    async def main():
        with runtime.CancelScope() as scope:
            scope.cancel()
            await runtime.checkpoint()
        assert scope.cancel_called and scope.cancelled_caught
        assert scope._runtime is None
        scope.deadline = -math.inf
        scope.shield = True
        assert scope.cancel_called
        with pytest.raises(RuntimeError):
            with scope:
                pass

    runtime.run(main)


def test_finished_task_releases_context_and_payload():
    class Payload:
        pass

    variable = contextvars.ContextVar("payload")

    async def main():
        payload = Payload()
        reference = weakref.ref(payload)
        token = variable.set(payload)

        async def child():
            assert variable.get() is not None
            await runtime.checkpoint()

        async with runtime.open_nursery() as nursery:
            nursery.start_soon(child)
        variable.reset(token)
        del token, payload
        gc.collect()
        assert reference() is None

    runtime.run(main)


def test_deadline_wakes_sleep_forever(api):
    async def main():
        with api.CancelScope(deadline=api.current_time() + 0.005) as scope:
            await api.sleep_forever()
        assert scope.cancel_called and scope.cancelled_caught
    api.run(main)


def test_deadline_can_be_extended_and_removed(api):
    async def main():
        with api.CancelScope(deadline=api.current_time() + 0.005) as scope:
            scope.deadline = math.inf
            await api.sleep(0.015)
            assert not scope.cancel_called
            scope.deadline = -math.inf
            await api.sleep(0)
            pytest.fail("past deadline was ignored")
        assert scope.cancelled_caught
    api.run(main)


def test_dynamic_shield_unblocks_cancellation(api):
    async def main():
        scopes = []

        async def child():
            with api.CancelScope(shield=True) as scope:
                scopes.append(scope)
                await api.sleep_forever()

        async with api.open_nursery() as nursery:
            nursery.start_soon(child)
            while not scopes:
                await api.sleep(0)
            nursery.cancel_scope.cancel()
            scopes[0].shield = False

    api.run(main)


def test_closed_scope_deadline_is_ignored(api):
    async def main():
        with api.CancelScope(deadline=api.current_time() + 0.005) as scope:
            pass
        await api.sleep(0.015)
        assert not scope.cancel_called
    api.run(main)


@pytest.fixture(params=[trio, runtime], ids=["trio", "rust"])
def api(request):
    return request.param


def checkpoint(api):
    return api.sleep(0)


def test_600_tasks_and_context(api):
    variable = contextvars.ContextVar("value")
    results = []

    async def child(index):
        assert variable.get() == index
        await checkpoint(api)
        assert variable.get() == index
        await api.sleep(0.001)
        results.append(index)

    async def main():
        async with api.open_nursery() as nursery:
            for index in range(600):
                variable.set(index)
                nursery.start_soon(child, index)
        return "done"

    assert api.run(main) == "done"
    assert sorted(results) == list(range(600))


def test_cancel_sleeping_children(api):
    events = []

    async def child():
        try:
            events.append("start")
            await api.sleep_forever()
        finally:
            events.append("exit")

    async def main():
        async with api.open_nursery() as nursery:
            nursery.start_soon(child)
            await checkpoint(api)
            nursery.cancel_scope.cancel()

    api.run(main)
    assert events == ["start", "exit"]


def test_cancel_scope_level_cancellation(api):
    async def main():
        with api.CancelScope() as scope:
            scope.cancel()
            for _ in range(2):
                with pytest.raises(api.Cancelled):
                    await checkpoint(api)
            await checkpoint(api)
        assert scope.cancel_called
        assert scope.cancelled_caught

    api.run(main)


def test_shield_and_outer_cancellation(api):
    async def main():
        with api.CancelScope() as outer:
            outer.cancel()
            with api.CancelScope(shield=True):
                await checkpoint(api)
                await api.sleep(0.001)
            await checkpoint(api)
            pytest.fail("outer cancellation was ignored")
        assert outer.cancelled_caught

    api.run(main)


def test_child_failure_cancels_siblings(api):
    events = []

    async def sibling():
        try:
            await api.sleep_forever()
        finally:
            events.append("sibling exited")

    async def fail():
        await checkpoint(api)
        raise ValueError("child failed")

    async def main():
        async with api.open_nursery() as nursery:
            nursery.start_soon(sibling)
            nursery.start_soon(fail)

    with pytest.raises(ExceptionGroup) as exc:
        api.run(main)
    assert len(exc.value.exceptions) == 1
    assert isinstance(exc.value.exceptions[0], ValueError)
    assert events == ["sibling exited"]


def test_outer_cancel_during_nested_join(api):
    events = []

    async def main():
        with api.CancelScope() as outer:
            async def cancel():
                await checkpoint(api)
                outer.cancel()

            async def sleeper():
                try:
                    await api.sleep_forever()
                finally:
                    events.append("exit")

            async with api.open_nursery() as nursery:
                nursery.start_soon(cancel)
                async with api.open_nursery() as nested:
                    nested.start_soon(sleeper)
            pytest.fail("outer cancellation was ignored")
        assert outer.cancelled_caught

    api.run(main)
    assert events == ["exit"]
