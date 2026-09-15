"""Real pinned sentiment service smoke probe; no core/OCES evaluation claim.

Run: .venv/Scripts/python.exe tests/fixtures/rayyan/sentiment_runtime.py --out results/<new-dir>
Uses the configured loopback port and shuts down only the child it starts.
The ASGI observer records received bytes without changing requests or responses.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import socket
import signal
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def save(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def peak_memory(pid):
    if sys.platform != "win32":
        return None
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in (
                "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
                "PagefileUsage", "PeakPagefileUsage")]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    handle = kernel.OpenProcess(0x410, False, pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        return counters.PeakWorkingSetSize
    finally:
        kernel.CloseHandle(handle)


def serve(out):
    import uvicorn
    from endpoint.targets import load_registry
    from endpoint.sentiment_v1 import app
    assert "endpoint.model" not in sys.modules
    spec = load_registry().target("sentiment_v1")
    save(out / "service_identity.json", {"service_pid": os.getpid(),
         "emotion_module_loaded": "endpoint.model" in sys.modules})
    async def observe(scope, receive, send):
        chunks = []
        async def observed_receive():
            message = await receive()
            if scope.get("path") == "/predict" and message["type"] == "http.request":
                chunks.append(message.get("body", b""))
                if not message.get("more_body", False):
                    body = b"".join(chunks)
                    with (out / "received.jsonl").open("a", encoding="utf-8") as stream:
                        stream.write(json.dumps({"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}) + "\n")
            return message
        await app(scope, observed_receive, send)
    uvicorn.run(observe, host="127.0.0.1", port=spec.port, log_level="warning")


def measure(out):
    import httpx
    from contract import AttackCase, BaselineCase
    from endpoint.loader import load_target_tokenizer
    from endpoint.targets import load_registry
    from runner.run import Runner, ResultWriter
    registry = load_registry()
    spec = registry.target("sentiment_v1")
    context = load_target_tokenizer(spec.target_id)
    assert "endpoint.model" not in sys.modules
    with socket.socket() as sock:
        if sock.connect_ex(("127.0.0.1", spec.port)) == 0:
            raise RuntimeError(f"configured port {spec.port} already occupied")
    out.mkdir(parents=True, exist_ok=False)
    url = f"http://127.0.0.1:{spec.port}"
    env = {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "TOKENIZERS_PARALLELISM": "false"}
    started = time.perf_counter()
    log = (out / "service.log").open("w", encoding="utf-8")
    process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--serve", str(out)],
                               cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    writer = runner = None
    service_pid = None
    try:
        with httpx.Client(timeout=1.0, trust_env=False) as client:
            while True:
                if process.poll() is not None:
                    raise RuntimeError("service exited; inspect service.log")
                try:
                    response = client.get(url + "/health")
                    if response.status_code == 200:
                        assert response.json() == {"status": "ok"}
                        break
                except httpx.HTTPError:
                    pass
                if time.perf_counter() - started > 90:
                    raise TimeoutError("service startup exceeded 90s")
                time.sleep(0.05)
        startup = time.perf_counter() - started
        service_pid = json.loads((out / "service_identity.json").read_text(encoding="utf-8"))["service_pid"]
        writer = ResultWriter(out / "results.jsonl")
        runner = Runner(url, "v1", writer, target_id="sentiment_v1", suite_id="core")
        rows = []
        for identifier, text, label in [
            ("positive", "This movie was excellent and I loved it.", "POSITIVE"),
            ("negative", "This movie was terrible and I hated it.", "NEGATIVE"),
            ("unicode", "A lovely caf\u00e9 and a wonderful evening.", "POSITIVE"),
        ]:
            row = runner.send_baseline(BaselineCase(identifier, text, label, "runtime smoke probe"))
            assert row.status_code == 200 and row.label == label
            assert set(row.all_scores) == {"NEGATIVE", "POSITIVE"}
            assert all(math.isfinite(v) for v in row.all_scores.values())
            assert abs(sum(row.all_scores.values()) - 1.0) < 1e-5
            rows.append(row)
        raw = AttackCase("probe.raw_utf8", None, "malformed", None, None,
                         is_raw=True, raw_body=b'{"text":"caf\xff"}', raw_headers={"Content-Type": "application/json"})
        rows.append(runner.send_attack(raw))
        assert rows[-1].status_code == 400
        for count, expected in [(512, 200), (513, 500)]:
            text = "word " * (count - 2)
            assert context.count_tokens(text) == count
            rows.append(runner.send_attack(AttackCase(f"probe.tokens_{count}", None, "boundary", None, text)))
            assert rows[-1].status_code == expected
        for index in range(20):
            row = runner.send_baseline(BaselineCase(f"repeat-{index}", "This movie was excellent.", "POSITIVE", "runtime timing probe"))
            assert row.status_code == 200
            rows.append(row)
        assert all(row.endpoint_alive_after for row in rows)
        received = [json.loads(line) for line in (out / "received.jsonl").read_text(encoding="utf-8").splitlines()]
        assert len(received) == len(rows) == 26
        for row, wire in zip(rows, received):
            assert (row.request_body_bytes, row.request_body_sha256) == (wire["bytes"], wire["sha256"])
        timing = sorted(row.latency_ms for row in rows[-20:])
        summary = {"kind": "real endpoint smoke; not a generated core/OCES evaluation",
                   "target_id": spec.target_id, "model_revision": context.model_spec.revision,
                   "tokenizer_revision": context.model_spec.tokenizer_revision,
                   "max_tokens": context.max_tokens, "cached_startup_s": startup,
                   "first_prediction_ms": rows[0].latency_ms,
                   "steady_median_ms": statistics.median(timing), "steady_p95_ms": timing[18],
                   "peak_working_set_bytes": peak_memory(service_pid),
                   "service_pid": service_pid, "launcher_pid": process.pid, "cases": len(rows),
                   "received_bytes_match_all_rows": True, "statuses": [row.status_code for row in rows],
                   "examples": [{"case_id": row.attack_id or row.baseline_id,
                                 "bytes": row.request_body_bytes, "sha256": row.request_body_sha256}
                                for row in rows[:6]]}
    finally:
        if runner is not None:
            runner.close()
        if writer is not None:
            writer.close()
        if process.poll() is None:
            if service_pid is not None and service_pid != process.pid:
                try:
                    os.kill(service_pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        log.close()
    with socket.socket() as sock:
        assert sock.connect_ex(("127.0.0.1", spec.port)) != 0, "service still listening after cleanup"
    summary["process_stopped"] = process.poll() is not None
    save(out / "summary.json", summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path)
    parser.add_argument("--serve", type=Path)
    args = parser.parse_args()
    if args.serve:
        serve(args.serve.resolve())
    elif args.out:
        measure(args.out.resolve())
    else:
        parser.error("--out is required")
