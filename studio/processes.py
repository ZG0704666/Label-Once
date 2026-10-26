"""Qt-free worker supervisor. The on-disk protocol is shared with the Qt app."""
from __future__ import annotations
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from .domain import atomic_write, save_json


class ProcessManager:
    def __init__(self, emit, log=None):
        self.emit = emit
        self.log = log
        self.process = None
        self.task = None
        self.lock = threading.RLock()
        self.thread = None
        self._busy = False

    @property
    def busy(self):
        return self._busy

    @property
    def last_task(self):
        return self.task

    @property
    def run(self):
        return Path(self.task['run']) if self.task else None

    def start(self, task):
        with self.lock:
            if self.busy:
                raise RuntimeError('已有任务运行，请等待完成或停止')
            run = Path(task['run'])
            run.mkdir(parents=True, exist_ok=True)
            (run/'cancel').unlink(missing_ok=True)
            (run/'control.json').unlink(missing_ok=True)
            atomic_write(run/'events.jsonl', '')
            save_json(run/'task.json', task)
            args = [sys.executable, '--worker', str(run/'task.json')] if getattr(sys, 'frozen', False) else [sys.executable, '-X', 'utf8', '-m', 'studio.worker', str(run/'task.json')]
            env = dict(os.environ, PYTHONUTF8='1', YOLO_AUTOINSTALL='False', QT_LOGGING_RULES='*.debug=false')
            log = (run/'process.log').open('a', encoding='utf-8')
            try:
                proc = subprocess.Popen(args, cwd=Path(__file__).resolve().parent.parent,
                    env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=log,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            except BaseException:
                log.close()
                raise
            self.process, self.task = proc, task
            self._busy = True
            self.thread = threading.Thread(target=self._watch, args=(proc, task, log), daemon=True)
            self.thread.start()
            return task

    def _tail(self, path, stop):
        offset = 0
        while not stop.is_set():
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            if size > offset:
                with path.open('r', encoding='utf-8', errors='replace') as f:
                    f.seek(offset)
                    chunk = f.read()
                    offset = f.tell()
                for line in chunk.splitlines():
                    if line.strip():
                        try:
                            self.log(line)
                        except Exception:
                            stop.set()
                            break
            elif size < offset:
                offset = 0
            stop.wait(.25)
        try:
            with path.open('r', encoding='utf-8', errors='replace') as f:
                f.seek(offset)
                for line in f.read().splitlines():
                    if line.strip():
                        self.log(line)
        except OSError:
            pass

    def _watch(self, proc, task, log):
        import time
        stop_tail = threading.Event()
        tailer = threading.Thread(target=self._tail, args=(Path(log.name), stop_tail), daemon=True) if self.log else None
        if tailer:
            tailer.start()
        terminal = False
        pending = b''
        offset = 0
        path = Path(task['run'])/'events.jsonl'
        try:
            while True:
                with path.open('rb') as stream:
                    stream.seek(offset)
                    chunk = stream.read()
                    offset = stream.tell()
                pending += chunk
                while b'\n' in pending:
                    line, pending = pending.split(b'\n', 1)
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                    except ValueError:
                        # 容错：worker 崩溃可残留半行；坏行只跳过并记账，不再让整次任务状态跟着崩。
                        text = 'events.jsonl 出现无法解析的行，已跳过：'+line[:160].decode('utf-8', 'replace')
                        if self.log:
                            self.log(text)
                        else:
                            self.emit({'event': 'log', 'data': text})
                        continue
                    if not isinstance(event, dict):
                        continue
                    terminal |= event.get('event') in ('result', 'error', 'cancelled')
                    self.emit(dict(event, task_kind=task['kind'], project=task['project'],
                                   run=task['run'], session=task.get('session'), request=task.get('request')))
                if proc.poll() is not None:
                    # A final read after process termination includes its flushed terminal event.
                    if path.stat().st_size > offset:
                        continue
                    break
                time.sleep(.08)
            if not terminal:
                self.emit(dict(event='error', message=f'后台进程异常退出 ({proc.returncode})；详见 process.log',
                    task_kind=task['kind'], project=task['project'], run=task['run'], session=task.get('session')))
        except Exception as exc:
            if proc.poll() is None:
                self.cancel(force=True)
                proc.wait(timeout=10)
            self.emit(dict(event='error', message=str(exc), project=task['project'], run=task['run']))
        finally:
            if tailer:
                stop_tail.set()
                tailer.join(2)
            log.close()
            with self.lock:
                self._busy = False
                try:
                    self.emit(dict(event='finished', exit_code=proc.returncode, project=task['project'],
                                   run=task['run'], task_kind=task['kind'], session=task.get('session')))
                except Exception:
                    pass  # 桥正在退出（事件管道已断）；忙碌状态照常清零即可

    def cancel(self, force=False):
        with self.lock:
            if self.task and self.busy:
                atomic_write(Path(self.task['run'])/'cancel', 'stop')
                if force and self.process.poll() is None:
                    # Kill the process tree too (DDP/export may have subprocesses).
                    if os.name == 'nt':
                        subprocess.run(['taskkill', '/PID', str(self.process.pid), '/T', '/F'],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=subprocess.CREATE_NO_WINDOW)
                    else:
                        self.process.kill()
        return {'busy': self.busy}

    def control(self, data):
        if not self.busy:
            raise RuntimeError('没有运行中的任务')
        path=Path(self.task['run'])/'control.json'
        if path.exists():
            raise RuntimeError('上一条控制命令尚未处理')
        save_json(path, data)
        return {'accepted': True}

    def close(self):
        self.cancel()
        if self.thread:
            self.thread.join(3)
        self.cancel(force=True)
        if self.thread:
            self.thread.join(3)
