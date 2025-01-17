from typing import List, Optional, Tuple

from .rtp import RtpPacket
from .utils import uint16_add
import logging

MAX_MISORDER = 100

logger = logging.getLogger(__name__)

class JitterFrame:
    def __init__(self, data: bytes, timestamp: int) -> None:
        self.data = data
        self.timestamp = timestamp


class JitterBuffer:
    def __init__(
        self, capacity: int, prefetch: int = 0, is_video: bool = False
    ) -> None:
        assert capacity & (capacity - 1) == 0, "capacity must be a power of 2"
        self._capacity = capacity
        self._origin: Optional[int] = None
        self._packets: List[Optional[RtpPacket]] = [None for i in range(capacity)]
        self._prefetch = prefetch
        self._is_video = is_video

    @property
    def capacity(self) -> int:
        return self._capacity

    def add(self, packet: RtpPacket) -> Tuple[bool, Optional[JitterFrame]]:
        pli_flag = False
        if self._origin is None:
            self._origin = packet.sequence_number
            delta = 0
            misorder = 0
        else:
            delta = uint16_add(packet.sequence_number, -self._origin)
            misorder = uint16_add(self._origin, -packet.sequence_number)

        if misorder < delta:
            if misorder >= MAX_MISORDER:
                self.remove(self.capacity)
                self._origin = packet.sequence_number
                if self._is_video:
                    pli_flag = True
                    logger.debug(f"Generating PLI because misorder %s exceeds max %s (Delta %s, capacity %s)", misorder, MAX_MISORDER, delta, self.capacity)
                delta = misorder = 0
            else:
                return pli_flag, None

        if delta >= self.capacity:
            # remove just enough frames to fit the received packets
            excess = delta - self.capacity + 1
            if self.smart_remove(excess):
                self._origin = packet.sequence_number
            if self._is_video:
                pli_flag = True
                logger.debug(f"Generating PLI because delta %s exceeds capacity %s", delta, self.capacity)

        pos = packet.sequence_number % self._capacity
        self._packets[pos] = packet
        if self._is_video:
            logger.debug(f"Adding packet with sequence number %s to pos %s", packet.sequence_number, pos)

        return pli_flag, self._remove_frame(packet.sequence_number)

    def _remove_frame(self, sequence_number: int) -> Optional[JitterFrame]:
        frame = None
        frames = 0
        packets = []
        remove = 0

        for count in range(self.capacity):
            pos = (self._origin + count) % self._capacity
            packet = self._packets[pos]
            if packet is None:
                break
            packets.append(packet)

            if packet.marker == 1:
                # we now have a complete frame, only store the first one
                if frame is None:
                    frame = JitterFrame(
                        data=b"".join([x._data for x in packets]), timestamp=packet.timestamp
                    )
                    remove = count + 1

                # check we have prefetched enough
                frames += 1
                if frames >= self._prefetch:
                    if self._is_video:
                        logger.debug(f"removing %s packets from origin %s", remove, self._origin)
                    self.remove(remove)
                    return frame

                # start a new frame
                packets = []

        return None

    def remove(self, count: int) -> None:
        assert count <= self._capacity
        for i in range(count):
            pos = self._origin % self._capacity
            self._packets[pos] = None
            self._origin = uint16_add(self._origin, 1)

    def smart_remove(self, count: int) -> bool:
        """
        smart_remove makes sure that all packages belonging to the same frame are removed
        it prevents sending corrupted frames to decoder
        """
        timestamp = None
        for i in range(self._capacity):
            pos = self._origin % self._capacity
            packet = self._packets[pos]
            if packet is not None:
                if i >= count and timestamp != packet.timestamp:
                    break
                timestamp = packet.timestamp
            self._packets[pos] = None
            self._origin = uint16_add(self._origin, 1)
            if i == self._capacity - 1:
                return True

        if self._is_video:
            logger.debug(f"Smart remove resulting in false with origin %s", self._origin)
        return False
