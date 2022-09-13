import asyncio
import errno
import fractions
import logging
import threading
import time
import sys
from typing import Dict, Optional, Set
import numpy as np
import concurrent.futures
import os
import datetime

import av
from av import AudioFrame, VideoFrame
from av.frame import Frame

from ..mediastreams import AUDIO_PTIME, MediaStreamError, MediaStreamTrack, KeypointsFrame

from first_order_model.fom_wrapper import FirstOrderModel
from first_order_model.reconstruction import frame_to_tensor, resize_tensor_to_array
from first_order_model.utils import get_main_config_params
from lte_wrapper import SuperResolutionModel
from skimage import img_as_float32
import torch
import torch.nn.functional as F
import yaml 
from .cached_models import checkpoint_zoo, config_paths

""" config_path, checkpoint, and main_configs are mostly used for
    generator_type in ['vpx', 'bicubic', 'swinir-lte']
"""
config_path = '/video-conf/scratch/vibhaa_tardy/final_results/training_with_encoder/lr512_tgt180/needle_drop/lr512_tgt180Kb.yaml'#os.environ.get('CONFIG_PATH', 'None')
checkpoint = '/video-conf/scratch/vibhaa_tardy/final_results/training_with_encoder/lr512_tgt180/needle_drop/00000029-checkpoint.pth.tar' #os.environ.get('CHECKPOINT_PATH', 'None')
person = os.environ.get('PERSON', 'needle_drop')
# main configs
main_configs = get_main_config_params(config_path)
frame_shape = main_configs['frame_shape']
generator_type = main_configs['generator_type']
use_lr_video = main_configs['use_lr_video']
lr_shape = main_configs['lr_size']
print(main_configs)

""" configuring the model zoo for adaptation"""
low_res_sizes = [64, 128, 256, 512]
checkpoint_paths = checkpoint_zoo[person]
model_zoo = {}

# instantiate and warm up the model
if generator_type not in ['vpx', 'bicubic']:
    time_before_instantiation = time.perf_counter()
    if generator_type == 'swinir-lte':
        model = SuperResolutionModel(config_path, checkpoint)
    elif use_lr_video: # kp-based model
        for lr_size in low_res_sizes:
            model_zoo[lr_size] = FirstOrderModel(config_paths[lr_size], checkpoint_paths[lr_size])
    else: # lr-video-based model
        lr_size = 'no_lr_video'
        low_res_sizes = ['no_lr_video']
        model_zoo[lr_size] = FirstOrderModel(config_path, checkpoint)

    for i in range(1):
        if generator_type not in ['swinir-lte']:
            """ update reference for models that need reference """
            for lr_size in low_res_sizes:
                random_array = np.random.randint(0, 255, model_zoo[lr_size].get_shape(), dtype=np.uint8)
                random_kps, src_index = model_zoo[lr_size].extract_keypoints(random_array)
                model_zoo[lr_size].update_source(src_index, random_array, random_kps)
                random_kps['source_index'] = src_index

        if use_lr_video:
            if generator_type == 'swinir-lte':
                model.predict_with_lr_video(np.random.randint(0, 255,
                        (lr_shape, lr_shape, 3), dtype=np.uint8))
            else:
                for lr_size in low_res_sizes:
                    model_zoo[lr_size].predict_with_lr_video(np.random.randint(0, 255,
                        (lr_size, lr_size, 3), dtype=np.uint8))
        else: # kp-based model
            model_zoo[lr_size].predict(random_kps)
    time_after_instantiation = time.perf_counter()
    print("Time to instantiate at time %s: %s" % (datetime.datetime.now(),
        str(time_after_instantiation - time_before_instantiation)))
    if generator_type not in ['swinir-lte']:
        for lr_size in low_res_sizes:
            model_zoo[lr_size].reset()

save_keypoints_to_file = False
save_lr_video_npy = False
save_predicted_frames = False
save_sent_frames = True
save_received_frames = True
logger = logging.getLogger(__name__)


REAL_TIME_FORMATS = [
    "alsa",
    "android_camera",
    "avfoundation",
    "bktr",
    "decklink",
    "dshow",
    "fbdev",
    "gdigrab",
    "iec61883",
    "jack",
    "kmsgrab",
    "openal",
    "oss",
    "pulse",
    "sndio",
    "rtsp",
    "v4l2",
    "vfwcap",
    "x11grab",
]

