"""Bounded deterministic ingestion. Temporal sampling is a milestone-1 baseline, not quality selection."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import shutil
import struct
import time
from fractions import Fraction

MAX_BYTES = 256 * 1024 * 1024
EXTRACTOR_ID = 'ffmpeg-temporal-v1'


class VideoError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def sha256(path):
    checksum = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            checksum.update(chunk)
    return checksum.hexdigest()


def validate_container(path: Path, expected_sha256=None):
    if path.is_symlink() or not path.is_file() or not 12 <= path.stat().st_size <= MAX_BYTES:
        raise VideoError('VIDEO_INVALID', 'Video must be a regular file of 12 bytes–256 MiB')
    # Reject incomplete ISO-BMFF top-level boxes, even when a decoder tolerates truncation.
    size = path.stat().st_size
    kinds, offset = [], 0
    with path.open('rb') as stream:
        while offset < size:
            stream.seek(offset)
            header = stream.read(8)
            if len(header) != 8:
                raise VideoError('VIDEO_INVALID', 'Truncated container box')
            length, kind = struct.unpack('>I4s', header)
            header_size = 8
            if length == 1:
                extended = stream.read(8)
                if len(extended) != 8:
                    raise VideoError('VIDEO_INVALID', 'Truncated extended box')
                length, header_size = struct.unpack('>Q', extended)[0], 16
            elif length == 0:
                length = size-offset
            if length < header_size or offset+length > size:
                raise VideoError('VIDEO_INVALID', 'Incomplete container box')
            kinds.append(kind)
            offset += length
    if not kinds or kinds[0] != b'ftyp' or b'moov' not in kinds or b'mdat' not in kinds:
        raise VideoError('VIDEO_INVALID', 'Expected self-contained MP4/MOV container with movie and media data')
    digest = sha256(path)
    if expected_sha256 is not None and digest != expected_sha256:
        raise VideoError('INPUT_CHECKSUM_MISMATCH', 'Raw video SHA-256 differs from capture')
    return {'sha256': digest, 'bytes': size}


def validate_probe(document):
    streams = [s for s in document.get('streams', []) if s.get('codec_type') == 'video']
    if len(streams) != 1 or streams[0].get('disposition', {}).get('attached_pic'):
        raise VideoError('VIDEO_INVALID', 'Exactly one video stream is required')
    stream = streams[0]
    if stream.get('codec_name') not in ('h264', 'hevc'):
        raise VideoError('VIDEO_UNSUPPORTED_CODEC', 'Only H.264 and HEVC are enabled for this pilot')
    if not {'mov', 'mp4'} & set(document.get('format', {}).get('format_name', '').split(',')):
        raise VideoError('VIDEO_INVALID', 'Unsupported container')
    try:
        width, height = int(stream['width']), int(stream['height'])
        duration = float(stream.get('duration', document['format'].get('duration', 'nan')))
        rate = float(Fraction(stream['avg_frame_rate']))
        if not (0 < width <= 4096 and 0 < height <= 4096 and width*height <= 9_000_000 and 0 < duration <= 120 and 0 < rate <= 120):
            raise ValueError('outside limits')
        # Preserve real presentation timestamps, including variable frame rate.
        timestamps = [float(f['best_effort_timestamp_time'])*1000 for f in document['frames']]
        if not 3 <= len(timestamps) <= 14400 or any(not math.isfinite(t) for t in timestamps):
            raise ValueError('invalid frame count or timestamps')
        if any(b <= a for a,b in zip(timestamps,timestamps[1:])):
            raise ValueError('non-increasing presentation timestamps')
        if any(int(f.get('width',width)) != width or int(f.get('height',height)) != height for f in document['frames']):
            raise ValueError('resolution changes within capture')
        timestamps = [round(t-timestamps[0], 6) for t in timestamps]
        if timestamps[-1] > 120000:
            raise ValueError('timeline exceeds budget')
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as error:
        raise VideoError('VIDEO_INVALID', f'Invalid video metadata: {error}') from error
    return {'width':width,'height':height,'durationSeconds':duration,'frameRate':rate,
            'codec':stream['codec_name'],'timestampsMs':timestamps,
            'orientation':stream.get('side_data_list', []),'tags':stream.get('tags', {}),
            'intrinsics':None,'intrinsicsStatus':'UNAVAILABLE',
            'color':{k:stream.get(k) for k in ('color_space','color_transfer','color_primaries','color_range')},
            'sampleAspectRatio':stream.get('sample_aspect_ratio')}


def temporal_indices(timestamps, budget):
    if not 3 <= budget <= 40:
        raise VideoError('VIDEO_INVALID', 'Legacy image budget must be 3–40')
    count = min(len(timestamps), budget)
    # Distinct presentation-order quantiles. This is intentionally NOT smart selection.
    return [(i*(len(timestamps)-1))//(count-1) for i in range(count)]


def extract_video(source, output, settings, execute, expected_sha256=None, *, candidate_budget=None, extra_indices_count=None):
    from PIL import Image
    identity = validate_container(source, expected_sha256)
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise VideoError('VIDEO_TOOLS_UNAVAILABLE', 'Install FFmpeg/ffprobe on the video worker')
    started = time.monotonic()
    input_dir, selected = output/'input', output/'frames'/('candidates' if candidate_budget else 'selected')
    input_dir.mkdir(exist_ok=True)
    selected.mkdir(parents=True)
    original = input_dir/'source.video'
    shutil.copyfile(source, original)
    if sha256(original) != identity['sha256']:
        raise VideoError('INPUT_CHECKSUM_MISMATCH', 'Video changed while preserving original')
    for tool in ('ffmpeg','ffprobe'):
        execute({'name':f'version-{tool}', 'command':[tool,'-version']},output,settings)
    tools = {tool:{'binarySha256':sha256(Path(shutil.which(tool))),
                   'version':(output/f'version-{tool}.log').read_text().splitlines()[0]} for tool in ('ffmpeg','ffprobe')}
    probe = input_dir/'ffprobe.json'
    try:
        # Inspect dimensions/duration/codec BEFORE decoding the full timeline.
        execute({'name':'video_header','stdout_file':'input/video_header.json','command':[
            'ffprobe','-v','error','-threads','1','-protocol_whitelist','file',
            '-show_streams','-show_format','-of','json',str(original)]},output,settings)
        header_path = input_dir/'video_header.json'
        if header_path.stat().st_size > 1024*1024:
            raise VideoError('VIDEO_INVALID','Header metadata exceeds budget')
        header = json.loads(header_path.read_text())
        # Common validation also checks the timeline; the real timeline is checked below.
        validate_probe({**header,'frames':[{'best_effort_timestamp_time':str(i/1000)} for i in range(3)]})
        execute({'name':'video_probe','stdout_file':'input/ffprobe.json','command':['ffprobe','-v','error','-threads','1',
                 '-protocol_whitelist','file','-select_streams','v','-show_streams','-show_format',
                 '-show_frames','-show_entries','frame=best_effort_timestamp_time,width,height:stream:format',
                 '-of','json',str(original)]},output,settings)
        if probe.stat().st_size > 8*1024*1024:
            raise VideoError('VIDEO_INVALID','Video metadata exceeds budget')
        metadata = validate_probe(json.loads(probe.read_text()))
    except VideoError:
        raise
    except (ValueError, OSError) as error:
        raise VideoError('VIDEO_INVALID', str(error)) from error
    probe_seconds = time.monotonic()-started
    if candidate_budget is None:
        indexes = temporal_indices(metadata['timestampsMs'],settings['max_images'])
    else:
        if not 3 <= candidate_budget <= 200 or not 3 <= (extra_indices_count or 3) <= 80:
            raise VideoError('VIDEO_INVALID', 'Candidate/frame budget exceeded')
        # No extra dependency for the milestone-1 path.
        count = len(metadata['timestampsMs'])
        def sample(budget):
            n = min(count, budget)
            return [i*(count-1)//(n-1) for i in range(n)]
        indexes = sorted(set(sample(candidate_budget)+sample(extra_indices_count or 3)))
    expression = '+'.join(f'eq(n\\,{index})' for index in indexes)
    edge = settings['long_edge']
    filters = f"select={expression},scale=w='min({edge},iw)':h='min({edge},ih)':force_original_aspect_ratio=decrease"
    decode_started = time.monotonic()
    try:
        # Decode the ENTIRE video, including frames after the last selected one.
        # xerror/err_detect explode prevent success on tolerant partial decodes.
        execute({'name':'video_decode','command':['ffmpeg','-nostdin','-v','error','-xerror',
                 '-err_detect','explode','-threads','1','-protocol_whitelist','file','-i',str(original),
                 '-map','0:v:0','-an','-sn','-dn','-filter_threads','1','-vf',filters,
                 '-vsync','0','-threads','1','-bitexact','-start_number','0',str(selected/'%06d.png')]},output,settings)
    except (ValueError, OSError) as error:
        raise VideoError('VIDEO_DECODE_FAILED',str(error)) from error
    paths = sorted(selected.glob('*.png'))
    if len(paths) != len(indexes):
        raise VideoError('VIDEO_DECODE_FAILED','Decoded frame count differs from selected presentation indexes')
    frames = []
    for path,index in zip(paths,indexes):
        with Image.open(path) as image:
            image.verify()
            width,height = image.size
        frames.append({'name':path.name,'frameIndex':index,'timestampMs':metadata['timestampsMs'][index],
                       'sha256':sha256(path),'bytes':path.stat().st_size,'width':width,'height':height,
                       'sourceVideoSha256':identity['sha256'],'orientationApplied':True})
    manifest = {'schema':2,'sourceType':'video','extractor':EXTRACTOR_ID,'tools':tools,
                'sourceVideo':identity,'frames':frames}
    if candidate_budget is not None:
        manifest.update(extractor='ffmpeg-candidates-v1', sourceFrameCount=len(metadata['timestampsMs']),
                        durationMs=metadata['durationSeconds']*1000,
                        timings={'probeAndTimelineDecode':probe_seconds, 'decodeAndCandidateExtraction':time.monotonic()-decode_started,
                                 'note':'FFmpeg decode and PNG extraction are fused; not independently measurable.'})
    (input_dir/'video_metadata.json').write_text(json.dumps(metadata,indent=2))
    (input_dir/'frames_manifest.json').write_text(json.dumps(manifest,indent=2))
    return selected,frames,manifest
