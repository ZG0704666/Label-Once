"""Versioned UTF-8 JSONL stdio RPC. Stdout is exclusively protocol traffic."""
import contextlib
import json
import logging
import sys
import threading
import traceback
from .service import StudioService


def _rebind_stdout_handlers():
    """第三方库（ultralytics）在导入/推理期给 LOGGER 挂 StreamHandler(sys.stdout)，
    会把横幅、计数行等日志直接写进协议管道，让 C# 端的逐行 JSON 解析炸掉。
    这里把所有指回 sys.stdout 的 handler 改指 stderr，保证 stdout 只承载 JSON 帧；开销极小，每帧防御调用。"""
    current = sys.stdout
    loggers = [logging.getLogger(), *(obj for obj in logging.root.manager.loggerDict.values()
                                     if isinstance(obj, logging.Logger))]
    for logger in loggers:
        for handler in list(logger.handlers):
            if getattr(handler, 'stream', None) is current:
                handler.stream = sys.stderr


def serve(input_stream, output_stream):
    lock = threading.Lock()
    def send(value):
        _rebind_stdout_handlers()
        with lock:
            output_stream.write(json.dumps(dict(version=1, **value), ensure_ascii=False, allow_nan=False)+'\n')
            output_stream.flush()
    service = StudioService(lambda event: send({'event':event}))
    _rebind_stdout_handlers()
    try:
        for line in input_stream:
            request_id = None
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise ValueError('请求必须是 JSON 对象')
                request_id = request.get('id')
                if request.get('version') != 1 or not isinstance(request_id, (str,int)):
                    raise ValueError('协议版本或请求 ID 无效')
                if not isinstance(request.get('params', {}), dict):
                    raise ValueError('params 必须是对象')
                with contextlib.redirect_stdout(sys.stderr):
                    result = service.dispatch(request['method'], request.get('params', {}))
                send(dict(id=request_id, result=result))
            except Exception as exc:
                traceback.print_exc(file=sys.stderr)
                send(dict(id=request_id,error=dict(code=type(exc).__name__,message=str(exc),retryable=isinstance(exc,(OSError,RuntimeError)))))
    finally:
        service.close()


def main():
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='strict')
    serve(sys.stdin, sys.stdout)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
