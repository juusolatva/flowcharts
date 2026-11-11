"""Sample module exercising every construct the Python frontend supports.

Used by integration tests; it is parsed, never imported or executed.
"""

import json


class Inventory:
    def __init__(self, items):
        self._items = list(items)

    def find(self, name):
        for item in self._items:
            if item.name == name:
                break
        else:
            return None
        return item

    @property
    def size(self):
        return len(self._items)

    @size.setter
    def size(self, value):
        raise AttributeError("size is read-only")


def load(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as err:
        print(f"could not load {path!r}: {err}")
        return {}
    else:
        print("loaded \"%s\"\n" % path)
    finally:
        print("done")
    return data


def drain(queue):
    while True:
        try:
            job = queue.pop()
            if job is None:
                break
            if job.skip:
                continue
            job.run()
        finally:
            queue.task_done()
    return "drained"


def describe(command):
    match command:
        case {"action": "move", "to": target}:
            return f"moving to {target}"
        case [first, *rest] if rest:
            return f"{first} and {len(rest)} more"
        case _:
            return "unknown"


def make_counter(start=0):
    count = start

    def step(by=1):
        nonlocal count
        count += by
        return count

    return step


async def fetch_all(client, urls):
    results = []
    async for page in client.stream(urls):
        results.append(await page.text())
    return results
