"""Compare process CPU and wall time for local socket readiness at scale."""
import argparse
import importlib
import json
import socket
import statistics
import time

def trial(api, count, rounds):
    async def main():
        pairs = [socket.socketpair() for _ in range(count)]
        for a,b in pairs:
            a.setblocking(False)
            b.setblocking(False)
        async def receiver(a):
            for _ in range(rounds):
                await api.lowlevel.wait_readable(a)
                assert a.recv(1) == b"x"
        try:
            async with api.open_nursery() as n:
                for a,b in pairs:
                    n.start_soon(receiver, a)
                for _ in range(rounds):
                    # Let all receivers park before delivery.
                    await api.sleep(0.002)
                    for a,b in pairs:
                        b.send(b"x")
        finally:
            for a,b in pairs:
                a.close()
                b.close()
    wall, cpu = time.perf_counter(), time.process_time()
    api.run(main)
    return time.perf_counter()-wall, time.process_time()-cpu

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("module")
    parser.add_argument("--count", type=int, default=600)
    parser.add_argument("--rounds", type=int, default=30)
    parser.add_argument("--repeat", type=int, default=5)
    args = parser.parse_args()
    api = importlib.import_module(args.module)
    results = [trial(api,args.count,args.rounds) for _ in range(args.repeat)]
    wall = statistics.median(x[0] for x in results)
    cpu = statistics.median(x[1] for x in results)
    print(json.dumps(dict(module=args.module, count=args.count, rounds=args.rounds,
        wall_s=wall, cpu_s=cpu, cpu_percent=100*cpu/wall, samples=results)))
