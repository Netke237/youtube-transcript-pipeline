#!/usr/bin/env python3
"""
YouTube Transcript Pipeline

Usage:
  python pipeline.py "search query"
  python pipeline.py "search query" --channel "Ali Abdaal"
  python pipeline.py "search query" --limit 5
  python pipeline.py "search query" --lang de
  python pipeline.py --url "https://www.youtube.com/watch?v=XXXXXXXXXXX"
  python pipeline.py "search query" --fallback     # enable audio fallback via Whisper
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / "config.ini"
DOWNLOADED_LOG = SCRIPT_DIR / "downloaded.json"

# Resolve executables relative to the current Python install
_SCRIPTS_DIR = Path(sys.executable).parent / "Scripts"
YT_DLP = [sys.executable, "-m", "yt_dlp"]
WHISPER_EXE = str(_SCRIPTS_DIR / "whisper.exe") if (_SCRIPTS_DIR / "whisper.exe").exists() else "whisper"


# ---------------------------------------------------------------------------
# Config & dedup log
# ---------------------------------------------------------------------------

def load_config():
    import configparser
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_FILE, encoding="utf-8")
    s = cfg["pipeline"]
    return {
        "output_dir": s.get("output_dir", r"F:\Obsidian\ObsidianVault\Public\inbox"),
        "whisper_model": s.get("whisper_model", "base"),
        "default_limit": s.getint("default_limit", 10),
        "default_lang": s.get("default_lang", "en"),
    }


def load_downloaded():
    if DOWNLOADED_LOG.exists():
        with open(DOWNLOADED_LOG, encoding="utf-8") as f:
            return set(json.load(f).get("downloaded", []))
    return set()


def save_downloaded(downloaded):
    with open(DOWNLOADED_LOG, "w", encoding="utf-8") as f:
        json.dump({"downloaded": sorted(downloaded)}, f, indent=2)


# ---------------------------------------------------------------------------
# Search & metadata
# ---------------------------------------------------------------------------

def search_videos(query, channel=None, limit=10):
    """Search YouTube via yt-dlp and return list of metadata dicts."""
    if channel:
        search_query = f"ytsearch{limit}:{query} {channel}"
    else:
        search_query = f"ytsearch{limit}:{query}"

    cmd = YT_DLP + [
        "--flat-playlist",
        "--dump-json",
        "--no-warnings",
        search_query,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if not result.stdout.strip():
        print(f"  [debug] yt-dlp returned no output. stderr: {result.stderr[:300]}")
        print(f"  [debug] Python: {sys.executable}")
        print(f"  [debug] cmd: {' '.join(cmd[:3])} ...")
    videos = []
    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        if line:
            try:
                videos.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return videos


def get_video_metadata(video_id):
    """Fetch full metadata for a single video ID."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    cmd = YT_DLP + [
        "--dump-json",
        "--no-warnings",
        "--skip-download",
        url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.stdout.strip():
        try:
            return json.loads(result.stdout.strip())
        except json.JSONDecodeError:
            pass
    return {}


def video_id_from_url(url):
    """Extract video ID from a YouTube URL."""
    match = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", url)
    return match.group(1) if match else url


# ---------------------------------------------------------------------------
# Subtitles
# ---------------------------------------------------------------------------

def get_subtitles(video_id, lang, output_dir):
    """Try to download manual or auto-generated subtitles. Returns .vtt path or None."""
    url = f"https://www.youtube.com/watch?v={video_id}"

    cmd = YT_DLP + [
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs", f"{lang},-live_chat",
        "--sub-format", "vtt",
        "--skip-download",
        "--no-warnings",
        "-o", str(output_dir / "%(id)s.%(ext)s"),
        url,
    ]

    subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")

    for f in output_dir.glob(f"{video_id}*.vtt"):
        return f
    return None


def parse_vtt(vtt_path):
    """Convert a VTT subtitle file to clean plain text."""
    text = vtt_path.read_text(encoding="utf-8")
    lines = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("WEBVTT"):
            continue
        if re.match(r"^\d{2}:\d{2}.*-->", line):
            continue
        if re.match(r"^\d+$", line):
            continue
        line = re.sub(r"<[^>]+>", "", line)  # strip HTML tags
        if line:
            lines.append(line)

    # Remove consecutive duplicate lines (common in auto-generated subs)
    deduped = []
    prev = None
    for line in lines:
        if line != prev:
            deduped.append(line)
            prev = line

    return " ".join(deduped)


# ---------------------------------------------------------------------------
# Audio fallback
# ---------------------------------------------------------------------------

