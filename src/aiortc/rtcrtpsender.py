import asyncio
import logging
import random
import time
import traceback
import uuid
from typing import Dict, List, Optional, Union
import datetime

from . import clock, rtp
from .codecs import get_capabilities, get_encoder, is_rtx
from .codecs.base import Encoder
from .exceptions import InvalidStateError
from .mediastreams import MediaStreamError, MediaStreamTrack
from .rtcrtpparameters import RTCRtpCodecParameters, RTCRtpSendParameters
from .rtp import (
    RTCP_PSFB_APP,
    RTCP_PSFB_PLI,
    RTCP_RTPFB_NACK,
    AnyRtcpPacket,
    RtcpByePacket,
    RtcpPsfbPacket,
    RtcpRrPacket,
    RtcpRtpfbPacket,
    RtcpSdesPacket,
    RtcpSenderInfo,
    RtcpSourceInfo,
    RtcpSrPacket,
    RtpPacket,
    unpack_remb_fci,
    wrap_rtx,
)
from .stats import (
    RTCOutboundRtpStreamStats,
    RTCRemoteInboundRtpStreamStats,
    RTCStatsReport,
)
from .utils import random16, random32, uint16_add, uint32_add
import math
import numpy as np
from skimage import img_as_float32
import torch.nn.functional as F
import torch
import av

logger = logging.getLogger(__name__)

RTP_HISTORY_SIZE = 128
RTT_ALPHA = 0.85
BITRATE_PAYLOAD_DICT = {15000: 0,
                        45000: 1,
                        75000: 2,
                        105000: 3,
                        180000: 4,
                        420000: 5,
                        600000: 6}
INV_BITRATE_PAYLOAD_DICT = {v: k for k, v in BITRATE_PAYLOAD_DICT.items()}
BITRATE_ESTIMATION = "perfect"
NUM_ROWS = 10
NUMBER_OF_BITS = 16

def frame_to_tensor(frame, device):
    array = np.expand_dims(frame, 0).transpose(0, 3, 1, 2)
    array = torch.from_numpy(array)
    return array.float().to(device)


def resize_tensor_to_array(input_tensor, output_size, device, mode='nearest'):
    """ resizes a float tensor of range 0.0-1.0 to an int numpy array
        of output_size
    """
    output_array = F.interpolate(input_tensor, output_size, mode=mode).data.cpu().numpy()
    output_array = np.transpose(output_array, [0, 2, 3, 1])[0]
    output_array *= 255
    output_array = output_array.astype(np.uint8)
    return output_array


def stamp_frame(frame, frame_index, frame_pts, frame_time_base):
    """ stamp frame with barcode for frame index before transmission
    """
    frame_array = frame.to_rgb().to_ndarray()
    stamped_frame = np.zeros((frame_array.shape[0] + NUM_ROWS,
                            frame_array.shape[1], frame_array.shape[2]))
    k = frame_array.shape[1] // NUMBER_OF_BITS
    stamped_frame[:-NUM_ROWS, :, :] = frame_array
    id_str = f'{frame_index+1:0{NUMBER_OF_BITS}b}'

    for i in range(len(id_str)):
        if id_str[i] == '0':
            for j in range(k):
                for s in range(NUM_ROWS):
                    stamped_frame[-s-1, i * k + j, 0] = 0
                    stamped_frame[-s-1, i * k + j, 1] = 0
                    stamped_frame[-s-1, i * k + j, 2] = 0
        elif id_str[i] == '1':
            for j in range(k):
                for s in range(NUM_ROWS):
                    stamped_frame[-s-1, i * k + j, 0] = 255
                    stamped_frame[-s-1, i * k + j, 1] = 255
                    stamped_frame[-s-1, i * k + j, 2] = 255

    stamped_frame = np.uint8(stamped_frame)
    final_frame = av.VideoFrame.from_ndarray(stamped_frame)
    final_frame.pts = frame_pts
    final_frame.time_base = frame_time_base
    logger.debug(f"RTCRtpSender stamping frame %s with frame_index %s", frame, frame_index)
    return final_frame


