"""Behavioral smoke tests shared by the original and native batch schedulers.

These are deliberately ordinary pytest functions calling trio.run(). They do
not depend on pytest-trio or on the private native implementation.
"""

from __future__ import annotations

import contextvars
import gc
import queue
import threading
import time
import types
import weakref

import outcome
import pytest
import trio
from trio import lowlevel
from trio.testing import MockClock, assert_checkpoints, wait_all_tasks_blocked

try:
    BaseExceptionGroup
except NameError:  # Python 3.10 is supported by Trio 0.35.
    from exceptiongroup import BaseExceptionGroup, ExceptionGroup


def test_context_isolation_and_task_identity():
    variable = contextvars.ContextVar("compat_variable", default="outside")
    observed = {}

    async def child(label):
        assert variable.get() == "parent"
        task = lowlevel.current_task()
        variable.set(label)
        with assert_checkpoints():
            await lowlevel.checkpoint()
        assert lowlevel.current_task() is task
        assert task.context.get(variable) == label
        assert task.parent_nursery is not None
        observed[label] = variable.get()

    async def main():
        variable.set("parent")
        async with trio.open_nursery() as nursery:
            nursery.start_soon(child, "left")
            nursery.start_soon(child, "right")
        assert variable.get() == "parent"

    trio.run(main)
    assert observed == {"left": "left", "right": "right"}
    assert variable.get() == "outside"


def test_nursery_start_handshake_and_exit_joins_child():
    events = []

    async def child(release, *, task_status=trio.TASK_STATUS_IGNORED):
        events.append("initialized")
        task_status.started(42)
        await release.wait()
        await lowlevel.checkpoint()
        events.append("finished")

    async def main():
        release = trio.Event()
        async with trio.open_nursery() as nursery:
            assert await nursery.start(child, release) == 42
            assert events == ["initialized"]
            events.append("parent_received_start")
            release.set()
        events.append("nursery_exited")

    trio.run(main)
    assert events == [
        "initialized",
        "parent_received_start",
        "finished",
        "nursery_exited",
    ]


def test_exception_group_propagates_after_sibling_cleanup():
    events = []

    async def waiting_child(started):
        started.set()
        try:
            await trio.sleep_forever()
        finally:
            with trio.CancelScope(shield=True):
                await lowlevel.checkpoint()
                events.append("cleanup_finished")

    async def failing_child():
        raise ValueError("child failed")

    async def main():
        started = trio.Event()
        async with trio.open_nursery() as nursery:
            nursery.start_soon(waiting_child, started)
            await started.wait()
            nursery.start_soon(failing_child)

    with pytest.raises(ExceptionGroup) as captured:
        trio.run(main)

    def leaves(error):
        if isinstance(error, BaseExceptionGroup):
            return [leaf for nested in error.exceptions for leaf in leaves(nested)]
        return [error]

    errors = leaves(captured.value)
    assert len(errors) == 1
    assert isinstance(errors[0], ValueError)
    assert str(errors[0]) == "child failed"
    assert events == ["cleanup_finished"]


def test_level_cancellation_and_shielded_checkpoints():
    events = []

    async def main():
        with trio.CancelScope() as scope:
            scope.cancel()
            for index in range(2):
                with pytest.raises(trio.Cancelled):
                    await lowlevel.checkpoint()
                events.append(f"cancelled_{index}")
            with trio.CancelScope(shield=True):
                with assert_checkpoints():
                    await lowlevel.checkpoint()
                events.append("shielded")
            with pytest.raises(trio.Cancelled):
                await lowlevel.checkpoint()
            events.append("cancelled_after_shield")
        assert scope.cancel_called
        # The user caught every cancellation; the scope itself caught none.
        assert not scope.cancelled_caught

    trio.run(main)
    assert events == [
        "cancelled_0", "cancelled_1", "shielded", "cancelled_after_shield"
    ]


def test_deadline_updates_and_mock_clock():
    clock = MockClock(rate=0, autojump_threshold=0)

    async def main():
        with trio.CancelScope(deadline=2) as scope:
            scope.deadline = 5
            await trio.sleep(3)
            assert trio.current_time() == 3
            assert not scope.cancel_called
            scope.deadline = 4
            await trio.sleep_forever()
            pytest.fail("deadline should cancel the sleeping task")
        assert scope.cancel_called
        assert scope.cancelled_caught
        assert trio.current_time() == 4

    trio.run(main, clock=clock)


