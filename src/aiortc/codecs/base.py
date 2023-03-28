from abc import ABCMeta, abstractmethod
from typing import List, Tuple

from av.frame import Frame

from ..jitterbuffer import JitterFrame


class Decoder(metaclass=ABCMeta):
    @abstractmethod
    def decode(self, encoded_frame: JitterFrame) -> List[Frame]:
        pass  # pragma: no cover


class Encoder(metaclass=ABCMeta):
    @abstractmethod
    def encode(
            self, frame: Frame, force_keyframe: bool = False, quantizer: int=32, lr_size=1024, bitrate_code=6
    ) -> Tuple[List[bytes], int]:
        pass  # pragma: no cover