NUM_ROWS = 10
NUMBER_OF_BITS = 16

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
    return final_frame, frame_id


async def blackhole_consume(track):
    while True:
        try:
            await track.recv()
        except MediaStreamError:
            return


class MediaBlackhole:
    """
    A media sink that consumes and discards all media.
    """

    def __init__(self):
        self.__tracks = {}

    def addTrack(self, track):
        """
        Add a track whose media should be discarded.

        :param track: A :class:`aiortc.MediaStreamTrack`.
        """
        if track not in self.__tracks:
            self.__tracks[track] = None

    async def start(self):
        """
        Start discarding media.
        """
        for track, task in self.__tracks.items():
            if task is None:
                self.__tracks[track] = asyncio.ensure_future(blackhole_consume(track))

    async def stop(self):
        """
        Stop discarding media.
        """
        for task in self.__tracks.values():
            if task is not None:
                task.cancel()
        self.__tracks = {}


def place_frame_in_video_queue(frame, frame_index, loop, video_track, container):
    """ place the attached frame in the video track queue after stamping it 
    """
    frame_time = frame.time
    frame = stamp_frame(frame, frame_index, frame.pts, frame.time_base)
    
    logger.warning(
        "MediaPlayer(%s) Put video frame %s in the queue: %s",
        container.name, str(frame_index), str(frame)
    )
    asyncio.run_coroutine_threadsafe(video_track._queue.put((frame, frame_time, \
                                     frame_index, frame.pts)), loop)


def requires_updated_reference(keypoints, frame_index, original_frame, lr_frame_array=None,
        method="fixed_interval", reference_update_freq=30):
    """ detect if the system needs an updated reference using one of multiple methods 
    """
    source_frame_index = keypoints['source_index']

    if frame_index == 0:
        return True

    if method == "fixed_interval":
        if frame_index % reference_update_freq == 0:
            return True
    return False


class PlayerStreamTrack(MediaStreamTrack):
    def __init__(self, player, kind, fps_factor=1):
        super().__init__()
        self.kind = kind
        self._player = player
        self._queue = asyncio.Queue()
        self._start = None
        self._fps_factor = fps_factor
        self._lr_size = 512 # default lr_video resolution at the start

    async def recv(self):
        if self.readyState != "live":
            raise MediaStreamError

        self._player._start(self)
        frame, frame_time, frame_index, frame_pts = await self._queue.get()
        if frame is None:
            self.__log_debug("Received frame from queue is None %s", self.kind)
            self.stop()
            raise MediaStreamError

        # control playback rate
        if (
            self._player is not None
            and self._player._throttle_playback
            and frame_time is not None
        ):
            if self._start is None:
                self._start = time.time() - frame_time
            else:
                wait = self._start + frame_time - time.time()
                await asyncio.sleep(wait)

        # record send time just before sending it on wire
        if self._player._send_times_file is not None:
            if self._player._enable_prediction and (self.kind == "keypoints" or self.kind == "lr_video"):
                self._player._send_times_file.write(f'Sent {frame_index} at {datetime.datetime.now()}\n')
            elif self._player._enable_prediction and self.kind == "video":
                self._player._send_times_file.write(
                        f'Sent {frame_index} at {datetime.datetime.now()} (video) \n')
            elif self.kind == "video":
                self._player._send_times_file.write(f'Sent {frame_index} at {datetime.datetime.now()}\n')
            self._player._send_times_file.flush()
        
        # extract keypoints before sending
        if self.kind == "keypoints": 
            try:
                frame_array = frame 
                time_before_keypoints = time.perf_counter()
                loop = asyncio.get_running_loop()
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    keypoints, source_frame_index = await loop.run_in_executor(pool,
                                                            model_zoo['no_lr_video'].extract_keypoints, frame_array)
                time_after_keypoints = time.perf_counter()
                logger.warning(
                    "Keypoints extraction time for frame index %s in sender: %s",
                    str(frame_index), str(time_after_keypoints - time_before_keypoints)
                )
                keypoints_frame = KeypointsFrame(keypoints, frame_pts, frame_index, source_frame_index) 
                
                if frame_index % self._player._reference_update_freq == 0:
                    time_before_update = time.perf_counter()
                    model_zoo['no_lr_video'].update_source(frame_index, frame_array, keypoints)
                    time_after_update = time.perf_counter()
                    logger.warning(
                        "Time to update source frame with index %s in sender: %s",
                        str(frame_index), str(time_after_update - time_before_update)
                    )
            except:
                keypoints_frame = None
                logger.warning(
                    "MediaPlayer(%s) Could not extract the keypoints for frame index %s", str(frame_index)
                )

            if keypoints_frame is not None:
                return keypoints_frame
        else:
            return frame

    def stop(self):
        super().stop()
        self.__log_debug("Stopping %s", self.kind)
        if self._player is not None:
            self._player._stop(self)
            self._player = None

    def __log_debug(self, msg: str, *args) -> None:
        logger.debug(f"PlayerStreamTrack(%s) {msg}", self.__container.name, *args)


