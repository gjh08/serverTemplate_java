#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Server 模板联调：HTTP / TCP / WebSocket"""
from __future__ import annotations

import argparse
import json
import socket
import struct
import sys
import time
import urllib.request

try:
    import websocket
except ImportError:
    websocket = None

DEFAULT_HTTP = 17080
DEFAULT_WS = 17081
DEFAULT_TCP = 17082
CMD_REQ = 9001
CMD_RESP = 9002
HEAD_SIZE = 12


def pack_frame(body: bytes) -> bytes:
    return struct.pack("<H", len(body)) + body


def pack_message(cmd: int, utag: int, payload: dict) -> bytes:
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    header = struct.pack("<HqH", cmd, utag, 0)
    return header + body


def parse_messages(data: bytes) -> list[bytes]:
    frames, i = [], 0
    while i + 2 <= len(data):
        ln = struct.unpack_from("<H", data, i)[0]
        i += 2
        if i + ln > len(data):
            break
        frames.append(data[i : i + ln])
        i += ln
    return frames


def parse_packet(raw: bytes) -> dict | None:
    if len(raw) < HEAD_SIZE:
        return None
    cmd, utag, _ = struct.unpack_from("<HqH", raw, 0)
    body = raw[HEAD_SIZE:]
    if cmd == CMD_RESP and body and body[0] != ord("{"):
        payload = decode_echo_response_body(body)
        if payload is not None:
            return {"cmd": cmd, "utag": utag, "body": payload}
    try:
        payload = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {}
    return {"cmd": cmd, "utag": utag, "body": payload}


def decode_echo_response_body(body: bytes) -> dict | None:
    """EchoResponse 二进制：seq i64 · payload u16+str · channel u16+str · ts i64"""
    off = 0
    try:
        if off + 8 > len(body):
            return None
        seq = struct.unpack_from("<q", body, off)[0]
        off += 8
        if off + 2 > len(body):
            return None
        plen = struct.unpack_from(">H", body, off)[0]
        off += 2
        if off + plen + 2 > len(body):
            return None
        payload = body[off : off + plen].decode("utf-8")
        off += plen
        clen = struct.unpack_from(">H", body, off)[0]
        off += 2
        if off + clen + 8 > len(body):
            return None
        channel = body[off : off + clen].decode("utf-8")
        off += clen
        ts = struct.unpack_from("<q", body, off)[0]
        return {"seq": seq, "payload": payload, "channel": channel, "ts": ts}
    except (struct.error, UnicodeDecodeError):
        return None


def test_http(host: str, http_port: int, timeout: float) -> bool:
    for path in ("/template/health", "/template/echo"):
        url = f"http://{host}:{http_port}{path}"
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            if body.get("code") != 0:
                print(f"[HTTP FAIL] {url} code={body.get('code')}")
                return False
            print(f"[HTTP OK] {url} -> {body.get('data')}")
    return True


def test_tcp(host: str, tcp_port: int, timeout: float) -> bool:
    sock = socket.create_connection((host, tcp_port), timeout=timeout)
    sock.settimeout(timeout)
    try:
        req = pack_message(CMD_REQ, 1001, {"seq": 1, "payload": "hello-tcp"})
        sock.sendall(pack_frame(req))
        buf = b""
        deadline = time.time() + timeout
        while time.time() < deadline:
            chunk = sock.recv(65536)
            if not chunk:
                break
            buf += chunk
            for frame in parse_messages(buf):
                pkt = parse_packet(frame)
                if pkt and pkt["cmd"] == CMD_RESP:
                    print(f"[TCP OK] {pkt['body']}")
                    return pkt["body"].get("channel") == "tcp"
        print("[TCP FAIL] no response")
        return False
    finally:
        sock.close()


def test_ws(host: str, ws_port: int, timeout: float) -> bool:
    if websocket is None:
        print("[WS SKIP] pip install websocket-client")
        return False
    url = f"ws://{host}:{ws_port}/websocket"
    ws = websocket.create_connection(url, timeout=timeout)
    try:
        req = pack_message(CMD_REQ, 2001, {"seq": 2, "payload": "hello-ws"})
        ws.send_binary(req)
        deadline = time.time() + timeout
        while time.time() < deadline:
            ws.settimeout(max(0.1, deadline - time.time()))
            try:
                raw = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            pkt = parse_packet(raw if isinstance(raw, bytes) else raw.encode())
            if pkt and pkt["cmd"] == CMD_RESP:
                print(f"[WS OK] {pkt['body']}")
                return pkt["body"].get("channel") == "ws"
        print("[WS FAIL] no response")
        return False
    finally:
        ws.close()


def main() -> int:
    p = argparse.ArgumentParser(description="Server 模板 HTTP/TCP/WS 联调")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--http", type=int, default=DEFAULT_HTTP)
    p.add_argument("--ws", type=int, default=DEFAULT_WS)
    p.add_argument("--tcp", type=int, default=DEFAULT_TCP)
    p.add_argument("--timeout", type=float, default=10.0)
    args = p.parse_args()

    print(f"target http://{args.host}:{args.http}  ws://{args.host}:{args.ws}/websocket  tcp://{args.host}:{args.tcp}")
    ok_http = test_http(args.host, args.http, args.timeout)
    ok_tcp = test_tcp(args.host, args.tcp, args.timeout)
    ok_ws = test_ws(args.host, args.ws, args.timeout)

    print("\n========== SUMMARY ==========")
    print(f"HTTP: {'PASS' if ok_http else 'FAIL'}")
    print(f"TCP:  {'PASS' if ok_tcp else 'FAIL'}")
    print(f"WS:   {'PASS' if ok_ws else 'FAIL'}")
    return 0 if ok_http and ok_tcp and ok_ws else 1


if __name__ == "__main__":
    raise SystemExit(main())
