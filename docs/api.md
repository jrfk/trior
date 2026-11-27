# API overview

Trior is an experimental runtime for CPython 3.12. Linux x86_64 (epoll)
and macOS ARM64 (kqueue) run the project's regression suite. Both platforms
also exercise the poll backend. See the [README](../README.md) to build
Trior locally.

## Implemented APIs

The compatibility target is Trio 0.35.0. This table describes Trior's current
API surface. The [technical handoff](HANDOFF.md#verified-scope-and-current-limitations)
tracks compatibility gaps and the cases covered by regression tests.

| Area | APIs |
|---|---|
| Run and timers | `run`, `current_time`, `sleep`, `sleep_until`, `sleep_forever` |
| Nurseries | `open_nursery`, `Nursery.start_soon`, `Nursery.start`, `Nursery.cancel_scope`, `TaskStatus.started`, `TASK_STATUS_IGNORED` |
| Cancellation | `CancelScope` with `cancel()`, `deadline`, `shield`, `cancel_called` and `cancelled_caught`; `Cancelled` |
| Synchronization | `Event` (`set`, `is_set`, `wait`); `Lock` and `Semaphore` (`acquire`, `acquire_nowait`, `release`, async context managers); `Lock.locked`, `Semaphore.value`, `Semaphore.max_value` |
| Memory channels | `open_memory_channel`, `MemorySendChannel` (`send`, `send_nowait`), `MemoryReceiveChannel` (`receive`, `receive_nowait`, async iteration); both endpoints support `clone`, `close`, `aclose` and context managers |
| Checkpoints and descriptor readiness | `trior.checkpoint`; under `trior.lowlevel`, `checkpoint`, `checkpoint_if_cancelled`, `cancel_shielded_checkpoint`, `wait_readable`, `wait_writable` and `notify_closing` |
| Socket facade | Under `trior.socket`, `socket`, `socketpair`, `from_stdlib_socket` and `SocketType`. Async operations include `recv`, `recv_into`, `send` and `accept`. Synchronous operations include `bind`, `listen`, `getsockname`, `setsockopt`, `shutdown`, `fileno`, `close` and context managers. |
| Resource and channel exceptions | `BusyResourceError`, `ClosedResourceError`, `BrokenResourceError`, `WouldBlock`, `EndOfChannel` |

Nursery methods accept the `name` argument. Task name tracking and startup
into a non-ancestor nursery are still pending.

## Planned APIs

These entries use Trio API names to describe the target scope.

| Stage | Target scope |
|---|---|
| [21 · TCP streams](ROADMAP.md#stage-21--tcp-streams) | Nonblocking `SocketType.connect`, `SocketStream`, `SocketListener`, `open_tcp_stream` and `open_tcp_listeners`, starting with numeric IP addresses. Stream operations include `send_all`, `receive_some`, `send_eof` and `aclose`. |
| [22 · DNS and connection fallback](ROADMAP.md#follow-up-details) | Async address resolution (`trio.socket.getaddrinfo` and `getnameinfo`) and Happy Eyeballs for hostname-based connections |
| [25 · Thread bridge](ROADMAP.md#follow-up-details) | Thread interoperability under `trio.to_thread` and `trio.from_thread` |

Guest mode (`trio.lowlevel.start_guest_run`) and instrumentation
(`trio.abc.Instrument` and `trio.lowlevel.add_instrument` / `remove_instrument`) are open compatibility gaps.
The [roadmap](ROADMAP.md) tracks the broader compatibility work.

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