class MediaPlayer:
    """
    A media source that reads audio and/or video from a file.

    Examples:

    .. code-block:: python

        # Open a video file.
        player = MediaPlayer('/path/to/some.mp4')

        # Open an HTTP stream.
        player = MediaPlayer(
            'http://download.tsi.telecom-paristech.fr/'
            'gpac/dataset/dash/uhd/mux_sources/hevcds_720p30_2M.mp4')

        # Open webcam on Linux.
        player = MediaPlayer('/dev/video0', format='v4l2', options={
            'video_size': '640x480'
        })

        # Open webcam on OS X.
        player = MediaPlayer('default:none', format='avfoundation', options={
            'video_size': '640x480'
        })

        # Open webcam on Windows.
        player = MediaPlayer('video=Integrated Camera', format='dshow', options={
            'video_size': '640x480'
        })

    :param file: The path to a file, or a file-like object.
    :param format: The format to use, defaults to autodect.
    :param options: Additional options to pass to FFmpeg.
    """

    def __init__(self, file, enable_prediction=False, prediction_type="keypoints",
                reference_update_freq=30, fps=None, save_dir=None, format=None, options={}):
        self.__container = av.open(file=file, format=format, mode="r", options=options)
        self.__thread: Optional[threading.Thread] = None
        self.__thread_quit: Optional[threading.Event] = None
        self.__save_dir = save_dir
        self._enable_prediction = enable_prediction
        self._prediction_type = prediction_type
        self._reference_update_freq = reference_update_freq
        
        if self.__save_dir is not None:
            self._send_times_file = open(os.path.join(save_dir, "send_times.txt"), "w")
        else:
            self._send_times_file = None

        # examine streams
        self.__started: Set[PlayerStreamTrack] = set()
        self.__streams = []
        self.__audio: Optional[PlayerStreamTrack] = None
        self.__video: Optional[PlayerStreamTrack] = None
        self.__keypoints: Optional[PlayerStreamTrack] = None
        self.__lr_video: Optional[PlayerStreamTrack] = None

        for stream in self.__container.streams:
            if stream.type == "audio" and not self.__audio:
                self.__audio = PlayerStreamTrack(self, kind="audio")
                self.__streams.append(stream)
            elif stream.type == "video" and not self.__video:
                if fps is not None and fps < stream.base_rate:
                    fps_factor = round(float(stream.base_rate) / fps)
                else:
                    fps_factor = 1
                if generator_type not in ['bicubic', 'swinir-lte']:
                    self.__video = PlayerStreamTrack(self, kind="video", fps_factor=fps_factor)
                    self.__streams.append(stream)
                if self._enable_prediction:
                    if self._prediction_type == "keypoints":
                        self.__keypoints = PlayerStreamTrack(self, kind="keypoints")
                    else:
                        self.__lr_video = PlayerStreamTrack(self, kind="lr_video", fps_factor=fps_factor)

        # check whether we need to throttle playback
        container_format = set(self.__container.format.name.split(","))
        self._throttle_playback = not container_format.intersection(REAL_TIME_FORMATS)

    @property
    def audio(self) -> MediaStreamTrack:
        """
        A :class:`aiortc.MediaStreamTrack` instance if the file contains audio.
        """
        return self.__audio

    @property
    def video(self) -> MediaStreamTrack:
        """
        A :class:`aiortc.MediaStreamTrack` instance if the file contains video.
        """
        return self.__video

    @property
    def keypoints(self) -> MediaStreamTrack:
        """
        A :class:`aiortc.MediaStreamTrack` instance if the file contains keypoints.
        """
        return self.__keypoints

    @property
    def lr_video(self) -> MediaStreamTrack:
        """
        A :class:`aiortc.MediaStreamTrack` instance if the file contains video.
        """
        return self.__lr_video

    def player_worker(
        self, loop, container, streams, audio_track, video_track, keypoints_track, lr_video_track,
        quit_event, throttle_playback, save_dir, enable_prediction, prediction_type,
        reference_update_freq):
        audio_fifo = av.AudioFifo()
        audio_format_name = "s16"
        audio_layout_name = "stereo"
        audio_sample_rate = 48000
        audio_samples = 0
        audio_samples_per_frame = int(audio_sample_rate * AUDIO_PTIME)
        audio_resampler = av.AudioResampler(
            format=audio_format_name, layout=audio_layout_name, rate=audio_sample_rate
        )

        video_first_pts = None

        frame_time = None
        display_option = 'synthetic'
        start_time = time.time()
        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

        while not quit_event.is_set():
            try:
                frame = next(container.decode(*streams))
                if isinstance(frame, VideoFrame) and video_track:
                    logger.debug(f"MediaPlayerWorker Frame size:%d Index:%d Factor:%d",
                            sys.getsizeof(frame),
                            frame.index, video_track._fps_factor)
                    if frame.index % video_track._fps_factor != 0:
                        continue

            except (av.AVError, StopIteration) as exc:
                if isinstance(exc, av.FFmpegError) and exc.errno == errno.EAGAIN:
                    time.sleep(0.01)
                    continue
                if audio_track:
                    logger.warning(
                        "MediaPlayer(%s) Put None in audio in player_worker",
                        container.name
                    )
                    asyncio.run_coroutine_threadsafe(audio_track._queue.put((None, None)), loop)
                if video_track:
                    logger.warning(
                        "MediaPlayer(%s) Put None in video and keypoints in player_worker",
                        container.name
                    )
                    asyncio.run_coroutine_threadsafe(video_track._queue.put((None, None)), loop)
                    if enable_prediction:
                        if prediction_type == 'keypoints':
                            asyncio.run_coroutine_threadsafe(keypoints_track._queue.put((None, None)), loop)
                        else:
                            asyncio.run_coroutine_threadsafe(lr_video_track._queue.put((None, None)), loop)
                break

            # read up to 1 second ahead
            if throttle_playback:
                elapsed_time = time.time() - start_time
                if frame_time and frame_time > elapsed_time + 1:
                    time.sleep(0.1)

            if isinstance(frame, AudioFrame) and audio_track:
                if (
                    frame.format.name != audio_format_name
                    or frame.layout.name != audio_layout_name
                    or frame.sample_rate != audio_sample_rate
                ):
                    frame.pts = None
                    frame = audio_resampler.resample(frame)

                # fix timestamps
                frame.pts = audio_samples
                frame.time_base = fractions.Fraction(1, audio_sample_rate)
                audio_samples += frame.samples

                audio_fifo.write(frame)
                while True:
                    frame = audio_fifo.read(audio_samples_per_frame)
                    if frame:
                        frame_time = frame.time
                        asyncio.run_coroutine_threadsafe(
                            audio_track._queue.put((frame, frame_time, frame.index, frame.pts)), loop
                        )
                    else:
                        break
            elif isinstance(frame, VideoFrame):
                if frame.pts is None:  # pragma: no cover
                    logger.warning(
                        "MediaPlayer(%s) Skipping video frame with no pts",
                        container.name
                    )
                    continue

                # video from a webcam doesn't start at pts 0, cancel out offset
                if video_first_pts is None:
                    video_first_pts = frame.pts
                frame.pts -= video_first_pts

                logger.warning(
                    "MediaPlayer(%s) Video frame %s read from media: %s at time %s",
                    container.name, str(frame.index), str(frame), time.perf_counter()
                )

                frame_array = frame.to_rgb().to_ndarray()

                if save_sent_frames and save_dir is not None:
                    np.save(os.path.join(save_dir, 'sender_frame_%05d.npy' % frame.index),
                            frame_array)

                if enable_prediction:
                    logger.warning(
                        "MediaPlayer(%s) Put frame %s in keypoints queue: %s",
                         container.name, str(frame.index), str(frame)
                    )

                    if prediction_type != "keypoints":
                        logger.warning("MediaPlayer(%s) frame size %s", container.name,
                                lr_video_track._lr_size)
                        frame_tensor = frame_to_tensor(img_as_float32(frame_array), device)
                        if generator_type != 'swinir-lte':
                            lr_frame_array = resize_tensor_to_array(frame_tensor,
                                                lr_video_track._lr_size , device)
                        else:
                            lr_frame_array = resize_tensor_to_array(frame_tensor, lr_shape , device)

                        lr_frame = av.VideoFrame.from_ndarray(lr_frame_array)
                        lr_frame.pts = frame.pts
                        lr_frame.time_base = frame.time_base
                        """
                        We can not re-write the index of an av.VideoFrame and it defaults to 0.
                        We should use frame.index as lr_frame.index.
                        """

                        place_frame_in_video_queue(lr_frame, frame.index, loop, lr_video_track, container)
                        if save_lr_video_npy and save_dir is not None:
                            np.save(os.path.join(save_dir,
                                    'sender_lr_frame_%05d.npy' % frame.index),
                                    lr_frame_array)

                    else:
                        asyncio.run_coroutine_threadsafe(keypoints_track._queue.put((frame_array, frame.time, \
                                frame.index, frame.pts)), loop)

                # Only add video frame is this is meant to be used as a source \
                # frame or if prediction is disabled
                if video_track is not None:
                    if (enable_prediction and frame.index % reference_update_freq == 0) or \
                            display_option == 'real' or not enable_prediction:
                        place_frame_in_video_queue(frame, frame.index, loop, video_track, container)

    def _start(self, track: PlayerStreamTrack) -> None:
        self.__started.add(track)
        if self.__thread is None:
            self.__log_debug("Starting worker thread")
            self.__thread_quit = threading.Event()
            self.__thread = threading.Thread(
                name="media-player",
                target=self.player_worker,
                args=(
                    asyncio.get_event_loop(),
                    self.__container,
                    self.__streams,
                    self.__audio,
                    self.__video,
                    self.__keypoints,
                    self.__lr_video,
                    self.__thread_quit,
                    self._throttle_playback,
                    self.__save_dir,
                    self._enable_prediction,
                    self._prediction_type,
                    self._reference_update_freq,
                ),
            )
            self.__thread.start()

    def _stop(self, track: PlayerStreamTrack) -> None:
        self.__log_debug("Stopping %s", track.kind)
        self.__started.discard(track)

        if not self.__started and self.__thread is not None:
            self.__log_debug("Stopping worker thread")
            self.__thread_quit.set()
            self.__thread.join()
            self.__thread = None

        if not self.__started and self.__container is not None:
            self.__container.close()
            self.__container = None

        if self.__send_times_file is not None:
            self.__send_times_file.close()

    def __log_debug(self, msg: str, *args) -> None:
        logger.debug(f"MediaPlayer(%s) {msg}", self.__container.name, *args)


