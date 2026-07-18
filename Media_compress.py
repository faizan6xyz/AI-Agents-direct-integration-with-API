import os
import shutil
import logging
import subprocess
from PIL import Image, UnidentifiedImageError
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("media_compress")
FFMPEG_BIN = shutil.which("ffmpeg")
FFPROBE_BIN = shutil.which("ffprobe")
MAX_IMAGE_DIMENSION_DEFAULT = 1920
IMAGE_QUALITY_MIN = 30
IMAGE_QUALITY_START = 85
IMAGE_QUALITY_STEP = 10
AUDIO_BITRATES = ["128k", "96k", "64k", "48k", "32k"]
VIDEO_CRF_MIN, VIDEO_CRF_MAX = 18, 35
PLATFORM_LIMITS = {"gmail":             {"image": 25, "audio": 25, "video": 25},
    "whatsapp":          {"image": 5,  "audio": 16, "video": 16},
    "whatsapp_document": {"image": 100, "audio": 100, "video": 100},}

def _require_ffmpeg():
    if not FFMPEG_BIN:
        raise EnvironmentError("ffmpeg not found on PATH. Install it to compress audio/video.")

def _resolve_paths(input_path, output_path, suffix):
    resolved_in = os.path.realpath(input_path)
    if not os.path.isfile(resolved_in):
        raise FileNotFoundError(f"Input file not found: {input_path}")
    if os.path.islink(input_path):
        raise ValueError(f"Input file '{input_path}' is a symlink, which is not allowed.")
    if output_path is None:
        base, ext = os.path.splitext(resolved_in)
        output_path = f"{base}{suffix}{ext}"
    resolved_out = os.path.realpath(output_path)
    os.makedirs(os.path.dirname(resolved_out) or ".", exist_ok=True)
    return resolved_in, resolved_out

def _run_ffmpeg(args):
    result = subprocess.run([FFMPEG_BIN, "-y", "-hide_banner", "-loglevel", "error", *args],
        capture_output=True, text=True, timeout=1800,)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr.strip()[:500]}")

