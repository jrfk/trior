"""Attribute ready recv cost to scheduling and Trio's socket wrapper."""

import json
import os
import random
import socket
import statistics
import subprocess
import sys
import time

import trio

MODES = ("raw", "checkpoints", "stock", "inline")
PAYLOAD = b"x" * 4000
BATCHES = 8


async def inline(self, wait_fn, fn, *args, **kwargs):
    """Experimental replacement for the generic socket helper."""
    await trio.lowlevel.checkpoint_if_cancelled()
    try:
        result = fn(self._sock, *args, **kwargs)
    except BlockingIOError:
        pass
    except BaseException:
        await trio.lowlevel.cancel_shielded_checkpoint()
        raise
    else:
        await trio.lowlevel.cancel_shielded_checkpoint()
        return result

    while True:
        await wait_fn(self._sock)
        try:
            return fn(self._sock, *args, **kwargs)
        except BlockingIOError:
            pass


async def sample(mode):
    left, right = socket.socketpair()
    try:
        left.setblocking(False)
        if mode == "inline":
            type(trio.socket.from_stdlib_socket(left))._nonblocking_helper = inline
        recv = (
            trio.socket.from_stdlib_socket(left).recv
            if mode in ("stock", "inline")
            else left.recv
        )
        check = trio.lowlevel.checkpoint_if_cancelled
        yield_task = trio.lowlevel.cancel_shielded_checkpoint
        start = time.process_time_ns()
        for _ in range(BATCHES):
            right.sendall(PAYLOAD)
            if mode == "raw":
                for _ in PAYLOAD:
                    assert recv(1) == b"x"
            elif mode == "checkpoints":
                for _ in PAYLOAD:
                    await check()
                    data = recv(1)
                    await yield_task()
                    assert data == b"x"
            else:
                for _ in PAYLOAD:
                    assert await recv(1) == b"x"
        return time.process_time_ns() - start
    finally:
        left.close()
        right.close()


def main():
    if len(sys.argv) == 2:
        print(trio.run(sample, sys.argv[1]))
        return
    if hasattr(os, "sched_setaffinity"):
        os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    randomizer = random.Random(31)
    rows = []
    for _ in range(7):
        order = list(MODES)
        randomizer.shuffle(order)
        rows.append({
            mode: int(subprocess.check_output([sys.executable, __file__, mode]))
            for mode in order
        })
    medians = {mode: statistics.median(row[mode] for row in rows) for mode in MODES}
    print(json.dumps({"python": sys.version, "trio": trio.__version__,
                      "recv_count": len(PAYLOAD) * BATCHES,
                      "cpu_ns_medians": medians, "cpu_ns_rounds": rows}, indent=2))


if __name__ == "__main__":
    main()
