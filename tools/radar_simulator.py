"""独立雷达 UDP 模拟发送程序。"""

from __future__ import annotations

import argparse
import logging
import socket
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ground_station.config import RadarProtocolSettings  # noqa: E402
from ground_station.radar_protocol.simulator import (  # noqa: E402
    FIXTURE_SCENARIOS,
    scenario_datagram,
    write_hex_fixtures,
)

SCENARIOS = (
    "zero",
    "one",
    "multi",
    "multi-moving",
    "multi-moving-clear",
    "moving",
    "cleared",
    "duplicate-display",
    "bad-length",
    "bad-checksum",
    "bad-tail",
)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="发送正式布局的 Demo 雷达航迹 UDP 报文")
    parser.add_argument("--scenario", choices=SCENARIOS, default="multi")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=6000)
    parser.add_argument("--count", type=int, default=1, help="发送次数；0 表示持续发送")
    parser.add_argument("--interval-ms", type=int, default=200)
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "config" / "radar_demo.example.json",
    )
    parser.add_argument("--hex-only", action="store_true", help="仅输出十六进制，不发送 UDP")
    parser.add_argument(
        "--write-fixtures",
        type=Path,
        help=f"生成 {len(FIXTURE_SCENARIOS)} 个十六进制夹具并退出",
    )
    return parser


def main() -> int:
    args = build_argument_parser().parse_args()
    if not 0 <= args.port <= 65535:
        raise SystemExit("端口必须在 0..65535")
    if args.count < 0:
        raise SystemExit("count 不能为负数")
    if args.interval_ms < 1:
        raise SystemExit("interval-ms 必须大于 0")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = RadarProtocolSettings.from_json(args.config)
    for message in settings.assumption_messages:
        logging.warning(message)

    if args.write_fixtures:
        paths = write_hex_fixtures(args.write_fixtures, settings)
        for path in paths:
            logging.info("已生成夹具: %s", path)
        return 0

    sock = None if args.hex_only else socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    tick = 0
    try:
        while args.count == 0 or tick < args.count:
            data = scenario_datagram(args.scenario, tick=tick, settings=settings)
            logging.info(
                "scenario=%s frame=%d bytes=%d hex=%s",
                args.scenario,
                tick,
                len(data),
                data.hex(" ").upper(),
            )
            if sock is not None:
                sock.sendto(data, (args.host, args.port))
                logging.info("已发送至 %s:%d", args.host, args.port)
            tick += 1
            if args.count == 0 or tick < args.count:
                time.sleep(args.interval_ms / 1000.0)
    except KeyboardInterrupt:
        logging.info("用户终止模拟发送")
    finally:
        if sock is not None:
            sock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
