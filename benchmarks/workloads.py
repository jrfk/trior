"""Equal-work Trio workloads; execution backend is chosen by the caller.

All assertions are deliberately kept in every backend. This measures complete
operations, not an empty scheduler with bookkeeping disabled.
"""

from __future__ import annotations

from typing import Any

import trio


CASES: dict[str, dict[str, Any]] = {
    "checkpoint_1": {
        "kind": "cpu", "description": "One runnable task, explicit checkpoints",
        "base": {"tasks": 1, "steps": 10000}, "scale_key": "steps",
    },
    "checkpoint_600": {
        "kind": "cpu", "description": "600 runnable tasks, explicit checkpoints",
        "base": {"tasks": 600, "steps": 20}, "scale_key": "steps",
    },
    "checkpoint_deep": {
        "kind": "cpu", "description": "10 tasks with a 32-level await chain",
        "base": {"tasks": 10, "steps": 100, "depth": 32}, "scale_key": "steps",
    },
    "channel_0": {
        "kind": "cpu", "description": "Rendezvous channel request/reply",
        "base": {"roundtrips": 2000, "capacity": 0}, "scale_key": "roundtrips",
    },
    "channel_64": {
        "kind": "cpu", "description": "Buffered channel request/reply",
        "base": {"roundtrips": 2000, "capacity": 64}, "scale_key": "roundtrips",
    },
    "nursery_spawn": {
        "kind": "cpu", "description": "Batches of 100 short-lived tasks",
        "base": {"batches": 20, "tasks_per_batch": 100}, "scale_key": "batches",
    },
    "deadline_churn": {
        "kind": "cpu", "description": "Create, change and remove live deadlines",
        "base": {"iterations": 3000, "yield_every": 16}, "scale_key": "iterations",
    },
    "cancel_fanout": {
        "kind": "cpu", "description": "Cancel 600 blocked children together",
        "base": {"batches": 2, "tasks_per_batch": 600}, "scale_key": "batches",
    },
    "mixed_600": {
        "kind": "latency", "description": "580 idle + 20 periodic workers; separate observer task",
        "base": {"tasks": 600, "active_tasks": 20, "samples": 200,
                 "probe_period_s": 0.002, "worker_period_ticks": 4, "payload_terms": 64},
        "scale_key": None,
    },
}


def parameters(name: str, scale: int = 1, quick: bool = False) -> dict[str, Any]:
    case = CASES[name]
    result = dict(case["base"])
    if case["scale_key"]:
        result[case["scale_key"]] *= scale
    elif quick:
        result["samples"] = 80
    return result


async def checkpoint_work(tasks: int, steps: int, depth: int = 0) -> dict[str, Any]:
    completed = [0] * tasks

    async def nested(level: int) -> None:
        if level:
            await nested(level - 1)
        else:
            await trio.lowlevel.checkpoint()

    async def worker(index: int) -> None:
        for _ in range(steps):
            if depth:
                await nested(depth)
            else:
                await trio.lowlevel.checkpoint()
            completed[index] += 1

    async with trio.open_nursery() as nursery:
        for index in range(tasks):
            nursery.start_soon(worker, index)
    assert completed == [steps] * tasks
    return {"operations": tasks * steps, "unit": "checkpoints", "completed_tasks": tasks}


async def channel_work(roundtrips: int, capacity: int) -> dict[str, Any]:
    tx, rx = trio.open_memory_channel[int](capacity)
    replies, responses = trio.open_memory_channel[int](capacity)
    received = 0
    checksum = 0

    async def echo() -> None:
        nonlocal received
        async with rx, replies:
            async for value in rx:
                assert value == received
                received += 1
                await replies.send(value)

    async with trio.open_nursery() as nursery:
        nursery.start_soon(echo)
        async with tx, responses:
            for value in range(roundtrips):
                await tx.send(value)
                answer = await responses.receive()
                assert answer == value
                checksum += answer
    assert received == roundtrips
    assert checksum == roundtrips * (roundtrips - 1) // 2
    return {"operations": roundtrips, "unit": "roundtrips", "messages": 2 * received,
            "checksum": checksum}


async def nursery_work(batches: int, tasks_per_batch: int) -> dict[str, Any]:
    completed = 0

    async def child() -> None:
        nonlocal completed
        await trio.lowlevel.checkpoint()
        completed += 1

    for _ in range(batches):
        async with trio.open_nursery() as nursery:
            for _ in range(tasks_per_batch):
                nursery.start_soon(child)
    assert completed == batches * tasks_per_batch
    return {"operations": completed, "unit": "spawned_and_joined_tasks"}


