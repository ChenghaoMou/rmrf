import inspect
from types import FrameType
from typing import BinaryIO

from rmscene.scene_stream import read_blocks


def current_stack_trace():
    """Get the current stack frames.

    Returns:
        List[FrameType]: A list of frame objects representing the current call stack,
        ordered from oldest (bottom) to most recent (top).
    """
    frames = inspect.stack()
    call_stack = []
    started = False

    for frame in frames:
        function = frame.function
        if "self" in frame.frame.f_locals:
            full_name = f"{frame.frame.f_locals['self'].__class__.__name__}.{function}"
        else:
            full_name = function
        if not started and full_name != "HookedStream.read":
            continue
        started = True
        if full_name == "HookedStream.read":
            continue
        if function == "read_blocks":
            break
        call_stack.append(full_name)
    
    # print(" -> ".join(call_stack))
    return call_stack

class HookedStream:

    def __init__(self, f: str | BinaryIO):
        self.fh = open(f, "rb") if isinstance(f, str) else f
        self.traces = []

    def read(self, size: int, silent: bool = False) -> bytes:
        data = self.fh.read(size)
        if not silent:
            frames = current_stack_trace()
            self.traces.append(("read", size, data.hex(), frames))
        return data

    def tell(self) -> int:
        return self.fh.tell()
    
    def seek(self, offset: int, whence: int = 0) -> int:
        return self.fh.seek(offset, whence)

    def close(self) -> None:
        return self.fh.close()
    
    def all_traces(self) -> list[tuple[str, int, str, list[str]]]:
        results = self.traces
        self.traces = []
        return results


def hooked_read(f: str | BinaryIO) -> list[tuple[type, int, int, str, list[tuple[str, int, str, list[str]]]]]:
    results = []
    start = 0
    fh = HookedStream(f)
    for block in read_blocks(fh):
        end = fh.tell()
        traces = fh.all_traces()
        fh.seek(start)
        results.append((block, start, end, fh.read(end - start, silent=True).hex(), traces))
        start = end
    fh.close()
    return results

if __name__ == "__main__":
    hooked_read("/Users/chenghao/Developer/rmscene/tests/data/Color_and_tool_v3.14.4.rm")
