"""Fixed work: many idle descriptors, one active socket round trip at a time."""
import argparse
import importlib
import json
import os
import socket
import statistics
import time

def trial(api, count, rounds):
    async def main():
        pairs = [socket.socketpair() for _ in range(count)]
        for a, b in pairs:
            a.setblocking(False)
            b.setblocking(False)
        async def idle(a):
            await api.lowlevel.wait_readable(a)
        try:
            async with api.open_nursery() as n:
                for a, b in pairs[1:]:
                    n.start_soon(idle, a)
                await api.sleep(0.01)
                a, b = pairs[0]
                for _ in range(rounds):
                    b.send(b"x")
                    await api.lowlevel.wait_readable(a)
                    assert a.recv(1) == b"x"
                n.cancel_scope.cancel()
        finally:
            for a, b in pairs:
                a.close()
                b.close()
    start, cpu = time.perf_counter(), time.process_time()
    api.run(main)
    return time.perf_counter()-start, time.process_time()-cpu

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("module")
    p.add_argument("--count", type=int, default=600)
    p.add_argument("--rounds", type=int, default=3000)
    p.add_argument("--repeat", type=int, default=5)
    args = p.parse_args()
    api = importlib.import_module(args.module)
    samples = [trial(api, args.count, args.rounds) for _ in range(args.repeat)]
    wall = statistics.median(x[0] for x in samples)
    cpu = statistics.median(x[1] for x in samples)
    print(json.dumps(dict(module=args.module, backend=os.environ.get("TRIOR_REACTOR", "default"),
        count=args.count, rounds=args.rounds, wall_s=wall, cpu_s=cpu,
        cpu_percent=100*cpu/wall, samples=samples)))
