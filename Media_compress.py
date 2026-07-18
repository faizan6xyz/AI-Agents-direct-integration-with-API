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
VIDEO_CRF_MIN = 18
VIDEO_CRF_MAX = 35

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
        capture_output=True, text=True, timeout=1800)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr.strip()[:500]}")

def _probe_duration(path):
    if not FFPROBE_BIN:
        return None
    try:
        result = subprocess.run([FFPROBE_BIN, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=60)
        return float(result.stdout.strip())
    except (ValueError, subprocess.TimeoutExpired):
        return None

def _report_sizes(input_path, resolved_in, resolved_out):
    original_size = os.path.getsize(resolved_in)
    compressed_size = os.path.getsize(resolved_out)
    saved = original_size - compressed_size
    percent = (saved / original_size) * 100 if original_size else 0
    print(f"'{input_path}' -> '{resolved_out}'")
    print(f"Original size: {original_size / 1024:.1f} KB")
    print(f"Compressed size: {compressed_size / 1024:.1f} KB")
    print(f"Saved: {saved / 1024:.1f} KB ({percent:.1f}%)")
    return compressed_size

def compress_image(input_path, output_path=None, target_bytes=None,max_dimension=MAX_IMAGE_DIMENSION_DEFAULT):
    resolved_in, resolved_out = _resolve_paths(input_path, output_path, "_compressed")
    try:
        img = Image.open(resolved_in)
        img.load()
    except UnidentifiedImageError:
        raise ValueError(f"'{input_path}' is not a valid image file.")
    if img.mode in ("RGBA", "P") and resolved_out.lower().endswith((".jpg", ".jpeg")):
        img = img.convert("RGB")
    width, height = img.size
    if max(width, height) > max_dimension:
        ratio = max_dimension / max(width, height)
        img = img.resize((max(1, int(width * ratio)), max(1, int(height * ratio))), Image.LANCZOS)
    quality = IMAGE_QUALITY_START
    save_kwargs = {"optimize": True}
    is_jpeg = resolved_out.lower().endswith((".jpg", ".jpeg"))
    if is_jpeg:
        save_kwargs["quality"] = quality
    img.save(resolved_out, **save_kwargs)
    if target_bytes:
        while os.path.getsize(resolved_out) > target_bytes and quality > IMAGE_QUALITY_MIN:
            quality -= IMAGE_QUALITY_STEP
            if is_jpeg:
                img.save(resolved_out, quality=quality, optimize=True)
            else:
                width, height = img.size
                img = img.resize((int(width * 0.85), int(height * 0.85)), Image.LANCZOS)
                img.save(resolved_out, optimize=True)
    final_size = os.path.getsize(resolved_out)
    if target_bytes and final_size > target_bytes:
        logger.warning(f"Could not reach target size for '{input_path}': "
            f"{final_size / 1024:.0f} KB vs target {target_bytes / 1024:.0f} KB")
    _report_sizes(input_path, resolved_in, resolved_out)
    return resolved_out

def compress_audio(input_path, output_path=None, target_bytes=None, bitrate="64k"):
    _require_ffmpeg()
    resolved_in, resolved_out = _resolve_paths(input_path, output_path, "_compressed")
    if not resolved_out.lower().endswith((".mp3", ".m4a", ".aac", ".ogg")):
        resolved_out = os.path.splitext(resolved_out)[0] + ".mp3"
    bitrates_to_try = [bitrate] if not target_bytes else AUDIO_BITRATES
    for br in bitrates_to_try:
        _run_ffmpeg(["-i", resolved_in, "-vn", "-b:a", br, "-ac", "1", resolved_out])
        if not target_bytes or os.path.getsize(resolved_out) <= target_bytes:
            break
    final_size = os.path.getsize(resolved_out)
    if target_bytes and final_size > target_bytes:
        logger.warning(f"Could not reach target size for '{input_path}': "
            f"{final_size / (1024*1024):.1f} MB vs target {target_bytes / (1024*1024):.1f} MB")
    _report_sizes(input_path, resolved_in, resolved_out)
    return resolved_out

def compress_video(input_path, output_path=None, target_bytes=None,crf=28, max_height=720):
    _require_ffmpeg()
    resolved_in, resolved_out = _resolve_paths(input_path, output_path, "_compressed")
    if not resolved_out.lower().endswith((".mp4", ".mov", ".mkv")):
        resolved_out = os.path.splitext(resolved_out)[0] + ".mp4"
    scale_filter = f"scale=-2:'min({max_height},ih)'"
    if target_bytes:
        duration = _probe_duration(resolved_in)
        if duration and duration > 0:
            target_total_kbit = (target_bytes * 8) / 1000
            audio_kbit = 64
            video_kbps = max(150, int(target_total_kbit / duration) - audio_kbit)
            _run_ffmpeg(["-i", resolved_in, "-vf", scale_filter,
                "-c:v", "libx264", "-b:v", f"{video_kbps}k",
                "-preset", "medium", "-c:a", "aac", "-b:a", "64k",
                resolved_out])
            final_size = os.path.getsize(resolved_out)
            if final_size > target_bytes:
                logger.warning(f"Could not reach target size for '{input_path}': "
                    f"{final_size / (1024*1024):.1f} MB vs target {target_bytes / (1024*1024):.1f} MB")
            _report_sizes(input_path, resolved_in, resolved_out)
            return resolved_out
    crf = max(VIDEO_CRF_MIN, min(VIDEO_CRF_MAX, crf))
    _run_ffmpeg(["-i", resolved_in, "-vf", scale_filter,
        "-c:v", "libx264", "-crf", str(crf),
        "-preset", "medium", "-c:a", "aac", "-b:a", "96k",
        resolved_out])
    _report_sizes(input_path, resolved_in, resolved_out)
    return resolved_out

def compress_for_platform(input_path, media_type, platform="gmail", output_path=None):
    limits = {"gmail": {"image": 25 * 1024 * 1024, "audio": 25 * 1024 * 1024, "video": 25 * 1024 * 1024},
        "whatsapp": {"image": 5 * 1024 * 1024, "audio": 16 * 1024 * 1024, "video": 16 * 1024 * 1024},
        "whatsapp_document": {"image": 100 * 1024 * 1024, "audio": 100 * 1024 * 1024, "video": 100 * 1024 * 1024},}
    if platform not in limits:
        raise ValueError(f"Unknown platform: {platform}")
    if media_type not in limits[platform]:
        raise ValueError(f"Unknown media_type: {media_type}")
    target_bytes = limits[platform][media_type]
    if media_type == "image":
        return compress_image(input_path, output_path, target_bytes=target_bytes)
    if media_type == "audio":
        return compress_audio(input_path, output_path, target_bytes=target_bytes)
    if media_type == "video":
        return compress_video(input_path, output_path, target_bytes=target_bytes)
    raise ValueError(f"Unsupported media_type: {media_type}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("--type", choices=["image", "audio", "video"], required=True)
    parser.add_argument("--platform", choices=["gmail", "whatsapp", "whatsapp_document"], default="gmail")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    result = compress_for_platform(args.input, args.type, args.platform, args.output)
    
    # py Media_compress.py photo.jpg --type image --platform whatsapp
    # py Media_compress.py clip.mp4 --type video --platform gmail