def download_audio(video_id, output_dir):
    """Download audio as mp3 to output_dir. Returns path or None."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    output_template = str(output_dir / f"{video_id}.%(ext)s")

    cmd = YT_DLP + [
        "-x",
        "--audio-format", "mp3",
        "--audio-quality", "5",  # mid-quality, fine for speech
        "--no-warnings",
        "-o", output_template,
        url,
    ]

    subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")

    matches = list(output_dir.glob(f"{video_id}*.mp3"))
    return matches[0] if matches else None


def transcribe_audio(audio_path, lang, model="base"):
    """Transcribe audio with Whisper. Returns transcript text or None."""
    cmd = [
        WHISPER_EXE,
        str(audio_path),
        "--model", model,
        "--language", lang,
        "--output_format", "txt",
        "--output_dir", str(audio_path.parent),
        "--verbose", "False",
    ]

    subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")

    txt_path = audio_path.with_suffix(".txt")
    if txt_path.exists():
        return txt_path.read_text(encoding="utf-8").strip()
    return None


# ---------------------------------------------------------------------------
# Markdown output
# ---------------------------------------------------------------------------

def to_markdown(meta, transcript, source):
    """Build Obsidian-compatible markdown. Returns (filename, content)."""
    title = meta.get("title", "Untitled")
    video_id = meta.get("id", "")
    url = f"https://www.youtube.com/watch?v={video_id}"
    channel = meta.get("channel") or meta.get("uploader", "Unknown")

    raw_date = meta.get("upload_date", "")
    if raw_date and len(raw_date) == 8:
        published = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
    else:
        published = raw_date or "unknown"

    downloaded = datetime.now().strftime("%Y-%m-%d")

    safe_title = re.sub(r'[\\/*?:"<>|]', "", title)[:80].strip()
    filename = f"{downloaded}_{safe_title}.md".replace(" ", "_")

    content = f"""---
title: "{title}"
url: {url}
channel: "{channel}"
published: {published}
downloaded: {downloaded}
transcript_source: {source}
tags: [transcript, youtube]
---

# {title}

{transcript}
"""
    return filename, content


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def process_video(video_id, lang, whisper_model, tmp_path, fallback=False):
    """
    Process a single video: subtitles -> (optional) audio fallback.
    Returns (transcript, source) or (None, None).
    """
    # Step 1: subtitles
    sub_file = get_subtitles(video_id, lang, tmp_path)
    if sub_file:
        transcript = parse_vtt(sub_file)
        if transcript:
            return transcript, "subtitles"

    # Step 2: audio fallback (only if --fallback flag set)
    if not fallback:
        return None, None

    print("    -> no subtitles, downloading audio...")
    audio_file = download_audio(video_id, tmp_path)
    if not audio_file:
        return None, None

    print(f"    -> transcribing with Whisper ({whisper_model})...")
    transcript = transcribe_audio(audio_file, lang, whisper_model)
    audio_file.unlink(missing_ok=True)  # clean up audio immediately

    if transcript:
        return transcript, "whisper"
    return None, None


def main():
    parser = argparse.ArgumentParser(description="YouTube Transcript Pipeline")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("query", nargs="?", help="Search query")
    group.add_argument("--url", "-u", help="Process a single YouTube URL")

    parser.add_argument("--channel", "-c", help="Filter search by channel name")
    parser.add_argument("--limit", "-n", type=int, default=None, help="Number of videos (default: from config)")
    parser.add_argument("--lang", "-l", default=None, help="Language code, e.g. en, de, fr (default: from config)")
    parser.add_argument("--fallback", action="store_true", help="Enable audio download + Whisper transcription when subtitles are missing")

    args = parser.parse_args()

    config = load_config()
    output_dir = Path(config["output_dir"])
    whisper_model = config.get("whisper_model", "base")
    limit = args.limit or config.get("default_limit", 10)
    lang = args.lang or config.get("default_lang", "en")

    output_dir.mkdir(parents=True, exist_ok=True)
    downloaded = load_downloaded()

    # Collect videos to process
    if args.url:
        video_id = video_id_from_url(args.url)
        videos = [{"id": video_id}]
        print(f"Processing single URL: {args.url}")
    else:
        print(f"Searching: '{args.query}'" + (f"  channel: '{args.channel}'" if args.channel else ""))
        videos = search_videos(args.query, args.channel, limit)
        print(f"Found {len(videos)} videos\n")

    processed = 0
    skipped = 0
    failed = 0

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        for video in videos:
            video_id = video.get("id")
            if not video_id:
                continue

            title_preview = video.get("title", video_id)[:65]

            if video_id in downloaded:
                print(f"  [skip]    {title_preview}")
                skipped += 1
                continue

            print(f"  [process] {title_preview}")

            # Full metadata (needed for channel, date, etc.)
            meta = get_video_metadata(video_id)
            if not meta:
                meta = video

            transcript, source = process_video(video_id, lang, whisper_model, tmp_path, args.fallback)

            if transcript:
                filename, content = to_markdown(meta, transcript, source)
                out_file = output_dir / filename
                out_file.write_text(content, encoding="utf-8")
                downloaded.add(video_id)
                save_downloaded(downloaded)
                print(f"    -> [{source}] saved: {filename}")
                processed += 1
            else:
                reason = "no subtitles (use --fallback to try audio)" if not args.fallback else "failed"
                print(f"    -> failed: {reason}")
                failed += 1

    print(f"\nDone — {processed} saved, {skipped} already downloaded, {failed} failed.")


if __name__ == "__main__":
    main()
