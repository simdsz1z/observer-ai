import json
import subprocess
import sys
import threading
import time

import pytest

from observer.persistent import PipeFailure, ResidentRuntime
from observer.vision import LocalQwenObserver, model_slot


def runtime(code, timeout=3):
    return ResidentRuntime([sys.executable, "-u", "-c", code], timeout, LocalQwenObserver._kill_tree)


def test_resident_reuses_one_process_for_multiple_requests_and_closes():
    code = "import sys,json; print(json.dumps({'ready':True,'protocol':1,'device':'test'}),flush=True)\nfor line in sys.stdin: print(json.dumps({'ok':True,'answer':json.loads(line)['prompt']}),flush=True)"
    worker = runtime(code)
    stop = threading.Event()
    try:
        assert worker.request({"prompt": "first"}, stop)["answer"] == "first"
        pid = worker.process.pid
        assert worker.request({"prompt": "second"}, stop)["answer"] == "second"
        assert worker.process.pid == pid
        assert worker.requests == 2
        process = worker.process
    finally:
        worker.close()
    assert process.poll() is not None
    assert not any(t.is_alive() for t in worker.readers)


def test_resident_cancel_reaps_a_busy_process_and_readers():
    code = "import json,sys,time; print(json.dumps({'ready':True,'protocol':1}),flush=True); sys.stdin.readline(); time.sleep(60)"
    worker = runtime(code)
    stop = threading.Event()
    failures = []
    def run():
        try:
            worker.request({"prompt": "wait"}, stop)
        except PipeFailure as error:
            failures.append(error.code)
    thread = threading.Thread(target=run)
    thread.start()
    deadline = time.monotonic() + 2
    while worker.process is None and time.monotonic() < deadline:
        time.sleep(.01)
    process = worker.process
    stop.set()
    worker.close()
    thread.join(3)
    assert not thread.is_alive()
    assert failures == ["cancelled"]
    assert process.poll() is not None


def test_resident_timeout_and_invalid_handshake_are_bounded():
    worker = runtime("import time; time.sleep(60)", timeout=.2)
    with pytest.raises(PipeFailure, match="inference_timeout"):
        worker.request({}, threading.Event())
    assert worker.process is None
    worker = runtime("print('{\"ready\":true,\"protocol\":99}',flush=True)")
    with pytest.raises(PipeFailure, match="runtime_failed"):
        worker.request({}, threading.Event())
    assert worker.process is None


def test_chat_handoff_releases_resident_weights_before_next_owner():
    class Owner:
        def __init__(self):
            self.released = False
        def release_model(self):
            self.released = True
    owner = Owner()
    with model_slot(threading.Event(), owner):
        pass
    with model_slot(threading.Event()):
        assert owner.released
