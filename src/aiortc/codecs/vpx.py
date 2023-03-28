import multiprocessing
import logging
import random
from struct import pack, unpack_from
from typing import List, Tuple, Type, TypeVar, cast

from av import VideoFrame
from av.frame import Frame

from ..jitterbuffer import JitterFrame
from ..mediastreams import VIDEO_CLOCK_RATE, VIDEO_TIME_BASE, convert_timebase
from ._vpx import ffi, lib
from .base import Decoder, Encoder

import os
import math

DEFAULT_BITRATE = int(os.environ.get('VPX_DEFAULT_BITRATE', 500000))
MIN_BITRATE = int(os.environ.get('VPX_MIN_BITRATE', 50000))
MAX_BITRATE = int(os.environ.get('VPX_MAX_BITRATE', 150000000))

MAX_FRAME_RATE = 30
PACKET_MAX = 1300

DESCRIPTOR_T = TypeVar("DESCRIPTOR_T", bound="VpxPayloadDescriptor")
logger = logging.getLogger(__name__)


def number_of_threads(pixels: int, cpus: int) -> int:
    if pixels >= 1920 * 1080 and cpus > 8:
        return 8
    elif pixels > 1280 * 960 and cpus >= 6:
        return 3
    elif pixels > 640 * 480 and cpus >= 3:
        return 2
    else:
        return 1


class VpxPayloadDescriptor:
    def __init__(
        self,
        partition_start,
        partition_id,
        picture_id=None,
        tl0picidx=None,
        tid=None,
        keyidx=None,
    ) -> None:
        self.partition_start = partition_start
        self.partition_id = partition_id
        self.picture_id = picture_id
        self.tl0picidx = tl0picidx
        self.tid = tid
        self.keyidx = keyidx

    def __bytes__(self) -> bytes:
        octet = (self.partition_start << 4) | self.partition_id

        ext_octet = 0
        if self.picture_id is not None:
            ext_octet |= 1 << 7
        if self.tl0picidx is not None:
            ext_octet |= 1 << 6
        if self.tid is not None:
            ext_octet |= 1 << 5
        if self.keyidx is not None:
            ext_octet |= 1 << 4

        if ext_octet:
            data = pack("!BB", (1 << 7) | octet, ext_octet)
            if self.picture_id is not None:
                if self.picture_id < 128:
                    data += pack("!B", self.picture_id)
                else:
                    data += pack("!H", (1 << 15) | self.picture_id)
            if self.tl0picidx is not None:
                data += pack("!B", self.tl0picidx)
            if self.tid is not None or self.keyidx is not None:
                t_k = 0
                if self.tid is not None:
                    t_k |= (self.tid[0] << 6) | (self.tid[1] << 5)
                if self.keyidx is not None:
                    t_k |= self.keyidx
                data += pack("!B", t_k)
        else:
            data = pack("!B", octet)

        return data

    def __repr__(self) -> str:
        return (
            f"VpxPayloadDescriptor(S={self.partition_start}, "
            f"PID={self.partition_id}, pic_id={self.picture_id})"
        )

    @classmethod
    def parse(cls: Type[DESCRIPTOR_T], data: bytes) -> Tuple[DESCRIPTOR_T, bytes]:
        if len(data) < 1:
            raise ValueError("VPX descriptor is too short")

        # first byte
        octet = data[0]
        extended = octet >> 7
        partition_start = (octet >> 4) & 1
        partition_id = octet & 0xF
        picture_id = None
        tl0picidx = None
        tid = None
        keyidx = None
        pos = 1

        # extended control bits
        if extended:
            if len(data) < pos + 1:
                raise ValueError("VPX descriptor has truncated extended bits")

            octet = data[pos]
            ext_I = (octet >> 7) & 1
            ext_L = (octet >> 6) & 1
            ext_T = (octet >> 5) & 1
            ext_K = (octet >> 4) & 1
            pos += 1

            # picture id
            if ext_I:
                if len(data) < pos + 1:
                    raise ValueError("VPX descriptor has truncated PictureID")

                if data[pos] & 0x80:
                    if len(data) < pos + 2:
                        raise ValueError("VPX descriptor has truncated long PictureID")

                    picture_id = unpack_from("!H", data, pos)[0] & 0x7FFF
                    pos += 2
                else:
                    picture_id = data[pos]
                    pos += 1

            # unused
            if ext_L:
                if len(data) < pos + 1:
                    raise ValueError("VPX descriptor has truncated TL0PICIDX")

                tl0picidx = data[pos]
                pos += 1
            if ext_T or ext_K:
                if len(data) < pos + 1:
                    raise ValueError("VPX descriptor has truncated T/K")

                t_k = data[pos]
                if ext_T:
                    tid = ((t_k >> 6) & 3, (t_k >> 5) & 1)
                if ext_K:
                    keyidx = t_k & 0x1F
                pos += 1

        obj = cls(
            partition_start=partition_start,
            partition_id=partition_id,
            picture_id=picture_id,
            tl0picidx=tl0picidx,
            tid=tid,
            keyidx=keyidx,
        )
        return obj, data[pos:]


