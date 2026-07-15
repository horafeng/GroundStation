"""Demo临时无人机协议UDP模拟接收器。"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import socket
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ground_station.drone_protocol import (  # noqa: E402
    SequenceMonitor,
    TemporaryDemoDecoder,
    TemporaryProtocolError,
)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="接收并验证64字节Demo临时无人机协议")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=7000)
    parser.add_argument("--count", type=int, default=0, help="0持续接收，否则收到指定帧数后退出")
    parser.add_argument("--timeout", type=float, default=0.5, help="Socket超时秒数，用于可中断退出")
    return parser


def main() -> int:
    args = build_argument_parser().parse_args()
    if not 1 <= args.port <= 65535:
        raise SystemExit("端口必须在1..65535")
    if args.count < 0 or args.timeout <= 0:
        raise SystemExit("count不能为负且timeout必须大于0")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    decoder = TemporaryDemoDecoder()
    monitor = SequenceMonitor()
    received = 0
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(args.timeout)
    sock.bind((args.host, args.port))
    logging.info("监听 %s:%d；协议为Demo临时协议，不是正式无人机协议", args.host, args.port)
    try:
        while args.count == 0 or received < args.count:
            try:
                payload, source = sock.recvfrom(65535)
            except socket.timeout:
                continue
            received += 1
            logging.info("source=%s:%d bytes=%d hex=%s", *source, len(payload), payload.hex(" ").upper())
            try:
                frame = decoder.decode(payload)
            except TemporaryProtocolError as error:
                logging.error("拒绝报文 code=%s message=%s", error.code.value, error.message)
                continue
            diagnostic = monitor.observe(frame.message_sequence, time.monotonic())
            fields = dataclasses.asdict(frame)
            fields["mode"] = {"value": int(frame.mode), "name": frame.mode.name}
            fields["reserved"] = frame.reserved.hex(" ").upper()
            fields["crc32"] = f"0x{frame.crc32:08X}"
            fields["sequence_status"] = diagnostic.status
            fields["missing_in_event"] = diagnostic.missing_count
            fields["duplicate_total"] = monitor.duplicates
            fields["missing_total"] = monitor.missing
            fields["out_of_order_total"] = monitor.out_of_order
            fields["measured_frequency_hz"] = monitor.measured_frequency_hz
            print(json.dumps(fields, ensure_ascii=False, indent=2))
    except KeyboardInterrupt:
        logging.info("用户终止接收")
    finally:
        sock.close()
        logging.info(
            "接收器已关闭 received=%d duplicate=%d missing=%d out_of_order=%d",
            received,
            monitor.duplicates,
            monitor.missing,
            monitor.out_of_order,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
