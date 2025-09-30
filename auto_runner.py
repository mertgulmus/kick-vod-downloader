import os
import sys
import json
import time
import threading
from typing import Dict, List, Tuple, Optional

from rich.console import Console
from rich.panel import Panel

from libs.config import Config
from libs.web_driver_manager import WebDriverManager
from libs.file_manager import FileManager
from libs.vod_downloader import VodDownloader
from libs.step_logger import StepLogger


def _debug(message: str, console: Optional[Console] = None) -> None:
    if Config.DEBUG_VERBOSE:
        if console:
            try:
                console.log(f"[debug] {message}")
                return
            except Exception:
                pass
        print(f"[debug] {message}")


STATE_LOCK = threading.Lock()
STATE_RETENTION = 200


def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "y", "on")


def _load_state(path: str) -> Dict[str, List[str]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(path: str, data: Dict[str, List[str]]) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def _normalize_history(history) -> List[str]:
    if isinstance(history, list):
        values = history
    elif isinstance(history, str):
        values = [history]
    else:
        values = []
    seen = set()
    ordered: List[str] = []
    for item in values:
        if not isinstance(item, str):
            continue
        if item in seen:
            continue
        ordered.append(item)
        seen.add(item)
    return ordered[-STATE_RETENTION:]


def _get_channel_history(state_path: str, channel: str) -> List[str]:
    with STATE_LOCK:
        state = _load_state(state_path)
        history = state.get(channel)
    return _normalize_history(history)


def _set_channel_history(state_path: str, channel: str, history: List[str]) -> List[str]:
    normalized = _normalize_history(history)
    with STATE_LOCK:
        state = _load_state(state_path)
        state[channel] = normalized
        _save_state(state_path, state)
    return normalized


def _list_channel_vods(vd: VodDownloader, channel: str) -> List[Tuple[str, str]]:
    links: List[str] = []
    if vd.driver:
        try:
            links = vd.fetch_channel_vod_links(channel)
        except Exception:
            links = []
    if not links:
        latest = vd.get_latest_vod_link(channel)
        if latest:
            links = [latest]

    items: List[Tuple[str, str]] = []
    seen = set()
    for link in links:
        uuid = vd._parse_uuid_from_vod_url(link)
        if not uuid or uuid in seen:
            continue
        items.append((uuid, link))
        seen.add(uuid)
    return items


def _worker(channel: str, quality: str, poll_seconds: int, live_check_seconds: int, state_path: str, console: Console) -> None:
    steps = StepLogger(console)
    fm = FileManager()

    driver = WebDriverManager(console).setup()
    if not driver:
        console.print(f"[bold red]Failed to init WebDriver for {channel}[/bold red]")
        return

    vd = VodDownloader(driver=driver, console=console, file_manager=fm, step_logger=steps)

    try:
        console.print(Panel(f"[cyan]Watching channel:[/cyan] [bold]{channel}[/bold]", title="Worker", border_style="cyan"))
        _debug(f"{channel}: worker started", console)

        history = _get_channel_history(state_path, channel)
        processed = set(history)
        queue_step_id = steps.start_step(f"{channel}: backlog", detail="initializing")
        current_task: Optional[str] = None
        _debug(f"{channel}: loaded history entries -> {len(history)}", console)

        def update_queue_detail(pending_count: int, status: str) -> None:
            summary = f"pending: {pending_count}, processed: {len(processed)}"
            if current_task:
                summary += f", downloading: {current_task}"
            elif status:
                summary += f", status: {status}"
            steps.set_detail(queue_step_id, summary)
            _debug(f"{channel}: backlog status -> {summary}", console)

        def record_processed(uuid: str, pending_after: int) -> None:
            nonlocal history, processed, current_task
            if uuid in processed:
                return
            history.append(uuid)
            history = _set_channel_history(state_path, channel, history)
            processed = set(history)
            current_task = None
            update_queue_detail(pending_after, "idle")
            _debug(f"{channel}: recorded VOD {uuid} as processed", console)

        while True:
            vod_items = _list_channel_vods(vd, channel)
            pending_list = [u for u, _ in vod_items if u not in processed]
            _debug(f"{channel}: poll -> total VODs {len(vod_items)}, pending {len(pending_list)}", console)
            if not vod_items or not pending_list:
                update_queue_detail(0, "idle")
                time.sleep(live_check_seconds)
                continue

            update_queue_detail(len(pending_list), "ready")
            downloaded_any = False

            for uuid, vod_page in vod_items:
                if uuid in processed:
                    _debug(f"{channel}: skipping already processed VOD {uuid}", console)
                    continue

                meta = vd.get_video_metadata_by_uuid(uuid)
                basename = vd.build_suggested_basename(channel, meta, quality)
                mp3_target = os.path.join(Config.DOWNLOAD_DIR, f"{basename}.mp3")

                current_task = basename
                pending_now = len([u for u, _ in vod_items if u not in processed])
                update_queue_detail(pending_now, "downloading")
                _debug(f"{channel}: preparing download for {basename} (uuid {uuid})", console)

                if os.path.exists(mp3_target):
                    console.print(f"[green]{channel}[/green]: {basename} already exists; skipping")
                    pending_after_skip = len([u for u, _ in vod_items if u not in processed and u != uuid])
                    record_processed(uuid, pending_after_skip)
                    _debug(f"{channel}: file already exists at {mp3_target}; skip", console)
                    continue

                with steps.step(f"{channel}: resolve {uuid[:8]}") as set_detail:
                    set_detail("fetching master playlist")
                    master = vd.get_video_master_m3u8_by_uuid(uuid)
                    if not master:
                        set_detail("master m3u8 missing; retry later")
                        current_task = None
                        _debug(f"{channel}: missing master playlist for {uuid}", console)
                        continue
                    set_detail("selecting variant")
                    variant = vd._derive_variant_from_master_url(master, quality)
                    if not variant:
                        set_detail("variant m3u8 missing; retry later")
                        current_task = None
                        _debug(f"{channel}: unable to derive variant for {uuid}", console)
                        continue
                    _debug(f"{channel}: resolved variant playlist {variant}", console)

                with steps.step(f"{channel}: download {basename}") as set_detail:
                    set_detail("downloading segments")
                    _debug(f"{channel}: starting download_vod_from_m3u8 for {basename}", console)
                    mp3_path = vd.download_vod_from_m3u8(variant, output_basename=basename)
                    if not mp3_path:
                        set_detail("download failed")
                        current_task = None
                        _debug(f"{channel}: download failed for {basename}", console)
                        continue
                    set_detail(f"saved {mp3_path}")
                    _debug(f"{channel}: download completed -> {mp3_path}", console)

                pending_after = len([u for u, _ in vod_items if u not in processed and u != uuid])
                record_processed(uuid, pending_after)
                downloaded_any = True

            if not downloaded_any:
                time.sleep(live_check_seconds)
            else:
                time.sleep(poll_seconds)

    except KeyboardInterrupt:
        pass
    finally:
        WebDriverManager(console).close(driver)
        steps.stop()


if __name__ == "__main__":
    console = Console()

    download_dir = os.getenv("DOWNLOAD_DIR")
    if download_dir:
        Config.DOWNLOAD_DIR = download_dir
    debug_http = _env_bool("DEBUG_HTTP", False)
    if debug_http:
        Config.DEBUG_HTTP = True
    debug_verbose = _env_bool("DEBUG_VERBOSE", False)
    if debug_verbose:
        Config.DEBUG_VERBOSE = True
        _debug("Verbose debug logging enabled", console)

    # Get channels from env or config, handling empty strings
    channels_str = os.getenv("CHANNELS", "").strip()
    if not channels_str and Config.TARGET_CHANNEL:
        channels_str = Config.TARGET_CHANNEL

    channels = [c.strip() for c in channels_str.split(",") if c.strip()]

    if not channels:
        console.print("[bold red]Error:[/bold red] No channels configured. Set CHANNELS env var or Config.TARGET_CHANNEL.")
        console.print("Example: export CHANNELS='channel1,channel2'")
        sys.exit(1)

    quality = os.getenv("QUALITY", "480p30")
    poll_seconds = int(os.getenv("POLL_SECONDS", "60"))
    live_check_seconds = int(os.getenv("LIVE_CHECK_SECONDS", "60"))
    os.makedirs(Config.DOWNLOAD_DIR, exist_ok=True)

    state_path = os.path.join(Config.DOWNLOAD_DIR, "_state.json")
    console.print(Panel(f"[bold green]Kick Auto Downloader[/bold green]\nDir: {Config.DOWNLOAD_DIR}\nChannels: {', '.join(channels)}\nQuality: {quality}", title="Init", border_style="green"))

    threads = []
    for ch in channels:
        t = threading.Thread(target=_worker, args=(ch, quality, poll_seconds, live_check_seconds, state_path, console), daemon=True)
        threads.append(t)
        t.start()

    try:
        while any(t.is_alive() for t in threads):
            time.sleep(5)
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Shutting down…[/bold yellow]")
