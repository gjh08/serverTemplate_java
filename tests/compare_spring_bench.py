#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""serverTemplate vs ASprintBootServer 三协议压测对比（HTTP / WS / TCP）"""

from __future__ import annotations

import argparse
import asyncio
import json
import socket
import struct
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

try:
    import websockets
except ImportError:
    websockets = None

try:
    import websocket as ws_client
except ImportError:
    ws_client = None

# serverTemplate 协议常量
ST_CMD_REQ = 9001
ST_CMD_RESP = 9002
ST_HEAD_SIZE = 12


@dataclass
class ServerTarget:
    key: str
    label: str
    stack: str
    http_port: int
    ws_port: int
    tcp_port: int
    http_path: str


TARGETS: dict[str, ServerTarget] = {
    "template": ServerTarget(
        "template",
        "serverTemplate (framework)",
        "Netty + 自研 framework (HTTP/WS/TCP)",
        17080,
        17081,
        17082,
        "/template/health",
    ),
    "spring": ServerTarget(
        "spring",
        "ASprintBootServer",
        "Spring Boot 3 + Tomcat WS + Netty TCP/UDP",
        8180,
        8180,
        9011,
        "/api/health",
    ),
}


@dataclass
class BenchResult:
    server: str
    protocol: str
    concurrency: int
    ok: int
    errors: int
    rps: float
    duration_s: float
    p50_ms: float
    p99_ms: float
    max_ms: float


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * p
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def probe_health(host: str, target: ServerTarget) -> bool:
    import http.client

    try:
        c = http.client.HTTPConnection(host, target.http_port, timeout=5)
        c.request("GET", target.http_path)
        r = c.getresponse()
        r.read()
        c.close()
        return r.status == 200
    except Exception:
        return False


