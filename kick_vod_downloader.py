import sys
import traceback
import os
import argparse
import time
from typing import Optional

from rich import print
from rich.panel import Panel
from rich.console import Console

from libs.config import Config
from libs.web_driver_manager import WebDriverManager
from libs.file_manager import FileManager
from libs.vod_downloader import VodDownloader
from libs.step_logger import StepLogger

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Kick VOD Downloader (Streaming-first)")
    parser.add_argument(
        "--m3u8-url",
        type=str,
        default=None,
        help="Direct m3u8 playlist URL to stream and convert (no Selenium)"
    )
    parser.add_argument(
        "--debug-http",
        action="store_true",
        help="Print HTTP debug info for API/page/playlist requests"
    )
    parser.add_argument(
        "--m3u8-poll-seconds",
        type=int,
        default=60,
        help="Polling interval in seconds for playlist when streaming (default: 60)"
    )
    parser.add_argument(
        "--m3u8-basename",
        type=str,
        default=None,
        help="Optional output base name for files; if not set, an informative name is generated"
    )
    parser.add_argument(
        "--live-channel",
        type=str,
        default=None,
        help="Kick channel name; resolves latest VOD m3u8 (not live playback) and streams"
    )
    parser.add_argument(
        "--live-quality",
        type=str,
        default=None,
        help="Preferred quality substring, e.g. '480p30' or '720p30' when using --live-channel"
    )

    args = parser.parse_args()

    # If a live channel is specified, resolve its m3u8 first and stream (always via Selenium to bypass CF)
    if args.live_channel:
        console = Console()
        console.print(Panel(f"[bold cyan]Kick VOD Downloader - Latest VOD Streaming[/bold cyan]", title="Init", border_style="cyan"))
        steps = StepLogger(console)
        driver = None
        try:
            if args.debug_http:
                with steps.step("Enable HTTP debug"):
                    Config.DEBUG_HTTP = True

            with steps.step("Initialize file manager"):
                fm = FileManager()

            with steps.step("Initialize WebDriver"):
                driver = WebDriverManager(console).setup()
                if not driver:
                    raise RuntimeError("WebDriver initialization failed")

            with steps.step("Create downloader instance"):
                vd = VodDownloader(driver=driver, console=console, file_manager=fm, step_logger=steps)

            # Strict strategy: DO NOT use live playback m3u8; always use latest VOD → v1 video API → variant
            variant = args.live_quality or '480p30'

            # 1) Wait for channel to go live (poll every 60s)
            with steps.step("Wait for channel to go live") as set_detail:
                while True:
                    try:
                        live = vd.is_channel_live(args.live_channel)
                    except Exception:
                        live = False
                    if live:
                        set_detail("Channel is live")
                        break
                    set_detail("Not live; rechecking in 60s")
                    time.sleep(60)

            # 2) Once live, poll for the latest VOD m3u8 until available
            with steps.step(f"Resolve latest VOD m3u8 ({variant})") as set_detail:
                resolved = None
                latest_vod_url = None
                while not resolved:
                    resolved, latest_vod_url = vd.get_latest_vod_variant_m3u8(args.live_channel, preferred_variant=variant)
                    if resolved:
                        break
                    set_detail("VOD not yet available; retrying in 60s")
                    time.sleep(60)
                set_detail(f"Resolved: {resolved}")

            with steps.step("Determine output name") as set_detail:
                basename = args.m3u8_basename
                if not basename:
                    vod_link = latest_vod_url or vd.get_latest_vod_link(args.live_channel)
                    uuid = vd._parse_uuid_from_vod_url(vod_link) if vod_link else None
                    meta = vd.get_video_metadata_by_uuid(uuid) if uuid else None
                    basename = vd.build_suggested_basename(args.live_channel, meta, variant)
                set_detail(f"Basename: {basename}")

            with steps.step("Stream and convert to MP3") as set_detail:
                mp3_path = vd.stream_vod_from_m3u8(
                    resolved,
                    output_basename=basename,
                    poll_seconds=args.m3u8_poll_seconds,
                )
                if not mp3_path:
                    raise RuntimeError("Streaming download failed")
                set_detail(f"Saved: {mp3_path}")

            console.print(f"[bold green]Success.[/bold green] MP3 saved to: {mp3_path}")
            if driver:
                WebDriverManager(console).close(driver)
            steps.stop()
            sys.exit(0)
        except KeyboardInterrupt:
            steps.stop()
            console.print("\n[bold yellow]Interrupted by user.[/bold yellow]")
            if driver:
                WebDriverManager(console).close(driver)
            sys.exit(130)
        except Exception as e:
            steps.stop()
            console.print(f"\n[bold red]Unexpected error:[/bold red] {e}")
            print(traceback.format_exc())
            if driver:
                WebDriverManager(console).close(driver)
            sys.exit(1)

    # If a direct m3u8 playlist URL is provided, stream and exit
    if args.m3u8_url:
        console = Console()
        console.print(Panel(f"[bold cyan]Kick VOD Downloader - M3U8 Streaming[/bold cyan]", title="Init", border_style="cyan"))
        steps = StepLogger(console)
        try:
            if args.debug_http:
                with steps.step("Enable HTTP debug"):
                    Config.DEBUG_HTTP = True

            with steps.step("Initialize file manager"):
                fm = FileManager()

            with steps.step("Create downloader instance"):
                vd = VodDownloader(driver=None, console=console, file_manager=fm, step_logger=steps)

            with steps.step("Stream and convert to MP3") as set_detail:
                mp3_path = vd.stream_vod_from_m3u8(
                    args.m3u8_url,
                    output_basename=args.m3u8_basename,
                    poll_seconds=args.m3u8_poll_seconds,
                )
                if not mp3_path:
                    raise RuntimeError("M3U8 streaming failed")
                set_detail(f"Saved: {mp3_path}")

            console.print(f"[bold green]Success.[/bold green] MP3 saved to: {mp3_path}")
            steps.stop()
            sys.exit(0)
        except KeyboardInterrupt:
            steps.stop()
            console.print("\n[bold yellow]Interrupted by user.[/bold yellow]")
            sys.exit(130)
        except Exception as e:
            steps.stop()
            console.print(f"\n[bold red]Unexpected error:[/bold red] {e}")
            print(traceback.format_exc())
            sys.exit(1)

    # Nothing provided: show help and exit
    parser.print_help()
    sys.exit(2)