def destamp_frame(frame):
    """ retrieve frame index and original frame from barcoded frame
    """
    frame_array = frame.to_rgb().to_ndarray()
    k = frame_array.shape[1] // NUMBER_OF_BITS
    destamped_frame = frame_array[:-NUM_ROWS]

    frame_id = frame_array[-NUM_ROWS:, :, :]
    frame_id = frame_id.mean(0)
    frame_id = frame_id[frame_array.shape[1] - k*NUMBER_OF_BITS:, :]

    frame_id = np.reshape(frame_id, [NUMBER_OF_BITS, k, 3])
    frame_id = frame_id.mean(axis=(1,2))

    frame_id = (frame_id > (frame_id.max() + frame_id.min()) / 2 * 1.2 ).astype(int)
    frame_id = ((2 ** (NUMBER_OF_BITS - 1 - np.arange(NUMBER_OF_BITS))) * frame_id).sum()
    frame_id = frame_id - 1

    destamped_frame = np.uint8(destamped_frame)
    final_frame = av.VideoFrame.from_ndarray(destamped_frame)
    logger.warning(
        "Detamping the frame %s with resulting frame_index %s in the sender",
         str(frame), str(frame_id)
    )
    return final_frame, frame_id


class RTCRtpSender:
    """
    The :class:`RTCRtpSender` interface provides the ability to control and
    obtain details about how a particular :class:`MediaStreamTrack` is encoded
    and sent to a remote peer.

    :param trackOrKind: Either a :class:`MediaStreamTrack` instance or a
                         media kind (`'audio'` or `'video'`).
    :param transport: An :class:`RTCDtlsTransport`.
    """

    def __init__(self, trackOrKind: Union[MediaStreamTrack, str], transport, quantizer,
            target_bitrate, enable_gcc) -> None:
        if transport.state == "closed":
            raise InvalidStateError

        if isinstance(trackOrKind, MediaStreamTrack):
            self.__kind = trackOrKind.kind
            self.replaceTrack(trackOrKind)
        else:
            self.__kind = trackOrKind
            self.replaceTrack(None)
        self.__cname: Optional[str] = None
        self._ssrc = random32()
        self._rtx_ssrc = random32()
        # FIXME: how should this be initialised?
        self._stream_id = str(uuid.uuid4())
        self.__lr_encoders : Dict[int, Optional[Encoder]] = {}
        self.__encoder : Optional[Encoder] = None
        self.__force_keyframe = False
        self.__quantizer = quantizer
        self.__target_bitrate = target_bitrate
        self.__gcc_target_bitrate = 500000
        self.__enable_gcc = enable_gcc
        self.__loop = asyncio.get_event_loop()
        self.__mid: Optional[str] = None
        self.__rtp_exited = asyncio.Event()
        self.__rtp_header_extensions_map = rtp.HeaderExtensionsMap()
        self.__rtp_task: Optional[asyncio.Future[None]] = None
        self.__rtp_history: Dict[int, RtpPacket] = {}
        self.__rtcp_exited = asyncio.Event()
        self.__rtcp_task: Optional[asyncio.Future[None]] = None
        self.__rtx_payload_type: Optional[int] = None
        self.__rtx_sequence_number = 61495 #random16()
        self.__started = False
        self.__stats = RTCStatsReport()
        self.__transport = transport

        # stats
        self.__lsr: Optional[int] = None
        self.__lsr_time: Optional[float] = None
        self.__ntp_timestamp = 0
        self.__prev_ntp_timestamp = -1
        self.__rtp_timestamp = 0
        self.__octet_count = 0
        self.__packet_count = 0
        self.__rtt = None
        self.__frame_count = 0
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

    @property
    def kind(self):
        return self.__kind

    @property
    def track(self) -> MediaStreamTrack:
        """
        The :class:`MediaStreamTrack` which is being handled by the sender.
        """
        return self.__track

    @property
    def transport(self):
        """
        The :class:`RTCDtlsTransport` over which media data for the track is
        transmitted.
        """
        return self.__transport

    @classmethod
    def getCapabilities(self, kind):
        """
        Returns the most optimistic view of the system's capabilities for
        sending media of the given `kind`.

        :rtype: :class:`RTCRtpCapabilities`
        """
        return get_capabilities(kind)

    async def getStats(self) -> RTCStatsReport:
        """
        Returns statistics about the RTP sender.

        :rtype: :class:`RTCStatsReport`
        """
        self.__stats.add(
            RTCOutboundRtpStreamStats(
                # RTCStats
                timestamp=clock.current_datetime(),
                type="outbound-rtp",
                id="outbound-rtp_" + str(id(self)),
                # RTCStreamStats
                ssrc=self._ssrc,
                kind=self.__kind,
                transportId=self.transport._stats_id,
                # RTCSentRtpStreamStats
                packetsSent=self.__packet_count,
                bytesSent=self.__octet_count,
                # RTCOutboundRtpStreamStats
                trackId=str(id(self.track)),
            )
        )
        self.__stats.update(self.transport._get_stats())

        return self.__stats

    def replaceTrack(self, track: Optional[MediaStreamTrack]) -> None:
        self.__track = track
        if track is not None:
            self._track_id = track.id
        else:
            self._track_id = str(uuid.uuid4())

    def setTransport(self, transport) -> None:
        self.__transport = transport

    async def send(self, parameters: RTCRtpSendParameters) -> None:
        """
        Attempt to set the parameters controlling the sending of media.

        :param parameters: The :class:`RTCRtpSendParameters` for the sender.
        """
        if not self.__started:
            self.__cname = parameters.rtcp.cname
            self.__mid = parameters.muxId

            # make note of the RTP header extension IDs
            self.__transport._register_rtp_sender(self, parameters)
            self.__rtp_header_extensions_map.configure(parameters)

            # make note of RTX payload type
            # Vibhaa: to change codec type to h264 - change this 0 to 2
            # one is some weird retransmission protocol
            for codec in parameters.codecs:
                if (
                    is_rtx(codec)
                    and codec.parameters["apt"] == parameters.codecs[0].payloadType
                ):
                    self.__rtx_payload_type = codec.payloadType
                    break

            self.__rtp_task = asyncio.ensure_future(self._run_rtp(parameters.codecs[0]))
            self.__rtcp_task = asyncio.ensure_future(self._run_rtcp())
            self.__started = True

    async def stop(self):
        """
        Irreversibly stop the sender.
        """
        if self.__started:
            self.__transport._unregister_rtp_sender(self)
            self.__rtp_task.cancel()
            self.__rtcp_task.cancel()
            await asyncio.gather(self.__rtp_exited.wait(), self.__rtcp_exited.wait())

    async def _handle_rtcp_packet(self, packet):
        self.__log_debug("< RTCP %s arrival time: %s",
                packet, datetime.datetime.now())
        
        if isinstance(packet, (RtcpRrPacket, RtcpSrPacket)):
            for report in filter(lambda x: x.ssrc == self._ssrc, packet.reports):
                # estimate round-trip time
                if self.__lsr == report.lsr and report.dlsr:
                    rtt = time.time() - self.__lsr_time - (report.dlsr / 65536)
                    self.__log_debug("estimated rtt is %s, fraction_lost %d, lsr %s, at time %d", \
                            rtt, report.fraction_lost, report.lsr, time.time())
                    if self.__rtt is None:
                        self.__rtt = rtt
                    else:
                        self.__rtt = RTT_ALPHA * self.__rtt + (1 - RTT_ALPHA) * rtt

                self.__stats.add(
                    RTCRemoteInboundRtpStreamStats(
                        # RTCStats
                        timestamp=clock.current_datetime(),
                        type="remote-inbound-rtp",
                        id="remote-inbound-rtp_" + str(id(self)),
                        # RTCStreamStats
                        ssrc=packet.ssrc,
                        kind=self.__kind,
                        transportId=self.transport._stats_id,
                        # RTCReceivedRtpStreamStats
                        packetsReceived=self.__packet_count - report.packets_lost,
                        packetsLost=report.packets_lost,
                        jitter=report.jitter,
                        # RTCRemoteInboundRtpStreamStats
                        roundTripTime=self.__rtt,
                        fractionLost=report.fraction_lost,
                    )
                )
        elif isinstance(packet, RtcpRtpfbPacket) and packet.fmt == RTCP_RTPFB_NACK:
            for seq in packet.lost:
                self.__log_debug("dispatching retransmit %s", seq)
                await self._retransmit(seq)
        elif isinstance(packet, RtcpPsfbPacket) and packet.fmt == RTCP_PSFB_PLI:
            self.__log_debug("Received PLI")
            self._send_keyframe()
        elif isinstance(packet, RtcpPsfbPacket) and packet.fmt == RTCP_PSFB_APP:
            try:
                bitrate, ssrcs = unpack_remb_fci(packet.fci)
                if self._ssrc in ssrcs:
                    if BITRATE_ESTIMATION == 'gcc':
                        self.__log_debug(
                            "- receiver estimated maximum bitrate %d bps at time %s", bitrate, datetime.datetime.now()
                        )
                        self.__gcc_target_bitrate = bitrate
            except ValueError:
                pass


    def get_lr_size_by_bitrate(self, bitrate):
        self.gcc_bitrate_resolution_dict = {(0, 30000): 128,
                                            (30000, 110000): 256,
                                            (110000, 550000): 512,
                                            (550000, 3000000): 1024}
        for low, high in self.gcc_bitrate_resolution_dict.keys():
            if low <= bitrate < high:
                return self.gcc_bitrate_resolution_dict[(low, high)]
        return 1024


    def get_model_bitrate_by_lr_size(self, lr_size, gcc_bitrate):
        """ maps frame size to the bitrate it should be encoded  with
            respect to gcc's bitrate as well
        """
        if lr_size == 128:
            return 15000
        elif lr_size == 256:
            return 45000
        elif lr_size == 512:
            return 180000
        else:
            # 1024
            return 600000


    async def _next_encoded_frame(self, codec: RTCRtpCodecParameters):
        # get frame
        frame, frame_index, frame_pts, frame_time_base = await self.__track.recv()
        self.__log_debug("frame width %s height %s in _next_encoded_frame", frame.width, frame.height)
        # harcode the bitrate
        self.__frame_count += 1

        # bitrate of for paper
        hardcoded_bitrate = min(max(750000 - 110 * self.__frame_count, 20000) + max(0, -942500 + 110* self.__frame_count), 650000)

        # TODO for Vibha: bitrate for 1Mbps that goes down to 20kbps
        #hardcoded_bitrate = min(max(1200000 - 55 * 2 * self.__frame_count, 20000) + max(0, -942500 + 55 * 2 * self.__frame_count), 1000000)

        if BITRATE_ESTIMATION == 'perfect':
            target_bitrate = hardcoded_bitrate
            self.__log_debug(
                     "- receiver estimated maximum bitrate %d bps at time %s", hardcoded_bitrate,
                     datetime.datetime.now())
        else:
            target_bitrate = self.__gcc_target_bitrate

        lr_size = self.get_lr_size_by_bitrate(target_bitrate)
        self.__track._lr_size = lr_size

        # check network status before encoding
        # resize the frame down if the network condition is worse
        if lr_size != frame.width and self.__kind == "lr_video":
            frame_array = frame.to_rgb().to_ndarray()
            frame_tensor = frame_to_tensor(img_as_float32(frame_array), self.device)
            lr_frame_array = resize_tensor_to_array(frame_tensor, lr_size , self.device)
            frame = av.VideoFrame.from_ndarray(lr_frame_array)
            frame.pts = frame_pts
            frame.time_base = frame_time_base

        frame = stamp_frame(frame, frame_index, frame_pts, frame_time_base)

        # get the correct encoder
        if self.__kind == "lr_video":
            if lr_size not in self.__lr_encoders.keys():
                self.__lr_encoders[lr_size] = None

            if self.__lr_encoders[lr_size] == None:
                self.__lr_encoders[lr_size] = get_encoder(codec)

            self.__encoder = self.__lr_encoders[lr_size]
            if lr_size == 1024:
                enable_gcc = True
                bitrate_code = BITRATE_PAYLOAD_DICT[600000]
                quantizer = -1 #TODO
            else:
                enable_gcc = True
                bitrate_code = BITRATE_PAYLOAD_DICT[self.get_model_bitrate_by_lr_size(lr_size, target_bitrate)]
                quantizer = -1

        else: # "video", "audio", "keypoints"
            lr_size = None
            bitrate_code = None
            if self.__encoder is None:
                self.__encoder = get_encoder(codec)
            enable_gcc = True
            quantizer = self.__quantizer

        if self.__encoder and hasattr(self.__encoder, "target_bitrate"):
            self.__encoder.target_bitrate = target_bitrate

        force_keyframe = self.__force_keyframe
        self.__force_keyframe = False
        self.__log_debug("encoding frame with force keyframe %s at time %s with quantizer %s \
                target_bitrate %s enable_gcc %s, lr_size %s, bitrate_code %s",
                force_keyframe, datetime.datetime.now(), quantizer, target_bitrate,
                enable_gcc, lr_size, bitrate_code)
        return await self.__loop.run_in_executor(
            None, self.__encoder.encode, frame, force_keyframe, quantizer, target_bitrate, True
        ), lr_size, bitrate_code


    async def _retransmit(self, sequence_number: int) -> None:
        """
        Retransmit an RTP packet which was reported as lost.
        """
        packet = self.__rtp_history.get(sequence_number % RTP_HISTORY_SIZE)
        if packet and packet.sequence_number == sequence_number:
            if self.__rtx_payload_type is not None:
                print("retransmit ", packet.sequence_number)
                packet = wrap_rtx(
                    packet,
                    payload_type=self.__rtx_payload_type,
                    sequence_number=self.__rtx_sequence_number,
                    ssrc=self._rtx_ssrc,
                )
                self.__rtx_sequence_number = uint16_add(self.__rtx_sequence_number, 1)

            self.__log_debug("> %s retransmission of original %s", packet, sequence_number)
            packet_bytes = packet.serialize(self.__rtp_header_extensions_map)
            await self.transport._send_rtp(packet_bytes)

    def _send_keyframe(self) -> None:
        """
        Request the next frame to be a keyframe.
        """
        self.__force_keyframe = True

    async def _run_rtp(self, codec: RTCRtpCodecParameters) -> None:
        self.__log_debug("- RTP started")

        sequence_number = 0 #random16()
        timestamp_origin = 0 #random32()
        try:
            counter = 0
            while True:
                if not self.__track:
                    await asyncio.sleep(0.02)
                    continue

                counter += 1
                try:
                    (payloads, timestamp), lr_size, bitrate_code  = await self._next_encoded_frame(codec)   
                except:
                    continue

                self.__log_debug("Frame %s is encoded with resolution %s with len %s at time %s with bitrate_code %s ", 
                                counter, lr_size, sum([len(i) for i in payloads]), datetime.datetime.now(), bitrate_code)
                old_timestamp = timestamp
                timestamp = uint32_add(timestamp_origin, timestamp)
                if self.__kind == "lr_video" and lr_size is not None and bitrate_code is not None:
                    """ Adding the resolution of frame (lr_size) as one byte
                        to the payload. resolution = 2 ** (int(resolution_payload))
                        Adding bitrate_code as one byte to the payload
                    """
                    resolution_payload = bytes([int(math.log(lr_size,2))])
                    bitrate_payload = bytes([int(bitrate_code)])
                    payloads= [resolution_payload] + [bitrate_payload] + payloads

                for i, payload in enumerate(payloads):
                    packet = RtpPacket(
                        payload_type=codec.payloadType,
                        sequence_number=sequence_number,
                        timestamp=timestamp,
                    )
                    packet.ssrc = self._ssrc
                    packet.payload = payload
                    packet.marker = (i == len(payloads) - 1) and 1 or 0

                    # set header extensions
                    packet.extensions.abs_send_time = (
                        clock.current_ntp_time() >> 14
                    ) & 0x00FFFFFF
                    packet.extensions.mid = self.__mid

                    # send packet
                    self.__log_debug("> RTP %s (encoded frame ts: %s) %s", packet, old_timestamp, 
                                    datetime.datetime.now())
                    self.__rtp_history[
                        packet.sequence_number % RTP_HISTORY_SIZE
                    ] = packet
                    packet_bytes = packet.serialize(self.__rtp_header_extensions_map)
                    await self.transport._send_rtp(packet_bytes)

                    self.__ntp_timestamp = clock.current_ntp_time()
                    self.__rtp_timestamp = packet.timestamp
                    self.__octet_count += len(payload)
                    self.__packet_count += 1
                    sequence_number = uint16_add(sequence_number, 1)
        except (asyncio.CancelledError, ConnectionError, MediaStreamError):
            pass
        except Exception:
            # we *need* to set __rtp_exited, otherwise RTCRtpSender.stop() will hang,
            # so issue a warning if we hit an unexpected exception
            self.__log_warning(traceback.format_exc())

        # stop track
        if self.__track:
            self.__track.stop()
            self.__track = None

        self.__log_debug("- RTP finished")
        self.__rtp_exited.set()

    async def _run_rtcp(self) -> None:
        self.__log_debug("- RTCP started")

        try:
            while True:
                # The interval between RTCP packets is varied randomly over the
                # range [0.5, 1.5] times the calculated interval.
                await asyncio.sleep(0.5 + random.random())

                if self.__prev_ntp_timestamp == self.__ntp_timestamp:
                    """
                    Safety mechanism: After the video has been fully sent,
                    self.__ntp_timestamp is no longer updated in run_rtp which
                    casuses a lot of sender's RTCP packets to have the same lsr.
                    Having the same lsr produces error in identifying which received
                    RTCP packet matches which sent RTCP packet (producing negative rtt).
                    """
                    self.__ntp_timestamp = clock.current_ntp_time()

                # RTCP SR
                packets: List[AnyRtcpPacket] = [
                    RtcpSrPacket(
                        ssrc=self._ssrc,
                        sender_info=RtcpSenderInfo(
                            ntp_timestamp=self.__ntp_timestamp,
                            rtp_timestamp=self.__rtp_timestamp,
                            packet_count=self.__packet_count,
                            octet_count=self.__octet_count,
                        ),
                    )
                ]
                self.__lsr = ((self.__ntp_timestamp) >> 16) & 0xFFFFFFFF
                self.__lsr_time = time.time()
                self.__prev_ntp_timestamp = self.__ntp_timestamp

                # RTCP SDES
                if self.__cname is not None:
                    packets.append(
                        RtcpSdesPacket(
                            chunks=[
                                RtcpSourceInfo(
                                    ssrc=self._ssrc,
                                    items=[(1, self.__cname.encode("utf8"))],
                                )
                            ]
                        )
                    )

                await self._send_rtcp(packets)
        except asyncio.CancelledError:
            pass

        # RTCP BYE
        packet = RtcpByePacket(sources=[self._ssrc])
        await self._send_rtcp([packet])

        self.__log_debug("- RTCP finished")
        self.__rtcp_exited.set()

    async def _send_rtcp(self, packets: List[AnyRtcpPacket]) -> None:
        payload = b""
        for packet in packets:
            self.__log_debug("> RTCP %s at time %d", packet, time.time())
            payload += bytes(packet)

        try:
            await self.transport._send_rtp(payload)
        except ConnectionError:
            pass

    def __log_debug(self, msg: str, *args) -> None:
        logger.debug(f"RTCRtpSender(%s) {msg}", self.__kind, *args)

    def __log_warning(self, msg: str, *args) -> None:
        logger.warning(f"RTCRtpsender(%s) {msg}", self.__kind, *args)
