#!/usr/bin/env python3
"""
YouTube Transcript Pipeline — Modern TUI
Run: python ui.py
"""

import os
import sys
import tempfile
from pathlib import Path

# Fix Windows terminal encoding for Unicode characters
if sys.platform == "win32":
    os.environ["PYTHONIOENCODING"] = "utf-8"

from rich.console import Console
from rich.panel import Panel
from rich.columns import Columns
from rich.table import Table
from rich.prompt import Prompt, Confirm
from rich.text import Text
from rich.rule import Rule
from rich import box

sys.path.insert(0, str(Path(__file__).parent))
from pipeline import (
    load_config, load_downloaded, save_downloaded,
    search_videos, get_video_metadata, process_video, to_markdown,
    video_id_from_url, extract_playlist_videos,
)

console = Console(emoji=False)


def safe_text(text, max_length=60):
    """Remove emoji and other characters that break Windows terminal output."""
    if not text:
        return ""
    # Replace common emoji and wide unicode chars
    cleaned = ""
    for char in text:
        if ord(char) > 0xFFFF:
            cleaned += "?"  # Replace emoji with ?
        else:
            cleaned += char
    return cleaned[:max_length]


# Palette — inspired by clean, modern design (teal / sage / coral)
TEAL   = "#4AADA0"
SAGE   = "#7BBF9E"
CORAL  = "#E8927C"
MUTED  = "#8B9BB4"


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------

def print_header():
    console.clear()
    title = Text()
    title.append("YouTube ", style=f"bold {TEAL}")
    title.append("Transcript", style="bold white")
    title.append(" Pipeline", style=f"bold {SAGE}")

    sub = Text("Extract  ·  Clean  ·  Save to Obsidian", style=f"dim {MUTED}")

    block = Text()
    block.append_text(title)
    block.append("\n")
    block.append_text(sub)

    console.print(
        Panel(block, border_style=TEAL, padding=(1, 6), expand=False),
        justify="center",
    )
    console.print()


def print_menu():
    card1 = Panel(
        Text.from_markup(
            f"[bold {TEAL}]Search[/bold {TEAL}] by keyword\n\n"
            f"[dim]Find videos by topic,\nfilter by channel[/dim]"
        ),
        title="[bold]  1  [/bold]",
        border_style=TEAL,
        padding=(1, 3),
        width=24,
    )
    card2 = Panel(
        Text.from_markup(
            f"[bold {SAGE}]Paste[/bold {SAGE}] a YouTube URL\n\n"
            f"[dim]Process a single video\ndirectly by URL[/dim]"
        ),
        title="[bold]  2  [/bold]",
        border_style=SAGE,
        padding=(1, 3),
        width=24,
    )
    card3 = Panel(
        Text.from_markup(
            f"[bold {CORAL}]Playlist[/bold {CORAL}] URL\n\n"
            f"[dim]Browse a public playlist\nand select videos[/dim]"
        ),
        title="[bold]  3  [/bold]",
        border_style=CORAL,
        padding=(1, 3),
        width=24,
    )
    card4 = Panel(
        Text.from_markup(
            f"[bold #8B9BB4]Quit[/bold #8B9BB4]\n\n"
            f"[dim]Exit the pipeline[/dim]"
        ),
        title="[bold]  Q  [/bold]",
        border_style="#8B9BB4",
        padding=(1, 3),
        width=24,
    )
    console.print(Columns([card1, card2, card3, card4], expand=False), justify="center")
    console.print()


# ---------------------------------------------------------------------------
# Input forms
# ---------------------------------------------------------------------------

def get_search_params(config):
    console.print(Rule(f"[{TEAL}]Search Settings[/{TEAL}]"))
    console.print()
    query   = Prompt.ask(f"  [{TEAL}]Topic / keyword[/{TEAL}]")
    channel = Prompt.ask(f"  [dim]Channel filter  [/dim] [dim](leave blank to skip)[/dim]", default="")
    lang    = Prompt.ask(f"  [dim]Language code   [/dim]", default=config.get("default_lang", "en"))
    limit   = Prompt.ask(f"  [dim]Max videos      [/dim]", default=str(config.get("default_limit", 10)))
    fallback = Confirm.ask(f"  [dim]Enable Whisper fallback?[/dim]", default=False)
    console.print()
    return {
        "query":    query,
        "channel":  channel or None,
        "lang":     lang,
        "limit":    int(limit),
        "fallback": fallback,
    }