def _probe_duration(path):
    if not FFPROBE_BIN:
        return None
    try:
        result = subprocess.run([FFPROBE_BIN, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=60,)
        return float(result.stdout.strip())
    except (ValueError, subprocess.TimeoutExpired):
        return None

def _warn_if_over_target(input_path, final_size, target_bytes):
    if target_bytes and final_size > target_bytes:
        logger.warning(f"Could not reach target size for '{input_path}': "
            f"{final_size / (1024*1024):.1f} MB vs target {target_bytes / (1024*1024):.1f} MB")
            
def _report_sizes(input_path, resolved_in, resolved_out):
    original_size = os.path.getsize(resolved_in)
    compressed_size = os.path.getsize(resolved_out)
    saved = original_size - compressed_size
    percent = (saved / original_size * 100) if original_size else 0
    print(f"'{input_path}' -> '{resolved_out}'")
    print(f"Original size: {original_size / 1024:.1f} KB")
    print(f"Compressed size: {compressed_size / 1024:.1f} KB")
    print(f"Saved: {saved / 1024:.1f} KB ({percent:.1f}%)")
    return compressed_size

def compress_image(input_path, output_path=None, target_bytes=None, max_dimension=MAX_IMAGE_DIMENSION_DEFAULT):
    resolved_in, resolved_out = _resolve_paths(input_path, output_path, "_compressed")
    try:
        img = Image.open(resolved_in)
        img.load()
    except UnidentifiedImageError:
        raise ValueError(f"'{input_path}' is not a valid image file.")
    is_jpeg = resolved_out.lower().endswith((".jpg", ".jpeg"))
    if is_jpeg and img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    width, height = img.size
    if max(width, height) > max_dimension:
        ratio = max_dimension / max(width, height)
        img = img.resize((max(1, int(width * ratio)), max(1, int(height * ratio))), Image.LANCZOS)
    quality = IMAGE_QUALITY_START
    img.save(resolved_out, quality=quality, optimize=True) if is_jpeg else img.save(resolved_out, optimize=True)
    while target_bytes and os.path.getsize(resolved_out) > target_bytes:
        if is_jpeg and quality > IMAGE_QUALITY_MIN:
            quality -= IMAGE_QUALITY_STEP
            img.save(resolved_out, quality=quality, optimize=True)
        elif not is_jpeg:
            width, height = img.size
            img = img.resize((max(1, int(width * 0.85)), max(1, int(height * 0.85))), Image.LANCZOS)
            img.save(resolved_out, optimize=True)
        else:
            break  # JPEG already at minimum quality
    final_size = os.path.getsize(resolved_out)
    _warn_if_over_target(input_path, final_size, target_bytes)
    _report_sizes(input_path, resolved_in, resolved_out)
    return resolved_out

def compress_audio(input_path, output_path=None, target_bytes=None, bitrate="64k"):
    _require_ffmpeg()
    resolved_in, resolved_out = _resolve_paths(input_path, output_path, "_compressed")
    if not resolved_out.lower().endswith((".mp3", ".m4a", ".aac", ".ogg")):
        resolved_out = os.path.splitext(resolved_out)[0] + ".mp3"
    bitrates_to_try = AUDIO_BITRATES if target_bytes else [bitrate]
    for br in bitrates_to_try:
        _run_ffmpeg(["-i", resolved_in, "-vn", "-b:a", br, "-ac", "1", resolved_out])
        if not target_bytes or os.path.getsize(resolved_out) <= target_bytes:
            break
    final_size = os.path.getsize(resolved_out)
    _warn_if_over_target(input_path, final_size, target_bytes)
    _report_sizes(input_path, resolved_in, resolved_out)
    return resolved_out

def compress_video(input_path, output_path=None, target_bytes=None, crf=28, max_height=720):
    _require_ffmpeg()
    resolved_in, resolved_out = _resolve_paths(input_path, output_path, "_compressed")
    if not resolved_out.lower().endswith((".mp4", ".mov", ".mkv")):
        resolved_out = os.path.splitext(resolved_out)[0] + ".mp4"
    scale_filter = f"scale=-2:'min({max_height},ih)'"
    duration = _probe_duration(resolved_in) if target_bytes else None
    if target_bytes and duration:
        audio_kbps = 64
        video_kbps = max(150, int((target_bytes * 8 / 1000) / duration) - audio_kbps)
        _run_ffmpeg(["-i", resolved_in, "-vf", scale_filter,
            "-c:v", "libx264", "-b:v", f"{video_kbps}k",
            "-preset", "medium", "-c:a", "aac", "-b:a", f"{audio_kbps}k",
            resolved_out,])
    else:
        crf = max(VIDEO_CRF_MIN, min(VIDEO_CRF_MAX, crf))
        _run_ffmpeg(["-i", resolved_in, "-vf", scale_filter,
            "-c:v", "libx264", "-crf", str(crf),
            "-preset", "medium", "-c:a", "aac", "-b:a", "96k",
            resolved_out,])
    final_size = os.path.getsize(resolved_out)
    _warn_if_over_target(input_path, final_size, target_bytes)
    _report_sizes(input_path, resolved_in, resolved_out)
    return resolved_out

def compress_for_platform(input_path, media_type, platform="gmail", output_path=None):
    if platform not in PLATFORM_LIMITS:
        raise ValueError(f"Unknown platform: {platform}")
    if media_type not in PLATFORM_LIMITS[platform]:
        raise ValueError(f"Unknown media_type: {media_type}")
    target_bytes = PLATFORM_LIMITS[platform][media_type] * 1024 * 1024
    compressors = {"image": compress_image,
        "audio": compress_audio,
        "video": compress_video,}
    return compressors[media_type](input_path, output_path, target_bytes=target_bytes)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("--type", choices=["image", "audio", "video"], required=True)
    parser.add_argument("--platform", choices=["gmail", "whatsapp", "whatsapp_document"], default="gmail")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    compress_for_platform(args.input, args.type, args.platform, args.output)

    # py media_compress.py photo.jpg --type image --platform whatsapp
    # py media_compress.py clip.mp4 --type video --platform gmail