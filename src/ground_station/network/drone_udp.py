"""只负责发送bytes的无人机UDP传输。"""

from __future__ import annotations

import socket
import threading


class DroneUdpTransport:
    def __init__(
        self,
        host: str,
        port: int,
        *,
        socket_factory: type[socket.socket] = socket.socket,
    ) -> None:
        if not host:
            raise ValueError("host不能为空")
        if not 1 <= port <= 65535:
            raise ValueError("port必须在1..65535")
        self.endpoint = (host, port)
        self._socket = socket_factory(socket.AF_INET, socket.SOCK_DGRAM)
        self._closed = False
        self._lock = threading.Lock()

    def send(self, payload: bytes) -> int:
        if not isinstance(payload, bytes):
            raise TypeError("DroneUdpTransport只接受bytes")
        with self._lock:
            if self._closed:
                raise OSError("DroneUdpTransport已关闭")
            return self._socket.sendto(payload, self.endpoint)

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._closed = True
                self._socket.close()

    def __enter__(self) -> "DroneUdpTransport":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