async def deadline_work(iterations: int, yield_every: int) -> dict[str, Any]:
    base = trio.current_time() + 3600
    scopes = 0
    checkpoints = 0
    for index in range(iterations):
        with trio.CancelScope(deadline=base + 1) as scope:
            scope.deadline = base + 2 + (index % 17)
            scope.deadline = base + 30
            if index % yield_every == 0:
                checkpoints += 1
                await trio.lowlevel.checkpoint()
        assert not scope.cancel_called
        scopes += 1
    assert scopes == iterations
    return {"operations": scopes, "unit": "scope_lifecycles", "deadline_updates": 2 * scopes,
            "explicit_checkpoints": checkpoints}


async def cancel_work(batches: int, tasks_per_batch: int) -> dict[str, Any]:
    exited_total = 0
    for _ in range(batches):
        ready = 0
        exited = 0
        all_ready = trio.Event()

        async def child() -> None:
            nonlocal ready, exited
            ready += 1
            if ready == tasks_per_batch:
                all_ready.set()
            try:
                await trio.sleep_forever()
            finally:
                exited += 1

        async with trio.open_nursery() as nursery:
            for _ in range(tasks_per_batch):
                nursery.start_soon(child)
            await all_ready.wait()
            nursery.cancel_scope.cancel()
        assert ready == tasks_per_batch
        assert exited == tasks_per_batch
        exited_total += exited
    return {"operations": exited_total, "unit": "cancelled_children", "batches": batches}


async def mixed_work(tasks: int, active_tasks: int, samples: int, probe_period_s: float,
                     worker_period_ticks: int, payload_terms: int) -> dict[str, Any]:
    """A synthetic load, not a robot/application benchmark.

    Probes use predetermined absolute deadlines. Slow probes do not reduce the
    number of observations, preventing closed-loop coordinated omission.
    """
    assert 0 < active_tasks < tasks
    assert samples % worker_period_ticks == 0
    ready = 0
    exited = 0
    workers_done = 0
    all_ready = trio.Event()
    start = trio.Event()
    active_done = trio.Event()
    anchor = 0.0
    work_steps = samples // worker_period_ticks
    work_counts = [0] * active_tasks
    checksums = [0] * active_tasks
    expected_payload = sum(value * value for value in range(payload_terms))
    timer_late_ns: list[int] = []
    checkpoint_ns: list[int] = []

    async def child(index: int) -> None:
        nonlocal ready, exited, workers_done
        ready += 1
        if ready == tasks:
            all_ready.set()
        try:
            await start.wait()
            if index >= active_tasks:
                await trio.sleep_forever()
            else:
                for step in range(1, work_steps + 1):
                    await trio.sleep_until(anchor + step * worker_period_ticks * probe_period_s)
                    checksums[index] += sum(value * value for value in range(payload_terms))
                    work_counts[index] += 1
                    await trio.lowlevel.checkpoint()
                workers_done += 1
                if workers_done == active_tasks:
                    active_done.set()
        finally:
            exited += 1

    async with trio.open_nursery() as nursery:
        for index in range(tasks):
            nursery.start_soon(child, index)
        await all_ready.wait()
        anchor = trio.current_time()
        start.set()
        for tick in range(1, samples + 1):
            intended = anchor + tick * probe_period_s
            await trio.sleep_until(intended)
            observed = trio.current_time()
            timer_late_ns.append(round(max(0.0, observed - intended) * 1e9))
            await trio.lowlevel.checkpoint()
            checkpoint_ns.append(round((trio.current_time() - observed) * 1e9))
        await active_done.wait()
        nursery.cancel_scope.cancel()
    assert ready == exited == tasks
    assert work_counts == [work_steps] * active_tasks
    assert checksums == [work_steps * expected_payload] * active_tasks
    assert len(timer_late_ns) == len(checkpoint_ns) == samples
    return {
        "operations": active_tasks * work_steps, "unit": "periodic_worker_steps",
        "probe_count": samples, "nominal_probe_span_s": samples * probe_period_s,
        "application_tasks": tasks, "observer_tasks": 1,
        "completed_tasks": exited, "checksum": sum(checksums),
        "latency_samples_ns": {"timer_lateness": timer_late_ns, "checkpoint": checkpoint_ns},
    }


async def execute(name: str, params: dict[str, Any]) -> dict[str, Any]:
    if name.startswith("checkpoint_"):
        return await checkpoint_work(**params)
    if name.startswith("channel_"):
        return await channel_work(**params)
    if name == "nursery_spawn":
        return await nursery_work(**params)
    if name == "deadline_churn":
        return await deadline_work(**params)
    if name == "cancel_fanout":
        return await cancel_work(**params)
    if name == "mixed_600":
        return await mixed_work(**params)
    raise ValueError(f"Unknown workload: {name}")