class MediaRecorderContext:
    def __init__(self, stream):
        self.stream = stream
        self.task = None


class MediaRecorder:
    """
    A media sink that writes audio and/or video to a file.

    Examples:

    .. code-block:: python

        # Write to a video file.
        player = MediaRecorder('/path/to/file.mp4')

        # Write to a set of images.
        player = MediaRecorder('/path/to/file-%3d.png')

    :param file: The path to a file, or a file-like object.
    :param format: The format to use, defaults to autodect.
    :param options: Additional options to pass to FFmpeg.
    """

    def __init__(self, file, enable_prediction=False, prediction_type="keypoints",
                reference_update_freq=30, output_fps=30, format=None, save_dir=None, options={}):
        self.__container = av.open(file=file, format=format, mode="w", options=options)
        self.__received_keypoints_frame_num = 0
        self.__keypoints_file_name = str(file).split('.')[0] + "_recorded_keypoints.txt"
        self.__tracks = {}
        self.__frame_height = None
        self.__frame_width = None
        self.__keypoints_queue = asyncio.Queue()
        self.__reference_frames_queue = asyncio.Queue()
        self.__real_video_queue = asyncio.Queue()
        self.__synthetic_video_queue = asyncio.Queue()
        self.__lr_video_queue = asyncio.Queue()
        self.__display_queue = asyncio.Queue()
        self.__save_dir = save_dir
        self.__enable_prediction = enable_prediction
        self.__prediction_type = prediction_type
        self.__reference_update_freq = reference_update_freq
        self.__output_fps = output_fps
        self.__display_option = "synthetic"
        '''
        __display_option could be:
            1. "real": original target-res video
            2. "synthetic": predicted target using keypoint or low-res video
        '''
        
        if self.__save_dir is not None:
            self.__recv_times_file = open(os.path.join(save_dir, "recv_times.txt"), "w")
        else:
            self.__recv_times_file = None

    def addTrack(self, track):
        """
        Add a track to be recorded.

        :param track: A :class:`aiortc.MediaStreamTrack`.
        """
        if track.kind == "audio":
            if self.__container.format.name in ("wav", "alsa"):
                codec_name = "pcm_s16le"
            elif self.__container.format.name == "mp3":
                codec_name = "mp3"
            else:
                codec_name = "aac"
            stream = self.__container.add_stream(codec_name)
        elif ((track.kind == "keypoints" or track.kind == "lr_video") and \
                self.__enable_prediction == True) or \
                (track.kind == "video" and self.__enable_prediction == False):
            # repurpose video container stream for predicted video w/ keypoints or lr_video
            if self.__container.format.name == "image2":
                stream = self.__container.add_stream("png", rate=self.__output_fps)
                stream.pix_fmt = "rgb24"
            else:
                stream = self.__container.add_stream("libx264", rate=self.__output_fps)
                stream.pix_fmt = "yuv420p"
            
            stream.height = frame_shape[0]
            stream.width = frame_shape[1]
        else:
            stream = None
        self.__tracks[track] = MediaRecorderContext(stream)

    async def start(self):
        """
        Start recording.
        """
        for track, context in self.__tracks.items():
            if context.task is None:
                context.task = asyncio.ensure_future(self.__run_track(track, context))

    async def stop(self):
        """
        Stop recording.
        """
        if self.__container:
            for track, context in self.__tracks.items():
                if context.stream is not None:
                    if context.task is not None:
                        context.task.cancel()
                        context.task = None
                        for packet in context.stream.encode(None):
                            self.__container.mux(packet)
            self.__tracks = {}

            if self.__container:
                self.__container.close()
                self.__container = None

        if self.__recv_times_file is not None:
            self.__recv_times_file.close()

    async def __run_track(self, track, context):
        loop = asyncio.get_running_loop()
        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        while True:
            try:
                frame = await track.recv()
            except MediaStreamError:
                logger.warning("Couldn't receive the %s track.", track.kind)
                return

            if track.kind == "video":
                frame, video_frame_index = destamp_frame(frame)
                self.__frame_height = frame.height
                self.__frame_width = frame.width

                self.__log_debug("Received original video frame %s with index %s at time %s",
                                    frame, video_frame_index, datetime.datetime.now())
                if self.__enable_prediction:
                    if self.__display_option == 'synthetic' and \
                            generator_type not in ['bicubic', 'swinir-lte']:
                        # update model related info with most recent source frame
                        source_frame_array = frame.to_rgb().to_ndarray()

                        time_before_keypoints = time.perf_counter()
                        with concurrent.futures.ThreadPoolExecutor() as pool:
                            source_keypoints_zoo = {}
                            for lr_size in low_res_sizes:
                                """ extract the source keypoints for all models with different lr_size
                                    for keypoint-based model the low_res_sizes = ['no_lr_video']
                                """
                                source_keypoints, _  = await loop.run_in_executor(pool,
                                        model_zoo[lr_size].extract_keypoints, source_frame_array)
                                source_keypoints_zoo[lr_size] = source_keypoints

                        time_after_keypoints = time.perf_counter()
                        self.__log_debug("Source keypoints extraction time in receiver: %s",
                                        str(time_after_keypoints - time_before_keypoints))

                        asyncio.run_coroutine_threadsafe(self.__reference_frames_queue.put(
                            (source_frame_array, source_keypoints_zoo, video_frame_index)), loop)
                    
                    elif self.__display_option == "real":
                        # directly display the received real video frames
                        asyncio.run_coroutine_threadsafe(self.__real_video_queue.put(
                                                        (frame, video_frame_index))
                                                        , loop)
                else:
                    # Original aiortc video stream, no prediction
                    if self.__recv_times_file is not None:
                        self.__recv_times_file.write(f'Received {video_frame_index} at {datetime.datetime.now()}\n')
                        self.__recv_times_file.flush()

                    if save_received_frames and self.__save_dir is not None:
                        frame_array = frame.to_rgb().to_ndarray()
                        np.save(os.path.join(self.__save_dir,
                            'receiver_frame_%05d.npy' % video_frame_index), frame_array)

                    self.__log_debug("Frame displayed at receiver %s", video_frame_index)
                    for packet in context.stream.encode(frame):
                        self.__container.mux(packet)
                    if video_frame_index % 1000 == 0:
                        print("Displayed ", video_frame_index)

            elif track.kind == "audio":
                for packet in context.stream.encode(frame):
                    self.__container.mux(packet)

            elif track.kind == "keypoints" or track.kind == "lr_video":
                if track.kind == "keypoints":
                    # keypoint stream
                    received_keypoints = frame.data
                    asyncio.run_coroutine_threadsafe(self.__keypoints_queue.put(received_keypoints), loop)
                    frame_index = received_keypoints['frame_index']

                    if save_keypoints_to_file:
                        keypoints_file = open(self.__keypoints_file_name, "a")
                        keypoints_file.write(str(received_keypoints))
                        keypoints_file.write("\n")
                        keypoints_file.close()

                elif track.kind == "lr_video":
                    lr_frame, frame_index = destamp_frame(frame)
                    lr_frame_array = lr_frame.to_rgb().to_ndarray()
                    asyncio.run_coroutine_threadsafe(self.__lr_video_queue.put((lr_frame_array, frame_index)), loop)
                    if save_lr_video_npy and self.__save_dir is not None:
                        np.save(os.path.join(self.__save_dir,
                                'receiver_lr_frame_%05d.npy' % frame_index),
                                lr_frame_array)
 
                self.__log_debug("%s for frame %s received at time %s",
                                track.kind, str(frame_index), datetime.datetime.now())

                if self.__enable_prediction:
                    try:
                        if track.kind == "keypoints":
                            received_keypoints = await self.__keypoints_queue.get()
                            frame_index = received_keypoints['frame_index']
                        elif track.kind == "lr_video":
                            lr_frame_array, frame_index = await self.__lr_video_queue.get()
                        if self.__display_option == "synthetic":
                            if frame_index % self.__reference_update_freq == 0 and \
                                    generator_type not in ['bicubic', 'swinir-lte']:
                                source_frame_array, source_keypoints_zoo, source_frame_index = await self.__reference_frames_queue.get()
                                time_before_update = time.perf_counter()
                                for lr_size in low_res_sizes:
                                    model_zoo[lr_size].update_source(source_frame_index,
                                            source_frame_array, source_keypoints_zoo[lr_size])

                                time_after_update = time.perf_counter()
                                self.__log_debug("Time to update source frame %s in all receiver models " \
                                        " when receiving %s %s: %s",
                                        source_frame_index, track.kind, frame_index, \
                                        str(time_after_update - time_before_update))
                                if save_sent_frames and self.__save_dir is not None:
                                    np.save(os.path.join(self.__save_dir,
                                        'reference_frame_%05d.npy' % source_frame_index), source_frame_array)

                            with concurrent.futures.ThreadPoolExecutor() as pool:
                                if generator_type not in ['bicubic', 'swinir-lte']:
                                    self.__log_debug("Calling predict for frame %s with source frame %s",
                                                frame_index, source_frame_index)
                                before_predict_time = time.perf_counter()
                                if track.kind == "keypoints":
                                    predicted_target = await loop.run_in_executor(pool, \
                                            model_zoo['no_lr_video'].predict, received_keypoints)
                                elif track.kind == "lr_video":
                                    if generator_type == "bicubic":
                                        predicted_target = lr_frame.reformat(width=frame_shape[0], height=frame_shape[0],\
                                                            interpolation='BICUBIC').to_rgb().to_ndarray()

                                    elif generator_type == 'swinir-lte':
                                        predicted_target = await loop.run_in_executor(pool, \
                                                model.predict_with_lr_video, lr_frame_array)

                                    else:
                                        lr_size = lr_frame_array.shape[1]
                                        self.__log_debug("Using the model with resolution %s from the zoo", lr_size)
                                        predicted_target = await loop.run_in_executor(pool, \
                                                model_zoo[lr_size].predict_with_lr_video, lr_frame_array)

                            after_predict_time = time.perf_counter()
                            self.__log_debug("Prediction time for received %s %s: %s at time %s",
                                    track.kind, frame_index, str(after_predict_time - before_predict_time),
                                    after_predict_time)

                            if self.__recv_times_file is not None:
                                self.__recv_times_file.write(f'Received {frame_index} at {datetime.datetime.now()}\n')
                                self.__recv_times_file.flush()

                            predicted_frame = av.VideoFrame.from_ndarray(np.array(predicted_target))
                            predicted_frame = predicted_frame.reformat(format='yuv420p')
                            asyncio.run_coroutine_threadsafe(self.__synthetic_video_queue.put(
                                                            (predicted_frame, frame_index)),
                                                            loop)
                            #predicted_frame.pts = received_keypoints['pts']
                            if frame_index % 1000 == 0:
                                print("Predicted!", frame_index)

                            if save_predicted_frames and self.__save_dir is not None:
                                predicted_array = np.array(predicted_target)
                                np.save(os.path.join(self.__save_dir,
                                    'predicted_frame_%05d.npy' % frame_index), predicted_array)
                    except Exception as e:
                        print(e)
                        self.__log_debug("Couldn't predict based on received %s frame %s with error %s",
                                    track.kind, frame_index, e)

                #read from the proper real/syn queue, write in display queue
                if self.__display_option == "real":
                    display_frame, frame_index = await self.__real_video_queue.get()
                else:
                    display_frame, frame_index = await self.__synthetic_video_queue.get()

                asyncio.run_coroutine_threadsafe(self.__display_queue.put(
                                                (display_frame, frame_index)),
                                                loop)
                #read from the display queue, and write in the file
                display_frame, frame_index = await self.__display_queue.get()
                self.__log_debug("Frame displayed at receiver %s", frame_index)
                for packet in context.stream.encode(display_frame):
                    self.__container.mux(packet)

                if self.__save_dir is not None and save_received_frames:
                    display_array = display_frame.to_rgb().to_ndarray()
                    np.save(os.path.join(self.__save_dir,
                            'receiver_frame_%05d.npy' % frame_index), display_array)

    def __log_debug(self, msg: str, *args) -> None:
        logger.debug(f"MediaRecorder(%s) {msg}", self.__container.name, *args)


