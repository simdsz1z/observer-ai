"""Bounded JSON-line transport to the owned, persistent local native worker."""
from collections import deque
import json
import queue
import subprocess
import threading
import time


class PipeFailure(Exception):
    def __init__(self, code, detail=""):
        self.code, self.detail = code, detail
        super().__init__(code)


class ResidentRuntime:
    def __init__(self, args, timeout, kill_tree):
        self.args, self.timeout, self.kill_tree = args, timeout, kill_tree
        self.process = None
        self.messages = queue.Queue(maxsize=8)
        self.logs = deque(maxlen=8)
        self.readers = []
        self.lock = threading.Lock()
        self.device = None
        self.requests = 0

    def _read_stdout(self, process):
        try:
            while True:
                line = process.stdout.readline(1024 * 1024 + 1)
                if not line:
                    break
                if len(line) > 1024 * 1024:
                    self.messages.put_nowait({"transport_error": "excessive_runtime_output"})
                    return
                self.messages.put_nowait(json.loads(line.decode("utf-8")))
        except (OSError, ValueError, queue.Full):
            pass
        finally:
            try:
                self.messages.put_nowait({"transport_error": "runtime_failed"})
            except queue.Full:
                pass

    def _read_stderr(self, process):
        try:
            while True:
                data = process.stderr.read1(4096)
                if not data:
                    return
                self.logs.append(data.decode("utf-8", errors="replace"))
        except (OSError, ValueError):
            pass

    def _receive(self, stop, deadline):
        while True:
            if stop.is_set() or time.monotonic() >= deadline:
                self.close()
                raise PipeFailure("cancelled" if stop.is_set() else "inference_timeout")
            try:
                value = self.messages.get(timeout=.05)
            except queue.Empty:
                continue
            if value.get("transport_error"):
                self.close()
                raise PipeFailure("cancelled" if stop.is_set() else value["transport_error"], "".join(self.logs)[-4000:])
            return value

    def request(self, value, stop):
        deadline = time.monotonic() + self.timeout
        if stop.is_set():
            raise PipeFailure("cancelled")
        if self.process is None:
            with self.lock:
                self.process = subprocess.Popen(self.args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                process = self.process
            self.readers = [threading.Thread(target=self._read_stdout, args=(process,), daemon=True),
                            threading.Thread(target=self._read_stderr, args=(process,), daemon=True)]
            for thread in self.readers:
                thread.start()
            ready = self._receive(stop, deadline)
            if ready.get("ready") is not True or ready.get("protocol") != 1:
                self.close()
                raise PipeFailure("runtime_failed", ready.get("error", "invalid_worker_handshake"))
            self.device = ready.get("device")
        try:
            self.process.stdin.write((json.dumps(value, ensure_ascii=True) + "\n").encode("utf-8"))
            self.process.stdin.flush()
        except (OSError, AttributeError):
            raise PipeFailure("cancelled" if stop.is_set() else "runtime_failed") from None
        result = self._receive(stop, deadline)
        self.requests += 1
        if not result.get("ok"):
            raise PipeFailure("runtime_failed", result.get("error", "native_error"))
        return result

    def close(self):
        with self.lock:
            process, self.process = self.process, None
        if process:
            if process.poll() is None:
                self.kill_tree(process)
            process.wait(timeout=3)
            for thread in self.readers:
                if thread is not threading.current_thread() and thread.ident is not None:
                    thread.join(timeout=1)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream:
                    stream.close()
