"""Tests for the SSE subscriber queue bound, drop-on-full behaviour, and the
listener-thread liveness check used by the systemd watchdog heartbeat.
"""

import asyncio
import threading

from app import listener


def test_subscribe_bounds_queue_size():
    loop = asyncio.new_event_loop()
    queue = listener.subscribe("obs_st", loop)
    try:
        assert queue.maxsize == listener._SUBSCRIBER_QUEUE_MAXSIZE
    finally:
        listener.unsubscribe("obs_st", loop, queue)
        loop.close()


def test_put_nowait_safe_drops_newest_when_full():
    queue = asyncio.Queue(maxsize=2)
    queue.put_nowait("a")
    queue.put_nowait("b")

    listener._put_nowait_safe(queue, "c")  # must not raise QueueFull

    assert queue.qsize() == 2
    assert queue.get_nowait() == "a"
    assert queue.get_nowait() == "b"


def test_get_subscriber_counts_reflects_subscribe_and_unsubscribe():
    loop = asyncio.new_event_loop()
    before = listener.get_subscriber_counts()["obs_st"]
    q1 = listener.subscribe("obs_st", loop)
    q2 = listener.subscribe("obs_st", loop)
    try:
        assert listener.get_subscriber_counts()["obs_st"] == before + 2
    finally:
        listener.unsubscribe("obs_st", loop, q1)
        listener.unsubscribe("obs_st", loop, q2)
        loop.close()
    assert listener.get_subscriber_counts()["obs_st"] == before


def test_listener_thread_alive_tracks_a_thread_named_udp_listener():
    assert listener.listener_thread_alive() is False

    stop = threading.Event()
    t = threading.Thread(target=stop.wait, name="udp-listener", daemon=True)
    t.start()
    try:
        assert listener.listener_thread_alive() is True
    finally:
        stop.set()
        t.join(timeout=1)

    assert listener.listener_thread_alive() is False