class RelayStreamTrack(MediaStreamTrack):
    def __init__(self, relay, source: MediaStreamTrack) -> None:
        super().__init__()
        self.kind = source.kind
        self._relay = relay
        self._queue: asyncio.Queue[Optional[Frame]] = asyncio.Queue()
        self._source: Optional[MediaStreamTrack] = source

    async def recv(self):
        if self.readyState != "live":
            raise MediaStreamError

        self._relay._start(self)
        frame = await self._queue.get()
        if frame is None:
            self.stop()
            raise MediaStreamError
        return frame

    def stop(self):
        super().stop()
        if self._relay is not None:
            self._relay._stop(self)
            self._relay = None
            self._source = None


class MediaRelay:
    """
    A media source that relays one or more tracks to multiple consumers.

    This is especially useful for live tracks such as webcams or media received
    over the network.
    """

    def __init__(self) -> None:
        self.__proxies: Dict[MediaStreamTrack, Set[RelayStreamTrack]] = {}
        self.__tasks: Dict[MediaStreamTrack, asyncio.Future[None]] = {}

    def subscribe(self, track: MediaStreamTrack) -> MediaStreamTrack:
        """
        Create a proxy around the given `track` for a new consumer.
        """
        proxy = RelayStreamTrack(self, track)
        self.__log_debug("Create proxy %s for source %s", id(proxy), id(track))
        if track not in self.__proxies:
            self.__proxies[track] = set()
        return proxy

    def _start(self, proxy: RelayStreamTrack) -> None:
        track = proxy._source
        if track is not None and track in self.__proxies:
            # register proxy
            if proxy not in self.__proxies[track]:
                self.__log_debug("Start proxy %s", id(proxy))
                self.__proxies[track].add(proxy)

            # start worker
            if track not in self.__tasks:
                self.__tasks[track] = asyncio.ensure_future(self.__run_track(track))

    def _stop(self, proxy: RelayStreamTrack) -> None:
        track = proxy._source
        if track is not None and track in self.__proxies:
            # unregister proxy
            self.__log_debug("Stop proxy %s", id(proxy))
            self.__proxies[track].discard(proxy)

    def __log_debug(self, msg: str, *args) -> None:
        logger.debug(f"MediaRelay(%s) {msg}", id(self), *args)

    async def __run_track(self, track: MediaStreamTrack) -> None:
        self.__log_debug("Start reading source %s" % id(track))

        while True:
            try:
                frame = await track.recv()
            except MediaStreamError:
                frame = None
            for proxy in self.__proxies[track]:
                proxy._queue.put_nowait(frame)
            if frame is None:
                break

        self.__log_debug("Stop reading source %s", id(track))
        del self.__proxies[track]
        del self.__tasks[track]