def test_cancelled_receive_does_not_consume_buffered_message():
    async def main():
        send, receive = trio.open_memory_channel(1)
        async with send, receive:
            marker = object()
            send.send_nowait(marker)
            with trio.CancelScope() as scope:
                scope.cancel()
                await receive.receive()
                pytest.fail("already-cancelled receive must not succeed")
            assert scope.cancelled_caught
            assert receive.receive_nowait() is marker

    trio.run(main)


def test_cancelled_blocked_send_does_not_deliver_later():
    async def main():
        send, receive = trio.open_memory_channel(0)
        done = trio.Event()
        discarded = object()
        retained = object()

        async def sender(*, task_status=trio.TASK_STATUS_IGNORED):
            with trio.CancelScope() as scope:
                task_status.started(scope)
                await send.send(discarded)
                pytest.fail("cancelled blocked send unexpectedly completed")
            assert scope.cancelled_caught
            done.set()

        async with send, receive, trio.open_nursery() as nursery:
            scope = await nursery.start(sender)
            await wait_all_tasks_blocked()
            scope.cancel()
            await done.wait()
            nursery.start_soon(send.send, retained)
            assert await receive.receive() is retained

    trio.run(main)


def test_lowlevel_successful_abort_runs_once():
    calls = []

    async def main():
        done = trio.Event()

        async def child(*, task_status=trio.TASK_STATUS_IGNORED):
            with trio.CancelScope() as scope:
                task_status.started(scope)

                def abort(raise_cancel):
                    calls.append(raise_cancel)
                    return lowlevel.Abort.SUCCEEDED

                await lowlevel.wait_task_rescheduled(abort)
                pytest.fail("successful abort must deliver cancellation")
            assert scope.cancelled_caught
            done.set()

        async with trio.open_nursery() as nursery:
            scope = await nursery.start(child)
            await wait_all_tasks_blocked()
            scope.cancel()
            scope.cancel()
            await done.wait()

    trio.run(main)
    assert len(calls) == 1


@pytest.mark.parametrize("deliver_cancel", [False, True])
def test_lowlevel_failed_abort_can_complete_or_deliver_cancel(deliver_cancel):
    callbacks = []
    results = []

    async def main():
        done = trio.Event()

        async def child(*, task_status=trio.TASK_STATUS_IGNORED):
            task = lowlevel.current_task()
            with trio.CancelScope() as scope:
                task.custom_sleep_data = "waiting"
                task_status.started((scope, task))

                def abort(raise_cancel):
                    callbacks.append(raise_cancel)
                    return lowlevel.Abort.FAILED

                result = await lowlevel.wait_task_rescheduled(abort)
                assert task.custom_sleep_data is None
                results.append(result)
            assert scope.cancel_called
            assert scope.cancelled_caught is deliver_cancel
            assert task.custom_sleep_data is None
            done.set()

        async with trio.open_nursery() as nursery:
            scope, task = await nursery.start(child)
            await wait_all_tasks_blocked()
            assert task.custom_sleep_data == "waiting"
            scope.cancel()
            scope.cancel()
            await lowlevel.checkpoint()
            assert len(callbacks) == 1
            assert not done.is_set()
            result = (
                outcome.capture(callbacks[0])
                if deliver_cancel
                else outcome.Value("finished")
            )
            lowlevel.reschedule(task, result)
            await done.wait()

    trio.run(main)
    assert len(callbacks) == 1
    assert results == ([] if deliver_cancel else ["finished"])


def test_instrument_step_pairs_and_sync_reentry():
    class Recorder(trio.abc.Instrument):
        def __init__(self):
            self.active = None
            self.before_count = 0
            self.after_count = 0
            self.spawned = set()
            self.exited = set()
            self.ended = False

        def task_spawned(self, task):
            self.spawned.add(task)

        def task_exited(self, task):
            self.exited.add(task)

        def before_task_step(self, task):
            assert self.active is None
            self.active = task
            self.before_count += 1
            # Re-enter a synchronous Trio API from an Instrument callback.
            assert lowlevel.current_statistics().tasks_living >= 1

        def after_task_step(self, task):
            assert self.active is task
            self.active = None
            self.after_count += 1
            lowlevel.current_statistics()

        def after_run(self):
            assert self.active is None
            self.ended = True

    recorder = Recorder()

    async def child():
        await lowlevel.checkpoint()

    async def main():
        async with trio.open_nursery() as nursery:
            for _ in range(5):
                nursery.start_soon(child)

    trio.run(main, instruments=[recorder])
    assert recorder.ended
    assert recorder.before_count == recorder.after_count
    assert recorder.before_count > 5
    assert recorder.spawned == recorder.exited


