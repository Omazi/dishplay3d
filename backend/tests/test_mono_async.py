"""The depth model on a thread of its own (reconstruction/mono_depth.py, AsyncMono).

The model fills what stereo cannot measure. It used to run inside the engine's own loop, so it was kept for
the finishing step only. It now works ahead of the engine, at the same time as stereo. While scanning nothing
may slow the scan down: a prediction that is not ready is simply not used, and when the computer cannot keep
up the model steps back by itself until the finishing step.

The real network is not run here: slow or fast stand-ins are.
"""
import threading
import time

import numpy as np
import pytest

from reconstruction.mono_depth import AsyncMono


class Fake:
    """Stands in for the network: answers after `delay` seconds with a map that identifies the picture."""

    def __init__(self, delay=0.0, fail_on=()):
        self.delay, self.fail_on = delay, set(fail_on)
        self.calls, self.threads, self.seconds = 0, set(), 0.0

    def predict(self, image_bgr, frame_id=None):
        self.threads.add(threading.get_ident())
        time.sleep(self.delay)
        self.calls += 1
        self.seconds += self.delay
        if frame_id in self.fail_on:
            raise RuntimeError("model failed on this picture")
        return np.full(image_bgr.shape[:2], float(image_bgr[0, 0, 0]), np.float32)


def img(v):
    return np.full((6, 8, 3), v, np.uint8)


def test_the_prediction_is_computed_on_another_thread_and_is_the_model_s_own():
    fake = Fake(0.02)
    m = AsyncMono(fake)
    try:
        m.request(7, img(70))
        out = m.predict(img(70), 7)
        assert out.shape == (6, 8) and float(out[0, 0]) == 70.0
        assert fake.threads and threading.get_ident() not in fake.threads
        # asked without having been requested first: still answered (finishing never goes without)
        assert float(m.predict(img(90), 9)[0, 0]) == 90.0
        assert fake.calls == 2 and m.stats()["computed"] == 2
    finally:
        m.close()


def test_work_asked_ahead_is_done_while_the_caller_is_busy():
    """The engine asks for the next pictures, then spends its time on stereo. Collecting three predictions must
    then cost almost nothing more: the model worked meanwhile."""
    fake = Fake(0.08)
    m = AsyncMono(fake)
    try:
        for k in range(3):
            m.request(k, img(k))
        time.sleep(0.30)                         # "stereo" of the caller
        t = time.perf_counter()
        outs = [m.predict(img(k), k) for k in range(3)]
        assert time.perf_counter() - t < 0.05
        assert [float(o[0, 0]) for o in outs] == [0.0, 1.0, 2.0]
    finally:
        m.close()


def test_while_scanning_a_late_prediction_is_skipped_not_waited_for():
    fake = Fake(0.5)
    m = AsyncMono(fake, live_patience_s=0.05)
    try:
        m.request(1, img(1), live=True)
        t = time.perf_counter()
        assert m.predict(img(1), 1, live=True) is None
        assert time.perf_counter() - t < 0.2, "the scan must not wait for the model"
        st = m.stats()
        assert st["late"] == 1 and st["on_time"] == 0
    finally:
        m.close()


def test_a_fast_model_is_on_time_while_scanning():
    fake = Fake(0.01)
    m = AsyncMono(fake, live_patience_s=0.2)
    try:
        for k in range(5):
            m.request(k, img(k), live=True)
            out = m.predict(img(k), k, live=True)
            assert out is not None and float(out[0, 0]) == float(k)
        st = m.stats()
        assert st["on_time"] == 5 and st["late"] == 0 and not st["stepped_back"]
    finally:
        m.close()


def test_a_computer_that_cannot_keep_up_makes_the_model_step_back():
    """A model four times slower than the scan: old requests are dropped instead of piling up, and after a
    dozen late answers the model is no longer asked during this scan."""
    fake = Fake(0.2)
    m = AsyncMono(fake, live_patience_s=0.01, ahead=2, give_up_after=10)
    try:
        t = time.perf_counter()
        for k in range(30):
            m.request(k, img(k), live=True)
            m.predict(img(k), k, live=True)
            time.sleep(0.02)                    # the scan goes on at its own pace
        took = time.perf_counter() - t
        st = m.stats()
        assert took < 30 * 0.02 + 30 * 0.01 + 0.6, took       # never the 6 s the model would have needed
        assert st["stepped_back"] and st["dropped"] > 0
        assert st["pending"] <= 2
        calls = fake.calls
        m.request(99, img(99), live=True)       # once stepped back, a live request costs nothing
        time.sleep(0.3)
        assert fake.calls <= calls + 2 and m.predict(img(99), 99, live=True) is None
        # the finishing step is in no hurry: it still gets every prediction
        assert float(m.predict(img(123), 123)[0, 0]) == 123.0
    finally:
        m.close()


def test_a_failure_of_the_model_is_reported_to_the_caller_and_does_not_stop_the_thread():
    fake = Fake(0.0, fail_on={2})
    m = AsyncMono(fake)
    try:
        m.request(2, img(2))
        with pytest.raises(RuntimeError):
            m.predict(img(2), 2)
        assert float(m.predict(img(3), 3)[0, 0]) == 3.0
        assert m.stats()["errors"] == 1
    finally:
        m.close()


def test_predictions_nobody_collects_do_not_pile_up():
    fake = Fake(0.0)
    m = AsyncMono(fake, keep=4)
    try:
        for k in range(20):
            m.request(k, img(k))
        deadline = time.time() + 2
        while fake.calls < 20 and time.time() < deadline:
            time.sleep(0.01)
        assert m.stats()["ready"] <= 4
    finally:
        m.close()
