# API overview

Trior is an experimental runtime for CPython 3.12. Linux x86_64 (epoll)
and macOS ARM64 (kqueue) run the project's regression suite. Both platforms
also exercise the poll backend. See the [README](../README.md) to build
Trior locally.

## Starting and joining tasks

Call `trior.run(async_fn, *args)` from synchronous code. It runs the
coroutine to completion and returns its result. Inside it,
`async with trior.open_nursery()` groups child tasks and waits for them
before exiting. Use `nursery.start_soon()` to schedule a child, or
`await nursery.start()` to wait for a child to signal readiness.

```python
import trior


async def worker(*, task_status=trior.TASK_STATUS_IGNORED):
    task_status.started("ready")
    await trior.sleep(0.01)


async def main():
    async with trior.open_nursery() as nursery:
        status = await nursery.start(worker)
        print(status)


trior.run(main)
```

## Passing data between tasks

`trior.open_memory_channel(capacity)` returns a send and a receive
endpoint. Use capacity `0` for an unbuffered handoff. A receiver using
`async for` stops once all send endpoints are closed and any buffered
values have been consumed.

```python
import trior


async def produce(send):
    async with send:
        await send.send("hello")


async def main():
    send, receive = trior.open_memory_channel(0)
    async with trior.open_nursery() as nursery:
        nursery.start_soon(produce, send)
        async with receive:
            async for message in receive:
                print(message)


trior.run(main)
```

## Supported areas

| Area | APIs |
|---|---|
| Scheduling and time | `run`, `checkpoint`, `current_time`, `sleep`, `sleep_until`, `sleep_forever` |
| Task lifecycle | `open_nursery`, `Nursery.start_soon`, `Nursery.start`, `TaskStatus`, `CancelScope` with deadline and shield |
| Synchronization | `Event`, `Lock`, `Semaphore`, memory channels |
| Descriptor readiness | `trior.lowlevel.wait_readable`, `wait_writable`, `notify_closing` |
| Socket facade | `socket`, `socketpair`, `from_stdlib_socket`, async `recv`, `recv_into`, `send`, `accept` |

The compatibility target is Trio 0.35.0. The current implementation covers
the cases exercised by Trior's own tests. Nursery methods accept the `name`
argument, with task name tracking still pending. TCP connect, high-level
streams, DNS, thread bridges, guest mode and instrumentation are future work.
See the [handoff](HANDOFF.md) and [roadmap](ROADMAP.md) for specific gaps.