def test_checkpoint_reschedule_hook_sees_queued_task_state():
    class Recorder(trio.abc.Instrument):
        def __init__(self):
            self.running = None
            self.checkpoint_schedules = 0

        def before_task_step(self, task):
            self.running = task

        def task_scheduled(self, task):
            if task is self.running:
                self.checkpoint_schedules += 1
                assert task in task._runner.runq
                assert task._next_send_fn.__self__ is task.coro
                assert task._next_send_fn.__name__ == "send"
                assert isinstance(task._next_send, outcome.Value)
                assert task._next_send.value is None
                assert task._abort_func is None
                assert task.custom_sleep_data is None

        def after_task_step(self, task):
            assert self.running is task
            self.running = None

    recorder = Recorder()

    async def main():
        for _ in range(3):
            await lowlevel.checkpoint()

    trio.run(main, instruments=[recorder])
    assert recorder.checkpoint_schedules >= 3


def test_worker_thread_can_call_back_into_trio():
    main_thread = threading.get_ident()
    seen = []

    async def asynchronous_callback(value):
        seen.append(("async", threading.get_ident()))
        await lowlevel.checkpoint()
        return value + 1

    def synchronous_callback(value):
        seen.append(("sync", threading.get_ident()))
        return value * 2

    def worker():
        assert threading.get_ident() != main_thread
        first = trio.from_thread.run(asynchronous_callback, 20)
        return trio.from_thread.run_sync(synchronous_callback, first)

    async def main():
        return await trio.to_thread.run_sync(worker)

    assert trio.run(main) == 42
    assert seen == [("async", main_thread), ("sync", main_thread)]


def test_async_generator_finalized_before_run_returns():
    events = []
    retained_generators = []

    async def generator():
        try:
            yield 1
        finally:
            with trio.CancelScope(shield=True):
                await lowlevel.checkpoint()
                events.append("finalized")

    async def main():
        instance = generator()
        retained_generators.append(instance)
        assert await instance.__anext__() == 1

    trio.run(main)
    assert events == ["finalized"]
    assert retained_generators[0].ag_frame is None


def test_invalid_yield_delivers_type_error_to_coroutine():
    @types.coroutine
    def foreign_awaitable():
        yield object()

    async def main():
        with pytest.raises(TypeError, match="unrecognized yield message"):
            await foreign_awaitable()
        await lowlevel.checkpoint()
        return "recovered"

    assert trio.run(main) == "recovered"


def test_completed_coroutine_does_not_retain_its_argument():
    references = []

    class Payload:
        pass

    async def child(payload):
        await lowlevel.checkpoint()
        assert isinstance(payload, Payload)

    async def main():
        payload = Payload()
        references.append(weakref.ref(payload))
        async with trio.open_nursery() as nursery:
            nursery.start_soon(child, payload)
            del payload

    trio.run(main)
    gc.collect()
    assert references[0]() is None


def test_guest_mode_completes_on_host_thread():
    callbacks = queue.Queue()
    finished = []
    host_thread = threading.get_ident()
    child_threads = []

    async def child():
        await lowlevel.checkpoint()
        child_threads.append(threading.get_ident())

    async def main():
        async with trio.open_nursery() as nursery:
            nursery.start_soon(child)
            # Exercise the host/IO waiting path as well as runnable batches.
            await trio.sleep(0.001)
        return 42

    lowlevel.start_guest_run(
        main,
        run_sync_soon_threadsafe=callbacks.put,
        run_sync_soon_not_threadsafe=callbacks.put,
        done_callback=finished.append,
    )
    deadline = time.monotonic() + 5
    while not finished:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            pytest.fail("guest run did not finish within five seconds")
        callback = callbacks.get(timeout=remaining)
        callback()
    assert len(finished) == 1
    assert finished[0].unwrap() == 42
    assert child_threads == [host_thread]
