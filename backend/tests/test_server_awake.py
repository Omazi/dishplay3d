"""The PC must not go to sleep while the calculator works: nobody touches it while dishes are scanned one after
the other, and a final calculation lasts a quarter of an hour. A sleeping PC shows as "calculateur injoignable"
in the middle of a scan."""
from app import main
from app.awake import ES_CONTINUOUS, ES_SYSTEM_REQUIRED, KeepAwake
from tests.test_server_fakes import calc, wait_for  # noqa: F401  (calc is a fixture)


class Kernel32:
    def __init__(self):
        self.calls = []

    def SetThreadExecutionState(self, flags):
        self.calls.append(flags)
        return 1


def test_on_windows_the_system_is_asked_to_stay_awake_only_while_the_calculator_works():
    k = Kernel32()
    awake = KeepAwake(platform="win32", kernel32=k)
    assert awake.how == "windows"
    awake.set(False)
    assert k.calls == []                                            # nothing was asked: nothing to give back
    awake.set(True)
    awake.set(True)
    assert k.calls == [ES_CONTINUOUS | ES_SYSTEM_REQUIRED]          # asked once, not at every look of the watchdog
    awake.set(False)
    awake.set(False)
    assert k.calls == [ES_CONTINUOUS | ES_SYSTEM_REQUIRED, ES_CONTINUOUS]   # given back: the PC may sleep again
    assert ES_CONTINUOUS | ES_SYSTEM_REQUIRED == 0x80000001         # the screen is not kept on, only the system


class Holder:
    started: list = []

    def __init__(self, cmd, **kwargs):
        self.cmd, self.ended = list(cmd), False
        Holder.started.append(self)

    def poll(self):
        return 0 if self.ended else None

    def terminate(self):
        self.ended = True

    def wait(self, timeout=None):
        return 0


def test_on_linux_and_macos_a_small_program_holds_the_request_while_the_calculator_works():
    for platform, program in (("linux", "systemd-inhibit"), ("darwin", "caffeinate")):
        Holder.started = []
        awake = KeepAwake(platform=platform, which=lambda name: f"/usr/bin/{name}", popen=Holder)
        assert awake.how == program
        awake.set(True)
        awake.set(True)
        assert len(Holder.started) == 1 and Holder.started[0].cmd[0] == f"/usr/bin/{program}"
        awake.set(False)
        assert Holder.started[0].ended
        awake.set(True)
        assert len(Holder.started) == 2 and not Holder.started[1].ended
        awake.close()
        assert Holder.started[1].ended                              # nothing is left behind when the calculator stops


def test_a_system_that_cannot_be_asked_never_stops_the_calculator():
    class Broken:
        def SetThreadExecutionState(self, flags):
            raise OSError("no such thing")

    def no_program(cmd, **kwargs):
        raise FileNotFoundError(cmd[0])

    for awake in (KeepAwake(platform="linux", which=lambda name: None), KeepAwake(platform="win32", kernel32=Broken()),
                  KeepAwake(platform="linux", which=lambda name: "/usr/bin/systemd-inhibit", popen=no_program),
                  KeepAwake(platform="sunos5")):
        awake.set(True)
        awake.set(False)
        awake.close()
    assert KeepAwake(platform="linux", which=lambda name: None).how is None
    assert KeepAwake(platform="sunos5").how is None


class Recorder:
    how = "test"

    def __init__(self):
        self.asked = []

    def set(self, busy):
        if not self.asked or self.asked[-1] != busy:
            self.asked.append(busy)

    def close(self):
        self.asked.append("closed")


def test_the_pc_stays_awake_from_the_first_view_to_the_end_of_the_last_calculation(calc, monkeypatch):  # noqa: F811
    rec = Recorder()
    calc.server.awake = rec
    wait_for(lambda: rec.asked == [False], what="an idle calculator to let the PC sleep")
    a = calc.create()
    calc.put_frames(a, 3)
    wait_for(lambda: rec.asked[-1] is True, what="the PC to be kept awake while views arrive")
    assert calc.finish(a).status_code == 200
    pa = calc.finishing(a)
    b = calc.create()                      # a second dish waits behind the first
    calc.put_frames(b, 2)
    assert calc.finish(b).status_code == 200
    pa.release()
    pb = calc.finishing(b)
    assert rec.asked[-1] is True, "between two calculations of the queue the PC must not be allowed to sleep"
    pb.release()
    wait_for(lambda: calc.info(b)["ready"], what="the second dish to be ready")
    wait_for(lambda: rec.asked[-1] is False, what="the PC to be allowed to sleep once everything is calculated")
    assert rec.asked == [False, True, False]


def test_a_scan_that_stopped_sending_views_does_not_keep_the_pc_awake_for_ever(calc, monkeypatch):  # noqa: F811
    monkeypatch.setattr(main, "KEEP_AWAKE_AFTER_VIEW_S", 0.3)
    rec = Recorder()
    calc.server.awake = rec
    sid = calc.create()
    calc.put_frames(sid, 2)
    wait_for(lambda: rec.asked[-1:] == [True], what="the PC to be kept awake while views arrive")
    wait_for(lambda: rec.asked[-1] is False, what="the PC to be released after the last view")
    calc.put_frame(sid, 2)                 # the scan goes on: awake again
    wait_for(lambda: rec.asked[-1] is True, what="the PC to be kept awake again")
