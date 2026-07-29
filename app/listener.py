import asyncio
import json
import socket
import threading
from typing import Optional

from app.parser import parse_message, UDP_PORT, BUFFER_SIZE

_state: dict = {
    "obs_st": None,
    "rapid_wind": None,
    "hub_status": None,
    "device_status": None,
    "evt_precip": None,
    "evt_strike": None,
}
_state_lock = threading.Lock()

# Keys are msg_type strings plus "*" for all-messages subscribers.
# Values are lists of (event_loop, asyncio.Queue) pairs.
_subscribers: dict = {"*": [], "obs_st": [], "rapid_wind": []}
_subscribers_lock = threading.Lock()

_started = threading.Event()

# Bounds how far a slow/dead SSE subscriber can lag before we drop new
# messages for it instead of growing its queue (and the process's memory)
# without limit. ~10 minutes of rapid_wind backlog (fires every ~3s).
_SUBSCRIBER_QUEUE_MAXSIZE = 200


def _listener_thread() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(1.0)
    sock.bind(("", UDP_PORT))

    while True:
        try:
            data, _ = sock.recvfrom(BUFFER_SIZE)
        except socket.timeout:
            continue

        try:
            raw = json.loads(data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue

        parsed = parse_message(raw)
        if parsed is None:
            continue

        msg_type = parsed["type"]

        with _state_lock:
            _state[msg_type] = parsed["data"]

        with _subscribers_lock:
            targets = list(_subscribers.get("*", [])) + list(_subscribers.get(msg_type, []))

        for loop, queue in targets:
            loop.call_soon_threadsafe(_put_nowait_safe, queue, parsed)


def _put_nowait_safe(queue: "asyncio.Queue", parsed: dict) -> None:
    """Drop the message if a subscriber's queue is full instead of raising.

    Runs on the event loop thread (scheduled via call_soon_threadsafe). A
    stalled/half-open SSE client would otherwise queue every message forever;
    bounding the queue (see subscribe()) and dropping the overflow here keeps
    a dead subscriber from growing process memory without limit.
    """
    try:
        queue.put_nowait(parsed)
    except asyncio.QueueFull:
        pass


def start_listener() -> None:
    if _started.is_set():
        return
    _started.set()
    t = threading.Thread(target=_listener_thread, daemon=True, name="udp-listener")
    t.start()


def get_state(msg_type: str) -> Optional[dict]:
    with _state_lock:
        return _state.get(msg_type)


def subscribe(msg_type: str, loop: asyncio.AbstractEventLoop) -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue(maxsize=_SUBSCRIBER_QUEUE_MAXSIZE)
    with _subscribers_lock:
        if msg_type not in _subscribers:
            _subscribers[msg_type] = []
        _subscribers[msg_type].append((loop, queue))
    return queue


def unsubscribe(msg_type: str, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue) -> None:
    with _subscribers_lock:
        bucket = _subscribers.get(msg_type, [])
        try:
            bucket.remove((loop, queue))
        except ValueError:
            pass


def get_subscriber_counts() -> dict:
    with _subscribers_lock:
        return {msg_type: len(bucket) for msg_type, bucket in _subscribers.items()}


def listener_thread_alive() -> bool:
    return any(t.name == "udp-listener" and t.is_alive() for t in threading.enumerate())
