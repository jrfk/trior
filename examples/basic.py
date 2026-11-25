"""Run multiple workers in a nursery."""
import trior


async def worker(number):
    await trior.sleep(0.01)
    print(number)


async def main():
    async with trior.open_nursery() as nursery:
        for number in range(3):
            nursery.start_soon(worker, number)


if __name__ == "__main__":
    trior.run(main)