def get_url_params(config):
    console.print(Rule(f"[{SAGE}]Video URL[/{SAGE}]"))
    console.print()
    url      = Prompt.ask(f"  [{SAGE}]YouTube URL[/{SAGE}]")
    lang     = Prompt.ask(f"  [dim]Language code[/dim]", default=config.get("default_lang", "en"))
    fallback = Confirm.ask(f"  [dim]Enable Whisper fallback?[/dim]", default=False)
    console.print()
    return {"url": url, "lang": lang, "fallback": fallback}


def get_playlist_params(config):
    console.print(Rule(f"[{CORAL}]Playlist URL[/{CORAL}]"))
    console.print()
    url      = Prompt.ask(f"  [{CORAL}]Playlist URL[/{CORAL}]")
    lang     = Prompt.ask(f"  [dim]Language code[/dim]", default=config.get("default_lang", "en"))
    fallback = Confirm.ask(f"  [dim]Enable Whisper fallback?[/dim]", default=False)
    console.print()
    return {"url": url, "lang": lang, "fallback": fallback}


def select_videos_from_playlist(videos):
    """Display playlist videos and let user select which ones to process."""
    if not videos:
        console.print(f"  [{CORAL}]No videos found in playlist.[/{CORAL}]\n")
        return []
    
    console.print(Rule(f"[{CORAL}]Playlist Videos[/{CORAL}]"))
    console.print()
    
    for i, video in enumerate(videos, 1):
        title = safe_text(video.get("title") or "Untitled", 65)
        channel = safe_text(video.get("channel") or video.get("uploader", "—"), 30)
        duration = video.get("duration", 0)
        if duration:
            mins, secs = divmod(int(duration), 60)
            duration_str = f"{mins}:{secs:02d}"
        else:
            duration_str = "—"
        
        console.print(f"  [bold {CORAL}]{i:>3}.[/bold {CORAL}] {title}  [dim]({channel}, {duration_str})[/dim]")
    
    console.print()
    console.print(f"  [dim]Enter numbers to select (e.g., 1,3,5-10) or type 'all'[/dim]")
    selection = Prompt.ask(f"  [bold]Select videos[/bold]")
    
    if selection.lower().strip() == "all":
        return videos
    
    selected_indices = set()
    for part in selection.split(","):
        part = part.strip()
        if "-" in part:
            try:
                start, end = part.split("-")
                selected_indices.update(range(int(start.strip()) - 1, int(end.strip())))
            except (ValueError, IndexError):
                continue
        else:
            try:
                selected_indices.add(int(part) - 1)
            except ValueError:
                continue
    
    selected = []
    for idx in sorted(selected_indices):
        if 0 <= idx < len(videos):
            selected.append(videos[idx])
    
    return selected


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------