def _vpx_assert(err: int) -> None:
    if err != lib.VPX_CODEC_OK:
        reason = ffi.string(lib.vpx_codec_err_to_string(err))
        raise Exception("libvpx error: " + reason.decode("utf8"))


class Vp8Decoder(Decoder):
    def __init__(self) -> None:
        self.codec = ffi.new("vpx_codec_ctx_t *")
        _vpx_assert(
            lib.vpx_codec_dec_init(self.codec, lib.vpx_codec_vp8_dx(), ffi.NULL, 0)
        )

        ppcfg = ffi.new("vp8_postproc_cfg_t *")
        ppcfg.post_proc_flag = lib.VP8_DEMACROBLOCK | lib.VP8_DEBLOCK
        ppcfg.deblocking_level = 3
        lib.vpx_codec_control_(self.codec, lib.VP8_SET_POSTPROC, ppcfg)

    def __del__(self) -> None:
        lib.vpx_codec_destroy(self.codec)

    def decode(self, encoded_frame: JitterFrame) -> List[Frame]:
        frames: List[Frame] = []
        result = lib.vpx_codec_decode(
            self.codec,
            encoded_frame.data,
            len(encoded_frame.data),
            ffi.NULL,
            lib.VPX_DL_REALTIME,
        )
        
        if result == lib.VPX_CODEC_OK:
            it = ffi.new("vpx_codec_iter_t *")
            while True:
                img = lib.vpx_codec_get_frame(self.codec, it)
                if not img:
                    break
                assert img.fmt == lib.VPX_IMG_FMT_I420

                frame = VideoFrame(width=img.d_w, height=img.d_h)
                frame.pts = encoded_frame.timestamp
                frame.time_base = VIDEO_TIME_BASE

                for p in range(3):
                    i_stride = img.stride[p]
                    i_buf = ffi.buffer(img.planes[p], i_stride * img.d_h)
                    i_pos = 0

                    o_stride = frame.planes[p].line_size
                    o_buf = memoryview(cast(bytes, frame.planes[p]))
                    o_pos = 0

                    div = p and 2 or 1
                    for r in range(0, img.d_h // div):
                        o_buf[o_pos : o_pos + o_stride] = i_buf[
                            i_pos : i_pos + o_stride
                        ]
                        i_pos += i_stride
                        o_pos += o_stride

                frames.append(frame)

        return frames


class Vp8Encoder(Encoder):
    def __init__(self) -> None:
        self.cx = lib.vpx_codec_vp8_cx()

        self.cfg = ffi.new("vpx_codec_enc_cfg_t *")
        lib.vpx_codec_enc_config_default(self.cx, self.cfg, 0)

        self.buffer = bytearray(8000)
        self.codec = None
        self.picture_id = random.randint(0, (1 << 15) - 1)
        self.timestamp_increment = VIDEO_CLOCK_RATE // MAX_FRAME_RATE
        self.__target_bitrate = DEFAULT_BITRATE
        self.__update_config_needed = False
        self.enable_gcc = False
        """ This implementation of the codec seems to need a transformsation
            from target bitrate to the supplied bitrate to vpx (values in bps)
        """
        self.vpx_bitrate_conversion_dict = {(0, 30000): 100000,
                                            (30000, 60000): 200000,
                                            (60000, 90000): 400000,
                                            (90000, 120000): 500000,
                                            (120000, 240000): 1000000,
                                            (240000, 360000): 1500000,
                                            (360000, 480000): 2500000,
                                            (480000, 530000): 3000000,
                                            (530000, 600000): 5000000}

    def get_vpx_bitrate(self, target_bitrate):
        # needle_drop
        x1, y1 = 425878.500749625, 2500000
        x2, y2 = 68829.0254872563, 400000

        #xiran
        #x1, y1 = 741442.567248702 + 100000, 3000000
        #x2, y2 = 370717.508258612 + 100000, 1500000
        return int((y2 - y1)/(x2 - x1) * (target_bitrate - x1) + y1)

    def __del__(self) -> None:
        if self.codec:
            lib.vpx_codec_destroy(self.codec)

    def encode(
            self, frame: Frame, force_keyframe: bool = False, quantizer: int = 32, target_bitrate: int = 100000,
            enable_gcc: bool = False, lr_size: int=1024, bitrate_code: int=6) -> Tuple[List[bytes], int]:
        assert isinstance(frame, VideoFrame)
        if frame.format.name != "yuv420p":
            frame = frame.reformat(format="yuv420p")

        if self.codec and (frame.width != self.cfg.g_w or frame.height != self.cfg.g_h):
            lib.vpx_codec_destroy(self.codec)
            self.codec = None

        self.enable_gcc = enable_gcc
        if not self.codec:
            # create codec
            self.codec = ffi.new("vpx_codec_ctx_t *")
            self.cfg.g_timebase.num = 1
            self.cfg.g_timebase.den = VIDEO_CLOCK_RATE
            self.cfg.g_lag_in_frames = 0
            self.cfg.g_threads = number_of_threads(
                frame.width * frame.height, multiprocessing.cpu_count()
            )
            self.cfg.g_w = frame.width
            self.cfg.g_h = frame.height
            self.cfg.rc_resize_allowed = 0
            self.cfg.rc_end_usage = lib.VPX_CBR
            """ quantizer = -1 is the full range quantizer in range 0 and 63 """
            self.cfg.rc_min_quantizer = quantizer if quantizer > 0 else 0
            self.cfg.rc_max_quantizer = quantizer if quantizer > 0 else 63
            self.cfg.rc_undershoot_pct = 100
            self.cfg.rc_overshoot_pct = 15
            self.cfg.rc_buf_initial_sz = 500
            self.cfg.rc_buf_optimal_sz = 600
            self.cfg.rc_buf_sz = 1000
            self.cfg.kf_mode = lib.VPX_KF_AUTO
            self.cfg.kf_max_dist = 3000
            self.vpx_min_bitrate = target_bitrate
            self.vpx_max_bitrate = target_bitrate

            if quantizer < 0 and not enable_gcc and MIN_BITRATE != MAX_BITRATE:
                """
                    Setting the bitrate to target_bitrate in quantizer when full range
                    if MIN_BITRATE != MAX_BITRATE
                """
                vpx_bitrate = self.get_vpx_bitrate(target_bitrate)
                if vpx_bitrate is not None:
                    self.vpx_min_bitrate = vpx_bitrate
                    self.vpx_max_bitrate = vpx_bitrate
                    self.__target_bitrate = vpx_bitrate

            logger.info(f"encoder's config: min_quantizer {str(self.cfg.rc_min_quantizer)}, "\
                        f"max_quantizer {str(self.cfg.rc_max_quantizer)}, "\
                        f"kf_max_dist {str(self.cfg.kf_max_dist)}, "\
                        f"DEFAULT_BITRATE {self.__target_bitrate}, MIN_BITRATE {self.vpx_min_bitrate}, "\
                        f"MAX_BITRATE {self.vpx_max_bitrate}, "\
                        f"buf_optimal_sz {str(self.cfg.rc_buf_optimal_sz)}, buf_sz {str(self.cfg.rc_buf_sz)}, "\
                        f"buf_initial_sz {str(self.cfg.rc_buf_initial_sz)}, ")
            self.__update_config()
            _vpx_assert(lib.vpx_codec_enc_init(self.codec, self.cx, self.cfg, 0))

            lib.vpx_codec_control_(
                self.codec, lib.VP8E_SET_NOISE_SENSITIVITY, ffi.cast("int", 4)
            )
            lib.vpx_codec_control_(
                self.codec, lib.VP8E_SET_STATIC_THRESHOLD, ffi.cast("int", 1)
            )
            lib.vpx_codec_control_(
                self.codec, lib.VP8E_SET_CPUUSED, ffi.cast("int", -6)
            )
            lib.vpx_codec_control_(
                self.codec,
                lib.VP8E_SET_TOKEN_PARTITIONS,
                ffi.cast("int", lib.VP8_ONE_TOKENPARTITION),
            )

            # create image on a dummy buffer, we will fill the pointers during encoding
            self.image = ffi.new("vpx_image_t *")
            lib.vpx_img_wrap(
                self.image,
                lib.VPX_IMG_FMT_I420,
                frame.width,
                frame.height,
                1,
                ffi.cast("void*", 1),
            )
        elif self.__update_config_needed:
            self.__update_config()
            _vpx_assert(lib.vpx_codec_enc_config_set(self.codec, self.cfg))

        # setup image
        for p in range(3):
            self.image.planes[p] = ffi.cast("void*", frame.planes[p].buffer_ptr)
            self.image.stride[p] = frame.planes[p].line_size

        # encode frame
        flags = 0
        if force_keyframe:
            flags |= lib.VPX_EFLAG_FORCE_KF
        _vpx_assert(
            lib.vpx_codec_encode(
                self.codec,
                self.image,
                frame.pts,
                self.timestamp_increment,
                flags,
                lib.VPX_DL_REALTIME,
            )
        )

        it = ffi.new("vpx_codec_iter_t *")
        length = 0
        while True:
            pkt = lib.vpx_codec_get_cx_data(self.codec, it)
            if not pkt:
                break
            elif pkt.kind == lib.VPX_CODEC_CX_FRAME_PKT:
                # resize buffer if needed
                if length + pkt.data.frame.sz > len(self.buffer):
                    new_buffer = bytearray(length + pkt.data.frame.sz)
                    new_buffer[0:length] = self.buffer[0:length]
                    self.buffer = new_buffer

                # append new data
                self.buffer[length : length + pkt.data.frame.sz] = ffi.buffer(
                    pkt.data.frame.buf, pkt.data.frame.sz
                )
                length += pkt.data.frame.sz

        # Add the resolution and the bitrate information
        """ Adding the resolution of frame (lr_size) as one byte
            to the payload. resolution = 2 ** (int(resolution_payload))
            Adding bitrate_code as one byte to the payload
        """
        if lr_size is None:
            lr_size = 1024
        if bitrate_code is None:
            bitrate_code = 6
        resolution_bytes = bytes([int(math.log(lr_size,2))])
        bitrate_bytes = bytes([int(bitrate_code)])
        # resize buffer if needed
        if length + len(resolution_bytes) + len(bitrate_bytes) > len(self.buffer):
            new_buffer = bytearray(length + len(resolution_bytes) + len(bitrate_bytes))
            new_buffer[0:length] = self.buffer[0:length]
            self.buffer = new_buffer

        # append new data
        self.buffer[length : length + len(resolution_bytes)] = resolution_bytes
        length += len(resolution_bytes)

        self.buffer[length : length + len(bitrate_bytes)] = bitrate_bytes
        length += len(resolution_bytes)

        # packetize
        payloads = []
        descr = VpxPayloadDescriptor(
            partition_start=1, partition_id=0, picture_id=self.picture_id
        )
        pos = 0
        while pos < length:
            descr_bytes = bytes(descr)
            size = min(length - pos, PACKET_MAX - len(descr_bytes))
            # TODO: add the reseloution information here (first byte of the buffer)
            # make sure that the buffer output is the same as input of jitterbuffer
            # TODO: add assertions to the code
            # dump all the outputs of the encoder and the inputs of the jitterbuffer
            payloads.append(descr_bytes + self.buffer[pos : pos + size])
            descr.partition_start = 0
            pos += size
        self.picture_id = (self.picture_id + 1) % (1 << 15)

        timestamp = convert_timebase(frame.pts, frame.time_base, VIDEO_TIME_BASE)
        logger.warning("encoding frame " + str(timestamp) + " type:" +  str(frame.pict_type) + " force keyframe:" + str(force_keyframe))
        return payloads, timestamp

    @property
    def target_bitrate(self) -> int:
        """
        Target bitrate in bits per second.
        """
        return self.__target_bitrate

    @target_bitrate.setter
    def target_bitrate(self, bitrate: int) -> None:
        if self.enable_gcc:
            vpx_bitrate = self.get_vpx_bitrate(bitrate)
            if vpx_bitrate is not None:
                bitrate = vpx_bitrate
            else:
                bitrate = int((bitrate * 1000 / 173 + 184971))

            if bitrate != self.__target_bitrate:
                self.__target_bitrate = bitrate
                self.vpx_min_bitrate = bitrate
                self.vpx_max_bitrate = bitrate
                self.__update_config_needed = True

    def __update_config(self) -> None:
        self.cfg.rc_target_bitrate = self.__target_bitrate // 1000
        self.__update_config_needed = False


def vp8_depayload(payload: bytes) -> bytes:
    descriptor, data = VpxPayloadDescriptor.parse(payload)
    return data