def bench_http(host: str, target: ServerTarget, concurrency: int, count: int) -> BenchResult:
    import http.client

    # serverTemplate / Spring 均使用 keep-alive 长连接（公平对比）
    keep_alive = True
    latencies: list[float] = []
    errors = 0
    per_worker = max(1, count // concurrency)

    def one_request(conn: http.client.HTTPConnection | None) -> tuple[float | None, http.client.HTTPConnection | None]:
        own_conn = conn is None
        c = conn or http.client.HTTPConnection(host, target.http_port, timeout=15)
        try:
            t0 = time.perf_counter()
            headers = {"Connection": "keep-alive"} if keep_alive else {"Connection": "close"}
            c.request("GET", target.http_path, headers=headers)
            resp = c.getresponse()
            resp.read()
            if resp.status != 200:
                if own_conn:
                    c.close()
                return None, None
            ms = (time.perf_counter() - t0) * 1000
            if keep_alive:
                return ms, c
            c.close()
            return ms, None
        except Exception:
            if own_conn:
                try:
                    c.close()
                except Exception:
                    pass
            return None, None

    def worker(_: int) -> tuple[list[float], int]:
        local_lat: list[float] = []
        local_err = 0
        conn: http.client.HTTPConnection | None = None
        for _ in range(per_worker):
            ms, conn = one_request(conn)
            if ms is None:
                local_err += 1
                conn = None
            else:
                local_lat.append(ms)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        return local_lat, local_err

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futs = [pool.submit(worker, i) for i in range(concurrency)]
        for fut in as_completed(futs):
            lat, err = fut.result()
            latencies.extend(lat)
            errors += err
    dur = time.perf_counter() - t0
    ok = len(latencies)
    return BenchResult(
        target.key, "HTTP", concurrency, ok, errors, ok / dur if dur else 0, dur,
        percentile(latencies, 0.5), percentile(latencies, 0.99),
        max(latencies) if latencies else 0,
    )


def st_pack_frame(body: bytes) -> bytes:
    return struct.pack("<H", len(body)) + body


def st_pack_message(cmd: int, utag: int, payload: dict) -> bytes:
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    header = struct.pack("<HqH", cmd, utag, 0)
    return header + body


def st_read_response(sock: socket.socket, timeout: float = 15.0) -> bool:
    buf = b""
    deadline = time.time() + timeout
    while time.time() < deadline:
        chunk = sock.recv(65536)
        if not chunk:
            return False
        buf += chunk
        i = 0
        while i + 2 <= len(buf):
            ln = struct.unpack_from("<H", buf, i)[0]
            i += 2
            if i + ln > len(buf):
                break
            frame = buf[i : i + ln]
            i += ln
            if len(frame) >= ST_HEAD_SIZE:
                cmd = struct.unpack_from("<H", frame, 0)[0]
                if cmd == ST_CMD_RESP:
                    return True
        buf = buf[i:]
    return False


def bench_template_tcp(host: str, target: ServerTarget, concurrency: int, count: int) -> BenchResult:
    latencies: list[float] = []
    errors = 0
    per_conn = max(1, count // concurrency)

    def worker(wid: int) -> tuple[list[float], int]:
        local_lat: list[float] = []
        local_err = 0
        try:
            sock = socket.create_connection((host, target.tcp_port), timeout=15)
            sock.settimeout(15)
            for seq in range(per_conn):
                req = st_pack_message(ST_CMD_REQ, 1000 + wid, {"seq": seq, "payload": "bench"})
                t0 = time.perf_counter()
                sock.sendall(st_pack_frame(req))
                if st_read_response(sock):
                    local_lat.append((time.perf_counter() - t0) * 1000)
                else:
                    local_err += 1
            sock.close()
        except Exception:
            local_err += per_conn
        return local_lat, local_err

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futs = [pool.submit(worker, i) for i in range(concurrency)]
        for fut in as_completed(futs):
            lat, err = fut.result()
            latencies.extend(lat)
            errors += err
    dur = time.perf_counter() - t0
    ok = len(latencies)
    return BenchResult(
        target.key, "TCP", concurrency, ok, errors, ok / dur if dur else 0, dur,
        percentile(latencies, 0.5), percentile(latencies, 0.99),
        max(latencies) if latencies else 0,
    )


def spring_tcp_frame(payload: dict) -> bytes:
    body = json.dumps(payload).encode("utf-8")
    return struct.pack(">I", len(body)) + body


def spring_tcp_read_frame(sock: socket.socket) -> bytes:
    hdr = sock.recv(4)
    if len(hdr) < 4:
        raise OSError("short read")
    n = struct.unpack(">I", hdr)[0]
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise OSError("closed")
        data += chunk
    return data


def bench_spring_tcp(host: str, target: ServerTarget, concurrency: int, count: int) -> BenchResult:
    payload = {"route": "/tcp/world_map/ping", "message": "bench"}
    latencies: list[float] = []
    errors = 0
    per_conn = max(1, count // concurrency)

    def worker(_: int) -> tuple[list[float], int]:
        local_lat: list[float] = []
        local_err = 0
        try:
            sock = socket.create_connection((host, target.tcp_port), timeout=15)
            spring_tcp_read_frame(sock)
            for _ in range(per_conn):
                t0 = time.perf_counter()
                sock.sendall(spring_tcp_frame(payload))
                spring_tcp_read_frame(sock)
                local_lat.append((time.perf_counter() - t0) * 1000)
            sock.close()
        except Exception:
            local_err += per_conn
        return local_lat, local_err

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futs = [pool.submit(worker, i) for i in range(concurrency)]
        for fut in as_completed(futs):
            lat, err = fut.result()
            latencies.extend(lat)
            errors += err
    dur = time.perf_counter() - t0
    ok = len(latencies)
    return BenchResult(
        target.key, "TCP", concurrency, ok, errors, ok / dur if dur else 0, dur,
        percentile(latencies, 0.5), percentile(latencies, 0.99),
        max(latencies) if latencies else 0,
    )


async def bench_template_ws_async(
    host: str, target: ServerTarget, concurrency: int, count: int
) -> BenchResult:
    if websockets is None:
        return BenchResult(target.key, "WS", concurrency, 0, count, 0, 0, 0, 0, 0)

    uri = f"ws://{host}:{target.ws_port}/websocket"
    per_conn = max(1, count // concurrency)
    latencies: list[float] = []
    errors = 0
    lock = asyncio.Lock()

    async def worker(wid: int) -> None:
        nonlocal errors
        local_lat: list[float] = []
        local_err = 0
        try:
            async with websockets.connect(uri, open_timeout=15, close_timeout=5) as ws:
                for seq in range(per_conn):
                    req = st_pack_message(ST_CMD_REQ, 2000 + wid, {"seq": seq, "payload": "bench"})
                    t0 = time.perf_counter()
                    await ws.send(req)
                    raw = await ws.recv()
                    if isinstance(raw, str):
                        raw = raw.encode()
                    if len(raw) >= ST_HEAD_SIZE and struct.unpack_from("<H", raw, 0)[0] == ST_CMD_RESP:
                        local_lat.append((time.perf_counter() - t0) * 1000)
                    else:
                        local_err += 1
        except Exception:
            local_err += per_conn
        async with lock:
            latencies.extend(local_lat)
            errors += local_err

    t0 = time.perf_counter()
    await asyncio.gather(*[worker(i) for i in range(concurrency)])
    dur = time.perf_counter() - t0
    ok = len(latencies)
    return BenchResult(
        target.key, "WS", concurrency, ok, errors, ok / dur if dur else 0, dur,
        percentile(latencies, 0.5), percentile(latencies, 0.99),
        max(latencies) if latencies else 0,
    )


def bench_template_ws(host: str, target: ServerTarget, concurrency: int, count: int) -> BenchResult:
    return asyncio.run(bench_template_ws_async(host, target, concurrency, count))


def bench_template_ws_legacy(host: str, target: ServerTarget, concurrency: int, count: int) -> BenchResult:
    if ws_client is None:
        return BenchResult(target.key, "WS", concurrency, 0, count, 0, 0, 0, 0, 0)

    latencies: list[float] = []
    errors = 0
    per_conn = max(1, count // concurrency)
    lock = __import__("threading").Lock()
    url = f"ws://{host}:{target.ws_port}/websocket"

    def worker(wid: int) -> tuple[list[float], int]:
        local_lat: list[float] = []
        local_err = 0
        try:
            ws = ws_client.create_connection(url, timeout=15)
            for seq in range(per_conn):
                req = st_pack_message(ST_CMD_REQ, 2000 + wid, {"seq": seq, "payload": "bench"})
                t0 = time.perf_counter()
                ws.send_binary(req)
                deadline = time.time() + 15
                ok = False
                while time.time() < deadline:
                    ws.settimeout(max(0.1, deadline - time.time()))
                    try:
                        raw = ws.recv()
                    except ws_client.WebSocketTimeoutException:
                        continue
                    if isinstance(raw, str):
                        raw = raw.encode()
                    if len(raw) >= ST_HEAD_SIZE:
                        cmd = struct.unpack_from("<H", raw, 0)[0]
                        if cmd == ST_CMD_RESP:
                            local_lat.append((time.perf_counter() - t0) * 1000)
                            ok = True
                            break
                if not ok:
                    local_err += 1
            ws.close()
        except Exception:
            local_err += per_conn
        return local_lat, local_err

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futs = [pool.submit(worker, i) for i in range(concurrency)]
        for fut in as_completed(futs):
            lat, err = fut.result()
            with lock:
                latencies.extend(lat)
                errors += err
    dur = time.perf_counter() - t0
    ok = len(latencies)
    return BenchResult(
        target.key, "WS", concurrency, ok, errors, ok / dur if dur else 0, dur,
        percentile(latencies, 0.5), percentile(latencies, 0.99),
        max(latencies) if latencies else 0,
    )


async def bench_spring_ws_async(
    host: str, target: ServerTarget, concurrency: int, count: int
) -> BenchResult:
    if websockets is None:
        return BenchResult(target.key, "WS", concurrency, 0, count, 0, 0, 0, 0, 0)

    uri = f"ws://{host}:{target.ws_port}/ws"
    msg = json.dumps({"route": "/ws/world_map/ping", "message": "bench"})
    per_conn = max(1, count // concurrency)
    latencies: list[float] = []
    errors = 0
    lock = asyncio.Lock()

    async def worker(_: int) -> None:
        nonlocal errors
        try:
            async with websockets.connect(uri, open_timeout=15, close_timeout=5) as ws:
                for _ in range(per_conn):
                    t0 = time.perf_counter()
                    await ws.send(msg)
                    await ws.recv()
                    ms = (time.perf_counter() - t0) * 1000
                    async with lock:
                        latencies.append(ms)
        except Exception:
            async with lock:
                errors += per_conn

    t0 = time.perf_counter()
    await asyncio.gather(*(worker(i) for i in range(concurrency)))
    dur = time.perf_counter() - t0
    ok = len(latencies)
    return BenchResult(
        target.key, "WS", concurrency, ok, errors, ok / dur if dur else 0, dur,
        percentile(latencies, 0.5), percentile(latencies, 0.99),
        max(latencies) if latencies else 0,
    )


def result_to_dict(r: BenchResult) -> dict:
    return {
        "server": r.server,
        "protocol": r.protocol,
        "concurrency": r.concurrency,
        "ok": r.ok,
        "errors": r.errors,
        "rps": r.rps,
        "duration_s": r.duration_s,
        "p50_ms": r.p50_ms,
        "p99_ms": r.p99_ms,
        "max_ms": r.max_ms,
    }


def result_from_dict(d: dict) -> BenchResult:
    return BenchResult(**d)


def save_results(path: Path, results: list[BenchResult], meta: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"meta": meta, "results": [result_to_dict(r) for r in results]}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_results(path: Path) -> tuple[list[BenchResult], dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    results = [result_from_dict(d) for d in payload["results"]]
    return results, payload.get("meta", {})


def assert_isolated(host: str, target: ServerTarget) -> None:
    """确保只测当前服务：目标可达，对手服务不可达。"""
    if not probe_health(host, target):
        raise RuntimeError(
            f"目标服务不可达: {target.label} "
            f"http://{host}:{target.http_port}{target.http_path}"
        )
    for key, other in TARGETS.items():
        if key == target.key:
            continue
        if probe_health(host, other):
            raise RuntimeError(
                f"隔离测试失败：{other.label} 仍在运行 "
                f"(http://{host}:{other.http_port}{other.http_path})。"
                f"请先停止 {other.label}，仅保留 {target.label}。"
            )
    print(f"[OK] 隔离检查通过：仅 {target.label} 在运行")


def run_server_bench(
    host: str,
    target: ServerTarget,
    concurrency: int,
    count: int,
    *,
    isolated: bool = True,
    warmup: bool = True,
) -> list[BenchResult]:
    print(f"\n{'='*60}\n>>> {target.label}\n{'='*60}")
    if isolated:
        assert_isolated(host, target)
    elif not probe_health(host, target):
        print(f"  [SKIP] HTTP {target.http_port}{target.http_path} 不可达")
        return []

    if warmup and count >= 1000:
        warm_count = min(2000, max(500, count // 5))
        print(f"  [warmup] HTTP/WS/TCP x{warm_count} @并发{concurrency} ...")
        run_server_bench(
            host, target, concurrency, warm_count, isolated=False, warmup=False
        )
        time.sleep(2)

    out: list[BenchResult] = []
    print("\n--- HTTP ---")
    r_http = bench_http(host, target, concurrency, count)
    print(f"  {r_http.rps:.1f} req/s  ok={r_http.ok} err={r_http.errors}  p50={r_http.p50_ms:.2f}ms")
    out.append(r_http)

    print("\n--- WS ---")
    if target.key == "template":
        r_ws = asyncio.run(bench_template_ws_async(host, target, concurrency, count))
    else:
        r_ws = asyncio.run(bench_spring_ws_async(host, target, concurrency, count))
    print(f"  {r_ws.rps:.1f} req/s  ok={r_ws.ok} err={r_ws.errors}  p50={r_ws.p50_ms:.2f}ms")
    out.append(r_ws)

    print("\n--- TCP ---")
    if target.key == "template":
        r_tcp = bench_template_tcp(host, target, concurrency, count)
    else:
        r_tcp = bench_spring_tcp(host, target, concurrency, count)
    print(f"  {r_tcp.rps:.1f} req/s  ok={r_tcp.ok} err={r_tcp.errors}  p50={r_tcp.p50_ms:.2f}ms")
    out.append(r_tcp)

    return out


def render_markdown(results: list[BenchResult], meta: dict) -> str:
    concurrencies = meta["concurrency_list"]
    title = meta.get("title", "压力测试报告（vs ASprintBootServer）")
    repro_cmd = meta.get(
        "repro_cmd",
        "py -3 tests/compare_spring_bench.py -c 100,400 -n 8000",
    )
    lines = [
        f"## {title}",
        "",
        f"- **测试时间**: {meta['time']}",
        f"- **主机**: {meta['host']}",
        f"- **并发档位**: {', '.join(str(c) for c in concurrencies)}",
        f"- **每协议每档总请求数**: {meta['count']}",
        f"- **测试方式**: {meta.get('mode', '同机逐台隔离压测（一次只运行一个服务）')}",
        "",
        "### 测试对象",
        "",
        "| 代号 | 服务 | 技术栈 | HTTP | WS | TCP |",
        "|------|------|--------|------|----|-----|",
    ]
    for t in TARGETS.values():
        lines.append(
            f"| {t.key} | {t.label} | {t.stack} | "
            f":{t.http_port}{t.http_path} | :{t.ws_port} | :{t.tcp_port} |"
        )

    for conc in concurrencies:
        subset = [r for r in results if r.concurrency == conc]
        lines += [
            "",
            f"### 并发 {conc} — 吞吐量 (req/s)",
            "",
            "| 协议 | serverTemplate | ASprintBoot | 领先 |",
            "|------|----------------|-------------|------|",
        ]
        for proto in ("HTTP", "WS", "TCP"):
            m = {r.server: r for r in subset if r.protocol == proto}
            tpl = m.get("template")
            spr = m.get("spring")
            best_name, best_rps = "-", -1.0
            for name, r in [("serverTemplate", tpl), ("ASprintBoot", spr)]:
                if r and r.rps > best_rps:
                    best_rps, best_name = r.rps, name
            lines.append(
                f"| {proto} | "
                f"{(tpl.rps if tpl else 0):.1f} | "
                f"{(spr.rps if spr else 0):.1f} | "
                f"**{best_name}** |"
            )

    # 综合评分：吞吐领先 + 零错误加分
    tpl_wins, spr_wins = 0, 0
    tpl_err_total, spr_err_total = 0, 0
    for r in results:
        if r.server == "template":
            tpl_err_total += r.errors
        else:
            spr_err_total += r.errors
    for conc in concurrencies:
        subset = [r for r in results if r.concurrency == conc]
        for proto in ("HTTP", "WS", "TCP"):
            m = {x.server: x for x in subset if x.protocol == proto}
            tpl, spr = m.get("template"), m.get("spring")
            if not tpl or not spr:
                continue
            if tpl.errors == 0 and spr.errors > 0:
                tpl_wins += 2
            elif spr.errors == 0 and tpl.errors > 0:
                spr_wins += 2
            elif tpl.rps > spr.rps:
                tpl_wins += 1
            elif spr.rps > tpl.rps:
                spr_wins += 1

    if tpl_wins > spr_wins:
        overall = "serverTemplate 综合更优（吞吐/稳定性）"
    elif spr_wins > tpl_wins:
        overall = "ASprintBootServer 综合更优（吞吐/稳定性）"
    else:
        overall = "两者持平"

    lines += [
        "",
        "### 综合结论",
        "",
        f"| 指标 | serverTemplate | ASprintBoot |",
        f"|------|----------------|-------------|",
        f"| 吞吐领先场次 | {tpl_wins} | {spr_wins} |",
        f"| 总错误数 | {tpl_err_total} | {spr_err_total} |",
        f"| **判定** | **{overall}** | |",
        "",
    ]
    lines += ["", "### 详细数据", ""]
    for conc in concurrencies:
        lines += [f"#### 并发 {conc}", ""]
        for key in ("template", "spring"):
            t = TARGETS[key]
            subset = [r for r in results if r.server == key and r.concurrency == conc]
            if not subset:
                continue
            lines += [
                f"**{t.label}**",
                "",
                "| 协议 | req/s | ok | err | p50 ms | p99 ms | max ms |",
                "|------|-------|----|----|--------|--------|--------|",
            ]
            for r in subset:
                lines.append(
                    f"| {r.protocol} | {r.rps:.1f} | {r.ok} | {r.errors} | "
                    f"{r.p50_ms:.2f} | {r.p99_ms:.2f} | {r.max_ms:.2f} |"
                )
            lines.append("")

    lines += [
        "### 说明",
        "",
        "1. **serverTemplate**：自研 framework + Netty，HTTP `/template/health`，WS/TCP 二进制帧（cmd 9001/9002）。",
        "2. **ASprintBootServer**：Spring Boot 3 官方参考实现，HTTP `/api/health`，Tomcat WebSocket + Netty TCP。",
        "3. HTTP 两栈均使用 keep-alive 长连接压测（framework 已支持）。",
        "4. 两栈 WS/TCP 协议不同，对比的是 **同机 localhost 下各协议 echo/health 路径的吞吐与延迟**，非字节级等价负载。",
        "5. **隔离测试**：每次只启动一个服务，测完再测另一个，避免 CPU/端口争用。",
        "6. 复现命令：`" + repro_cmd + "`。",
        "",
    ]
    return "\n".join(lines)


def run_bench_for_server(
    host: str,
    server_key: str,
    concurrency_list: list[int],
    count: int,
    *,
    isolated: bool,
) -> list[BenchResult]:
    target = TARGETS[server_key]
    all_results: list[BenchResult] = []
    for conc in concurrency_list:
        print(f"\n{'#'*70}\n# {target.label} | 并发: {conc}\n{'#'*70}")
        all_results.extend(run_server_bench(host, target, conc, count, isolated=isolated))
    return all_results


def evaluate_template_full_win(
    results: list[BenchResult], concurrencies: list[int]
) -> tuple[bool, list[str]]:
    """判定 template 是否在全部协议×并发档位上吞吐领先且零错误。"""
    slots: list[tuple[str, int]] = []
    for conc in concurrencies:
        for proto in ("HTTP", "WS", "TCP"):
            slots.append((proto, conc))
    return evaluate_template_slots(results, slots, require_zero_errors=True)


def evaluate_template_slots(
    results: list[BenchResult],
    slots: list[tuple[str, int]],
    *,
    require_zero_errors: bool = True,
) -> tuple[bool, list[str]]:
    failures: list[str] = []
    if require_zero_errors:
        tpl_err = sum(r.errors for r in results if r.server == "template")
        if tpl_err > 0:
            failures.append(f"template 总错误数 {tpl_err} > 0")
    for proto, conc in slots:
        subset = [r for r in results if r.concurrency == conc]
        m = {x.server: x for x in subset if x.protocol == proto}
        tpl, spr = m.get("template"), m.get("spring")
        if not tpl or not spr:
            failures.append(f"缺少数据: 并发={conc} 协议={proto}")
            continue
        if require_zero_errors and tpl.errors > 0:
            failures.append(f"template {proto} 并发={conc} 错误={tpl.errors}")
        if tpl.rps <= spr.rps:
            failures.append(
                f"{proto} 并发={conc}: template {tpl.rps:.1f} req/s "
                f"<= spring {spr.rps:.1f} req/s"
            )
    return len(failures) == 0, failures


def parse_slot_list(raw: str) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            raise ValueError(f"invalid slot: {part}")
        proto, conc_s = part.split(":", 1)
        proto = proto.strip().upper()
        if proto not in ("HTTP", "WS", "TCP"):
            raise ValueError(f"invalid protocol in slot: {part}")
        out.append((proto, int(conc_s.strip())))
    if not out:
        raise ValueError("slot list is empty")
    return out


def cmd_merge(args: argparse.Namespace) -> int:
    all_results: list[BenchResult] = []
    metas: list[dict] = []
    for path_str in args.merge:
        path = Path(path_str)
        if not path.exists():
            print(f"文件不存在: {path}", file=sys.stderr)
            return 1
        results, meta = load_results(path)
        all_results.extend(results)
        metas.append(meta)

    conc_set: list[int] = []
    for m in metas:
        for c in m.get("concurrency_list", []):
            if c not in conc_set:
                conc_set.append(c)

    meta = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "host": args.host,
        "concurrency_list": conc_set or parse_concurrency_list(args.concurrency),
        "count": metas[0].get("count", args.count) if metas else args.count,
        "title": args.title,
        "mode": "同机逐台隔离压测（一次只运行一个服务）",
        "repro_cmd": (
            "scripts\\run_isolated_bench.ps1 "
            f"-Concurrency {args.concurrency} -Count {args.count}"
        ),
    }
    md = render_markdown(all_results, meta)
    report_path = Path(args.report) if args.report else Path(__file__).resolve().parent.parent / "bench_report_section.md"
    report_path.write_text(md, encoding="utf-8")
    print(f"\n对比报告已写入: {report_path}")
    print(md)

    if getattr(args, "require_template_win", False):
        conc_list = meta["concurrency_list"]
        ok, failures = evaluate_template_full_win(all_results, conc_list)
        if ok:
            print("\n[PASS] serverTemplate 全部协议×并发档位领先且零错误。")
        else:
            print("\n[FAIL] serverTemplate 未达成全面领先：", file=sys.stderr)
            for f in failures:
                print(f"  - {f}", file=sys.stderr)
            return 2

    if getattr(args, "require_slots", ""):
        try:
            slots = parse_slot_list(args.require_slots)
        except ValueError as e:
            print(str(e), file=sys.stderr)
            return 1
        ok, failures = evaluate_template_slots(all_results, slots, require_zero_errors=True)
        if ok:
            print(f"\n[PASS] 指定档位 {args.require_slots} 全部领先且零错误。")
        else:
            print(f"\n[FAIL] 指定档位未全部领先：", file=sys.stderr)
            for f in failures:
                print(f"  - {f}", file=sys.stderr)
            return 2
    return 0


def parse_concurrency_list(raw: str) -> list[int]:
    out: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        n = int(part)
        if n < 1:
            raise ValueError(f"invalid concurrency: {n}")
        out.append(n)
    if not out:
        raise ValueError("concurrency list is empty")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare serverTemplate vs ASprintBootServer (isolated)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("-c", "--concurrency", default="100,400")
    parser.add_argument("-n", "--count", type=int, default=8000)
    parser.add_argument("--report", default="")
    parser.add_argument("--title", default="压力测试报告（vs ASprintBootServer）")
    parser.add_argument(
        "--server",
        choices=("template", "spring"),
        help="只压测指定服务（隔离模式，对手服务须已停止）",
    )
    parser.add_argument("--save", default="", help="将本次结果保存为 JSON")
    parser.add_argument(
        "--merge",
        nargs="+",
        metavar="JSON",
        help="合并多次隔离测试结果并生成对比报告",
    )
    parser.add_argument(
        "--require-template-win",
        action="store_true",
        help="merge 时要求 template 全部协议×并发领先且零错误，否则 exit 2",
    )
    parser.add_argument(
        "--require-slots",
        default="",
        help="merge 时仅校验指定档位，如 WS:1000,TCP:2000",
    )
    parser.add_argument(
        "--no-isolated-check",
        action="store_true",
        help="跳过对手服务是否已停止的检查（不推荐）",
    )
    args = parser.parse_args()

    if args.merge:
        return cmd_merge(args)

    if not args.server:
        print(
            "请指定 --server template|spring 逐台压测，"
            "或使用 --merge 合并结果。\n"
            "推荐: scripts\\run_isolated_bench.ps1",
            file=sys.stderr,
        )
        return 1

    try:
        concurrency_list = parse_concurrency_list(args.concurrency)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1

    isolated = not args.no_isolated_check
    all_results = run_bench_for_server(
        args.host, args.server, concurrency_list, args.count, isolated=isolated
    )
    if not all_results:
        return 1

    meta = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "host": args.host,
        "concurrency_list": concurrency_list,
        "count": args.count,
        "title": args.title,
        "server": args.server,
        "mode": "单服务隔离压测",
        "repro_cmd": (
            f"py -3 tests/compare_spring_bench.py --server {args.server} "
            f"-c {args.concurrency} -n {args.count}"
        ),
    }

    if args.save:
        save_path = Path(args.save)
        save_results(save_path, all_results, meta)
        print(f"\n结果已保存: {save_path}")
    else:
        print("\n提示: 使用 --save bench_data/<server>.json 保存结果，再用 --merge 生成对比报告。")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