def run_pipeline(videos, config, lang, fallback, output_dir):
    downloaded   = load_downloaded()
    whisper_model = config.get("whisper_model", "base")
    results      = []

    console.print(Rule(f"[{TEAL}]Processing {len(videos)} video(s)[/{TEAL}]"))
    console.print()

    table = Table(
        box=box.ROUNDED,
        border_style=MUTED,
        header_style=f"bold {TEAL}",
        show_lines=False,
        expand=True,
    )
    table.add_column("Title",   style="white",         ratio=5)
    table.add_column("Channel", style=f"dim {MUTED}",  ratio=2)
    table.add_column("Status",  justify="center",      ratio=1)
    table.add_column("Source",  justify="center",      ratio=1)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        for i, video in enumerate(videos, 1):
            video_id = video.get("id")
            if not video_id:
                continue

            title_preview = safe_text(video.get("title") or video_id, 60)

            if video_id in downloaded:
                table.add_row(
                    title_preview,
                    safe_text(video.get("channel") or video.get("uploader", "—"), 25),
                    f"[{CORAL}]skipped[/{CORAL}]",
                    "—",
                )
                results.append("skip")
                continue

            with console.status(
                f"  [{TEAL}][{i}/{len(videos)}][/{TEAL}]  {safe_text(title_preview, 50)}…",
                spinner="dots",
                spinner_style=TEAL,
            ):
                meta = get_video_metadata(video_id) or video
                transcript, source = process_video(
                    video_id, lang, whisper_model, tmp_path, fallback
                )

            channel = safe_text(meta.get("channel") or meta.get("uploader", "—"), 25)

            if transcript:
                filename, content = to_markdown(meta, transcript, source)
                (output_dir / filename).write_text(content, encoding="utf-8")
                downloaded.add(video_id)
                save_downloaded(downloaded)

                src_tag = (
                    f"[{TEAL}]{source}[/{TEAL}]"
                    if source == "subtitles"
                    else f"[{SAGE}]{source}[/{SAGE}]"
                )
                table.add_row(title_preview, channel, f"[bold {SAGE}]saved[/bold {SAGE}]", src_tag)
                results.append("saved")
            else:
                table.add_row(title_preview, channel, f"[{CORAL}]failed[/{CORAL}]", "—")
                results.append("failed")

    console.print(table)
    console.print()

    saved   = results.count("saved")
    skipped = results.count("skip")
    failed  = results.count("failed")

    summary = Text()
    summary.append(f"  {saved} saved  ", style=f"bold {SAGE}")
    summary.append("·  ", style=f"dim {MUTED}")
    summary.append(f"{skipped} skipped  ", style=CORAL)
    summary.append("·  ", style=f"dim {MUTED}")
    summary.append(f"{failed} failed", style=f"dim {MUTED}")

    console.print(Panel(summary, border_style=MUTED, padding=(0, 2)))
    console.print()


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main():
    config     = load_config()
    output_dir = Path(config["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    while True:
        print_header()
        print_menu()

        choice = Prompt.ask(
            f"  [bold]Choose[/bold]",
            choices=["1", "2", "3", "q", "Q"],
            show_choices=False,
        )

        if choice.lower() == "q":
            console.print(f"\n  [dim {MUTED}]Goodbye.[/dim {MUTED}]\n")
            break

        console.print()

        if choice == "1":
            params = get_search_params(config)
            with console.status(
                f"  [{TEAL}]Searching YouTube…[/{TEAL}]",
                spinner="dots",
                spinner_style=TEAL,
            ):
                videos = search_videos(params["query"], params["channel"], params["limit"])

            if not videos:
                console.print(f"  [{CORAL}]No results found.[/{CORAL}]\n")
            else:
                console.print(f"  [{TEAL}]Found {len(videos)} video(s)[/{TEAL}]\n")
                run_pipeline(videos, config, params["lang"], params["fallback"], output_dir)

        elif choice == "2":
            params   = get_url_params(config)
            video_id = video_id_from_url(params["url"])
            run_pipeline([{"id": video_id}], config, params["lang"], params["fallback"], output_dir)

        elif choice == "3":
            params = get_playlist_params(config)
            with console.status(
                f"  [{CORAL}]Fetching playlist videos…[/{CORAL}]",
                spinner="dots",
                spinner_style=CORAL,
            ):
                videos = extract_playlist_videos(params["url"])

            if not videos:
                console.print(f"  [{CORAL}]No videos found in playlist.[/{CORAL}]\n")
            else:
                selected = select_videos_from_playlist(videos)
                if selected:
                    console.print(f"  [{CORAL}]Selected {len(selected)} video(s)[/{CORAL}]\n")
                    run_pipeline(selected, config, params["lang"], params["fallback"], output_dir)

        if not Confirm.ask(f"  [dim]Run another?[/dim]", default=True):
            console.print(f"\n  [dim {MUTED}]Goodbye.[/dim {MUTED}]\n")
            break


if __name__ == "__main__":
    main()
