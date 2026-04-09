# YouTube Transcript Pipeline

A local tool that searches YouTube, downloads transcripts, and saves them as clean Obsidian-compatible markdown files.

## Features

- Search YouTube by keyword or paste a direct video URL
- Downloads subtitles automatically (manual or auto-generated)
- Falls back to Whisper audio transcription when subtitles are unavailable
- Saves transcripts as Obsidian-ready markdown with YAML frontmatter
- Skips already-downloaded videos (dedup log)
- Modern terminal UI powered by [Rich](https://github.com/Textualize/rich)

## Requirements

- Python 3.9+
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- [Whisper](https://github.com/openai/whisper) *(optional, for audio fallback)*
- [Rich](https://github.com/Textualize/rich)

## Setup

```bash
# 1. Clone the repo
git clone https://github.com/YOUR_USERNAME/youtube-transcript-pipeline.git
cd youtube-transcript-pipeline

# 2. Create a virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Mac / Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure
copy config.ini.example config.ini
# Edit config.ini and set your output_dir
```

## Usage

### Interactive UI (recommended)

```bash
python ui.py
```

### Command line

```bash
# Search by keyword
python pipeline.py "prompt engineering"

# Search with channel filter
python pipeline.py "trading psychology" --channel "Ali Abdaal"

# Single video by URL
python pipeline.py --url "https://www.youtube.com/watch?v=XXXXXXXXXXX"

# Limit results and set language
python pipeline.py "supply chain" --limit 5 --lang de

# Enable Whisper fallback for videos without subtitles
python pipeline.py "deep learning" --fallback
```

## Output

Each transcript is saved as a markdown file with YAML frontmatter:

```markdown
---
title: "Video Title"
url: https://www.youtube.com/watch?v=...
channel: "Channel Name"
published: 2024-01-15
downloaded: 2026-04-09
transcript_source: subtitles
tags: [transcript, youtube]
---
```

## License

MIT
