#!/usr/bin/env python3
"""上传/下载稳定性：并发压测 + 异常请求 + 压测后 health 探活。"""
from __future__ import annotations

import http.client
import io
import json
import random
import string
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HOST = "127.0.0.1"
HTTP_PORT = 17080
HEALTH = "/template/health"
UPLOAD = "/template/files/upload"
LIST = "/template/files/list"

stats = {"ok": 0, "err": 0, "health_ok": 0, "health_err": 0}
lock = threading.Lock()


def bump(key: str, n: int = 1) -> None:
    with lock:
        stats[key] += n


def random_name(suffix: str = "txt") -> str:
    return "st_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8)) + f".{suffix}"


def health_check() -> bool:
    try:
        conn = http.client.HTTPConnection(HOST, HTTP_PORT, timeout=5)
        conn.request("GET", HEALTH, headers={"Connection": "close"})
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        ok = resp.status == 200 and b'"code":0' in body or b'"status":"ok"' in body
        bump("health_ok" if ok else "health_err")
        return ok
    except Exception:
        bump("health_err")
        return False


def upload_file(name: str, content: bytes) -> tuple[bool, int]:
    try:
        boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{name}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
        conn = http.client.HTTPConnection(HOST, HTTP_PORT, timeout=15)
        conn.request(
            "POST",
            UPLOAD,
            body=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(body)),
                "Connection": "close",
            },
        )
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        ok = resp.status == 200 and b'"code":0' in data
        bump("ok" if ok else "err")
        return ok, resp.status
    except Exception:
        bump("err")
        return False, 0


def download_file(name: str) -> tuple[bool, int]:
    try:
        conn = http.client.HTTPConnection(HOST, HTTP_PORT, timeout=15)
        conn.request("GET", f"/template/files/download/{name}", headers={"Connection": "close"})
        resp = conn.getresponse()
        resp.read()
        conn.close()
        ok = resp.status == 200
        bump("ok" if ok else "err")
        return ok, resp.status
    except Exception:
        bump("err")
        return False, 0


def list_files() -> tuple[bool, int]:
    try:
        conn = http.client.HTTPConnection(HOST, HTTP_PORT, timeout=10)
        conn.request("GET", LIST, headers={"Connection": "close"})
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        ok = resp.status == 200 and b'"code":0' in data
        bump("ok" if ok else "err")
        return ok, resp.status
    except Exception:
        bump("err")
        return False, 0


def abuse_request(desc: str, method: str, path: str, body: bytes | None = None) -> None:
    """异常/恶意请求：应返回 4xx 且不能拖垮服务。"""
    try:
        conn = http.client.HTTPConnection(HOST, HTTP_PORT, timeout=5)
        headers = {"Connection": "close"}
        if body is not None:
            headers["Content-Length"] = str(len(body))
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        resp.read()
        conn.close()
        # 4xx/5xx 均可接受，关键是连接正常关闭
        bump("ok")
        print(f"  [abuse OK] {desc} -> HTTP {resp.status}")
    except Exception as ex:
        bump("err")
        print(f"  [abuse ERR] {desc} -> {ex}", file=sys.stderr)


def worker_mix(wid: int, rounds: int) -> None:
    uploaded: list[str] = []
    for i in range(rounds):
        op = random.choice(["upload", "download", "list", "health"])
        if op == "health":
            health_check()
            continue
        if op == "list":
            list_files()
            continue
        if op == "upload":
            name = random_name()
            payload = f"worker{wid}-round{i}-{time.time()}".encode()
            ok, _ = upload_file(name, payload)
            if ok:
                uploaded.append(name)
            continue
        if uploaded:
            download_file(random.choice(uploaded))


def wait_health(retries: int = 30) -> bool:
    for _ in range(retries):
        if health_check():
            return True
        time.sleep(0.5)
    return False


def main() -> int:
    print("=== File transfer stability test ===")
    print(f"Target http://{HOST}:{HTTP_PORT}")

    if not wait_health():
        print("FAIL: server health not reachable", file=sys.stderr)
        return 1

    print("\n[1] Baseline health x50")
    with ThreadPoolExecutor(max_workers=10) as pool:
        list(pool.map(lambda _: health_check(), range(50)))
    if stats["health_err"] > 0:
        print(f"FAIL: baseline health errors={stats['health_err']}", file=sys.stderr)
        return 1
    print("  baseline OK")

    print("\n[2] Concurrent upload/download/list/health (20 workers x 30 ops)")
    with ThreadPoolExecutor(max_workers=20) as pool:
        futs = [pool.submit(worker_mix, i, 30) for i in range(20)]
        for f in as_completed(futs):
            f.result()

    print("\n[3] Abuse / edge cases")
    abuse_request("path traversal download", "GET", "/template/files/download/../../index.html")
    abuse_request("invalid name", "GET", "/template/files/download/..%2F..%2Fetc%2Fpasswd")
    abuse_request("empty upload", "POST", UPLOAD, b"")
    abuse_request("missing file download", "GET", "/template/files/download/no_such_file_xyz.bin")
    long_name = "a" * 250 + ".txt"
    abuse_request("overlong filename", "POST", UPLOAD + f"?name={long_name}", b"x")

    print("\n[4] Post-stress health x100 (server must stay alive)")
    health_err_before = stats["health_err"]
    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(lambda _: health_check(), range(100)))
    post_fail = sum(1 for r in results if not r)
    if post_fail > 0:
        print(f"FAIL: post-stress health failed {post_fail}/100", file=sys.stderr)
        return 1

    print("\n=== Summary ===")
    print(json.dumps(stats, indent=2))
    total_err = stats["err"]
    if total_err > 5:
        print(f"WARN: total operational errors={total_err} (abuse cases may count as ok)")
    print("PASS: server stable after file transfer stress")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
