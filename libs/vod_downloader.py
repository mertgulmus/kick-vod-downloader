import time
import traceback
import datetime
import os
import re
import subprocess
from urllib.parse import urlparse, urljoin
from typing import Set, Optional, List, Tuple
import requests

try:
    import cloudscraper
except ImportError:
    cloudscraper = None

from selenium.webdriver.remote.webdriver import WebDriver as RemoteWebDriver
from selenium.common.exceptions import (
    WebDriverException,
    TimeoutException,
)

from rich import print
from rich.console import Console


from .config import Config
from .file_manager import FileManager
from .step_logger import StepLogger

# Constants for timeouts and retries
HTTP_TIMEOUT = 30
PLAYLIST_TIMEOUT = 20
PAGE_TIMEOUT = 25
SEGMENT_MAX_FAILURES = 10  # Maximum number of segment failures before aborting

def _debug(message: str):
    if getattr(Config, "DEBUG_VERBOSE", False):
        print(f"[debug] {message}")

class VodDownloader:
    def __init__(self, driver: Optional[RemoteWebDriver], console: Console, file_manager: FileManager, step_logger: Optional[StepLogger] = None):
        self.driver = driver
        self.console = console
        self.file_manager = file_manager
        self.step_logger: Optional[StepLogger] = step_logger
        self._http_client, self._http_uses_cloudscraper = self._create_http_client()

    def _build_headers(self, referer: Optional[str] = None) -> dict:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive",
        }
        # Kick/IVS commonly checks Origin/Referer
        headers["Origin"] = "https://kick.com"
        headers["Referer"] = referer or "https://kick.com/"
        return headers

    def _create_http_client(self, force_cloudscraper: bool = False):
        if cloudscraper:
            try:
                scraper = cloudscraper.create_scraper(
                    browser={
                        "browser": "chrome",
                        "platform": "windows",
                        "mobile": False,
                    }
                )
                if Config.DEBUG_HTTP:
                    print("[debug] Initialized cloudscraper HTTP client")
                return scraper, True
            except Exception as e:
                if force_cloudscraper or Config.DEBUG_HTTP:
                    print(f"[yellow]cloudscraper init failed: {e}. Falling back to requests.[/yellow]")
        session = requests.Session()
        if Config.DEBUG_HTTP:
            print("[debug] Using requests.Session for HTTP client")
        return session, False

    def _http_get(self, url: str, headers: Optional[dict] = None, allow_retry: bool = True, **kwargs):
        final_headers = dict(headers) if headers else self._build_headers()
        if "timeout" not in kwargs:
            kwargs["timeout"] = HTTP_TIMEOUT
        client = self._http_client
        try:
            response = client.get(url, headers=final_headers, **kwargs)
        except Exception as e:
            if allow_retry and cloudscraper and not self._http_uses_cloudscraper:
                if Config.DEBUG_HTTP:
                    print(f"[debug] Exception during GET {url}: {e}. Retrying with cloudscraper.")
                self._http_client, self._http_uses_cloudscraper = self._create_http_client(force_cloudscraper=True)
                return self._http_get(url, headers=final_headers, allow_retry=False, **kwargs)
            raise
        if response.status_code == 403 and allow_retry and cloudscraper and not self._http_uses_cloudscraper:
            if Config.DEBUG_HTTP:
                print(f"[debug] HTTP 403 for {url}. Retrying with cloudscraper.")
            self._http_client, self._http_uses_cloudscraper = self._create_http_client(force_cloudscraper=True)
            return self._http_get(url, headers=final_headers, allow_retry=False, **kwargs)
        return response

    def fetch_channel_vod_links(self, channel_name: str) -> List[str]:
        # print(f"\n[cyan]Fetching VOD links for channel:[/cyan] [bold magenta]{channel_name}[/bold magenta]")
        api_url = f"https://kick.com/api/v2/channels/{channel_name}/videos?cursor=0&sort=date&time=all"
        vod_links: List[str] = []

        try:
            # print(f"[cyan]Executing fetch for API URL:[/cyan] {api_url}")
            script = f"return await fetch('{api_url}').then(response => response.json()).catch(e => {{ console.error('Fetch API Error:', e); return {{ error: e.message }}; }});"
            response_data = self.driver.execute_script(script)

            if not response_data:
                print("[yellow]Warning:[/yellow] No VOD found in API response.")
                return []

            if isinstance(response_data, dict) and 'error' in response_data:
                print(f"[bold red]API Fetch Error in Browser:[/bold red] {response_data['error']}")
                self.file_manager.save_debug_info(self.driver, prefix="fetch_vods_api_error", vod_url=channel_name)
                return []

            if not isinstance(response_data, list):
                print(f"[yellow]Warning:[/yellow] Unexpected API response format: {type(response_data)}. Expected a list.")
                print(f"Response received: {str(response_data)[:200]}...")
                if isinstance(response_data, dict) and 'message' in response_data:
                    print(f"[red]API Error Message:[/red] {response_data.get('message')}")
                self.file_manager.save_debug_info(self.driver, prefix="fetch_vods_bad_format", vod_url=channel_name)
                return []

            for video_info in response_data:
                if isinstance(video_info, dict) and 'video' in video_info and isinstance(video_info['video'], dict) and 'uuid' in video_info['video']:
                    video_uuid = video_info['video']['uuid']
                    vod_link = f"https://kick.com/{channel_name}/videos/{video_uuid}"
                    vod_links.append(vod_link)
                else:
                    print(f"[yellow]Warning:[/yellow] Skipping item with unexpected structure: {str(video_info)[:100]}...")

            print(f"[green]Found {len(vod_links)} VOD links for '{channel_name}'.[/green]")
            return vod_links

        except TimeoutException as e:
            print(f"[bold red]Timeout Error executing VOD fetch script:[/bold red] {e}")
            self.file_manager.save_debug_info(self.driver, prefix="fetch_vods_timeout", vod_url=channel_name)
            return []
        except WebDriverException as e:
            print(f"[bold red]WebDriver Error executing API fetch script:[/bold red] {e}")
            print("[yellow]This might happen if the page context changed or the script failed.[/yellow]")
            self.file_manager.save_debug_info(self.driver, prefix="fetch_vods_script_error", vod_url=channel_name)
            return []
        except Exception as e:
            print(f"[bold red]An unexpected error occurred while fetching VOD links:[/bold red] {e}")
            print(traceback.format_exc())
            self.file_manager.save_debug_info(self.driver, prefix="fetch_vods_unexpected_error", vod_url=channel_name)
            return []

    def download_vod_from_m3u8(self, playlist_url: str, output_basename: Optional[str] = None) -> Optional[str]:
        """
        Prototype: Download Kick VOD by fetching the HLS playlist (.m3u8),
        downloading all .ts segments, concatenating to a single .ts, and
        converting to MP3 using ffmpeg.

        Returns the path to the resulting MP3 on success, otherwise None.
        """
        try:
            print(f"[cyan]Fetching playlist:[/cyan] {playlist_url}")
            headers = self._build_headers()
            if Config.DEBUG_HTTP:
                print(f"[debug] GET {playlist_url}\n[debug] headers: {headers}")
            _debug(f"download_vod_from_m3u8: fetching playlist {playlist_url}")
            resp = self._http_get(playlist_url, headers=headers, timeout=HTTP_TIMEOUT)
            if Config.DEBUG_HTTP:
                print(f"[debug] -> HTTP {resp.status_code}")
            if resp.status_code != 200:
                print(f"[bold red]Failed to fetch playlist. HTTP {resp.status_code}[/bold red]")
                _debug(f"download_vod_from_m3u8: playlist HTTP {resp.status_code}")
                return None

            text = resp.text
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            if not lines or not lines[0].startswith('#EXTM3U'):
                print("[bold red]Invalid or empty m3u8 playlist.[/bold red]")
                _debug("download_vod_from_m3u8: invalid playlist content")
                return None

            base_url = playlist_url.rsplit('/', 1)[0]

            segment_urls: List[str] = []
            for line in lines:
                if line.startswith('#'):
                    continue
                # Expect lines like "0.ts", "1.ts", or absolute URLs
                if line.endswith('.ts'):
                    if re.match(r'^https?://', line):
                        segment_urls.append(line)
                    else:
                        segment_urls.append(f"{base_url}/{line}")

            if not segment_urls:
                print("[bold red]No TS segments found in playlist.[/bold red]")
                return None

            # Determine output base name
            if not output_basename:
                # Use last two path parts as a simple identifier
                parsed = urlparse(playlist_url)
                parts = parsed.path.strip('/').split('/')
                ident = '-'.join(parts[-3:]) if len(parts) >= 3 else parts[-1]
                output_basename = ident.replace('.m3u8', '')

            safe_basename = re.sub(r'[^A-Za-z0-9_.\-]+', '_', output_basename)
            work_dir = os.path.join(Config.DOWNLOAD_DIR, safe_basename)
            os.makedirs(work_dir, exist_ok=True)
            _debug(f"download_vod_from_m3u8: work_dir {work_dir}")

            concat_ts_path = os.path.join(work_dir, f"{safe_basename}.ts")
            mp3_output_path = os.path.join(Config.DOWNLOAD_DIR, f"{safe_basename}.mp3")
            _debug(f"download_vod_from_m3u8: concat path {concat_ts_path}")
            _debug(f"download_vod_from_m3u8: output path {mp3_output_path}")

            seg_step_id = None
            if self.step_logger:
                seg_step_id = self.step_logger.start_step(f"Download {len(segment_urls)} segments")
                self.step_logger.set_detail(seg_step_id, f"0/{len(segment_urls)}")
            else:
                print(f"[cyan]Downloading {len(segment_urls)} segments...[/cyan]")

            failed_segments = 0
            with open(concat_ts_path, 'wb') as out_f:
                for idx, seg_url in enumerate(segment_urls):
                    try:
                        if Config.DEBUG_HTTP:
                            print(f"[debug] GET {seg_url}")
                        _debug(f"download_vod_from_m3u8: segment {idx + 1}/{len(segment_urls)} -> {seg_url}")
                        seg_resp = self._http_get(seg_url, headers=headers, timeout=HTTP_TIMEOUT, stream=True)
                        if seg_resp.status_code != 200:
                            failed_segments += 1
                            print(f"[yellow]Segment HTTP {seg_resp.status_code} skipped:[/yellow] {seg_url}")
                            _debug(f"download_vod_from_m3u8: segment HTTP {seg_resp.status_code}")
                            if failed_segments >= SEGMENT_MAX_FAILURES:
                                print(f"[bold red]Too many segment failures ({failed_segments}). Aborting.[/bold red]")
                                return None
                            continue
                        for chunk in seg_resp.iter_content(chunk_size=1024 * 256):
                            if chunk:
                                out_f.write(chunk)
                        if (idx + 1) % 10 == 0 or (idx + 1) == len(segment_urls):
                            if self.step_logger and seg_step_id:
                                self.step_logger.set_detail(seg_step_id, f"{idx + 1}/{len(segment_urls)}")
                            else:
                                print(f"[green]Downloaded {idx + 1}/{len(segment_urls)}[/green]", end='\r')
                    except Exception as e:
                        failed_segments += 1
                        print(f"[yellow]Warning: Error downloading segment {idx}:[/yellow] {e}")
                        _debug(f"download_vod_from_m3u8: segment error {e}")
                        if failed_segments >= SEGMENT_MAX_FAILURES:
                            print(f"[bold red]Too many segment failures ({failed_segments}). Aborting.[/bold red]")
                            if self.step_logger and seg_step_id:
                                self.step_logger.error_step(seg_step_id, detail=f"failed at {idx + 1}/{len(segment_urls)}")
                            return None
            if self.step_logger and seg_step_id:
                self.step_logger.complete_step(seg_step_id, detail=f"{len(segment_urls)}/{len(segment_urls)}")
            else:
                print(f"\n[bold green]All segments downloaded and concatenated.[/bold green]")
            _debug(f"download_vod_from_m3u8: all segments downloaded ({len(segment_urls)})")

            # Convert concatenated TS to MP3 using ffmpeg directly
            if not self.step_logger:
                print("[cyan]Converting concatenated TS to MP3 via ffmpeg...[/cyan]")
            _debug("download_vod_from_m3u8: launching ffmpeg conversion")
            ffmpeg_cmd = [
                'ffmpeg',
                '-hide_banner', '-loglevel', 'error',
                '-y',
                '-i', concat_ts_path,
                '-vn',
                '-acodec', 'libmp3lame',
                '-ab', '128k',
                '-ar', '48000',
                mp3_output_path
            ]
            try:
                process = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
                stdout, stderr = process.communicate()
                if process.returncode != 0:
                    print(f"[bold red]ffmpeg failed ({process.returncode}).[/bold red]")
                    if stderr:
                        print(stderr)
                    _debug(f"download_vod_from_m3u8: ffmpeg failed ({process.returncode}) stderr={stderr}")
                    return None
            except FileNotFoundError:
                print("[bold red]ffmpeg not found. Please install ffmpeg and ensure it is in PATH.[/bold red]")
                _debug("download_vod_from_m3u8: ffmpeg missing")
                return None

            print(f"[bold green]MP3 saved:[/bold green] {mp3_output_path}")
            _debug(f"download_vod_from_m3u8: MP3 saved {mp3_output_path}")
            return mp3_output_path
        except Exception as e:
            print(f"[bold red]Unexpected error in M3U8 download:[/bold red] {e}")
            print(traceback.format_exc())
            _debug(f"download_vod_from_m3u8: exception {e}")
            return None

    def stream_vod_from_m3u8(self, playlist_url: str, output_basename: Optional[str] = None, poll_seconds: int = 60) -> Optional[str]:
        """
        Stream-aware downloader:
        - Downloads all current segments and saves each .ts file individually
        - Polls the playlist every poll_seconds to fetch new segments (for live VODs)
        - When #EXT-X-ENDLIST is seen or on interrupt, concatenates and converts to MP3

        Returns the path to the resulting MP3 on success, otherwise None.
        """
        headers = self._build_headers()
        _debug(f"stream_vod_from_m3u8: start playlist {playlist_url}")

        # Resolve basename/workdir
        if not output_basename:
            parsed = urlparse(playlist_url)
            parts = parsed.path.strip('/').split('/')
            ident = '-'.join(parts[-3:]) if len(parts) >= 3 else parts[-1]
            output_basename = ident.replace('.m3u8', '')
        safe_basename = re.sub(r'[^A-Za-z0-9_.\-]+', '_', output_basename)
        work_dir = os.path.join(Config.DOWNLOAD_DIR, safe_basename)
        segments_dir = os.path.join(work_dir, 'segments')
        os.makedirs(segments_dir, exist_ok=True)

        # Track already downloaded segments (support resuming)
        downloaded_files: Set[str] = set(f for f in os.listdir(segments_dir) if f.endswith('.ts'))
        seg_step_id = None
        if self.step_logger:
            seg_step_id = self.step_logger.start_step("Download segments (streaming)")
            self.step_logger.set_detail(seg_step_id, f"total: {len(downloaded_files)}")
        _debug(f"stream_vod_from_m3u8: existing segments {len(downloaded_files)}")

        def parse_playlist(text: str) -> Tuple[List[Tuple[str, str]], bool]:
            """Return list of (segment_url, local_filename) and whether ENDLIST present."""
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            if not lines or not lines[0].startswith('#EXTM3U'):
                return [], False
            base_url = playlist_url.rsplit('/', 1)[0]
            ended = any('#EXT-X-ENDLIST' in line for line in lines)

            segs: List[Tuple[str, str]] = []
            for line in lines:
                if line.startswith('#'):
                    continue
                if line.endswith('.ts'):
                    full_url = line if re.match(r'^https?://', line) else f"{base_url}/{line}"
                    # Local filename from URL path
                    local_name = os.path.basename(urlparse(full_url).path)
                    if not local_name.endswith('.ts'):
                        local_name = f"{local_name}.ts"
                    segs.append((full_url, local_name))
            return segs, ended

        def download_segment(seg_url: str, local_path: str) -> bool:
            try:
                if Config.DEBUG_HTTP:
                    print(f"[debug] GET {seg_url}")
                r = self._http_get(seg_url, headers=headers, timeout=HTTP_TIMEOUT, stream=True)
                if r.status_code != 200:
                    print(f"[yellow]Segment HTTP {r.status_code} skipped:[/yellow] {seg_url}")
                    return False
                with open(local_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=1024 * 256):
                        if chunk:
                            f.write(chunk)
                _debug(f"stream_vod_from_m3u8: downloaded {local_path}")
                return True
            except Exception as e:
                print(f"[bold red]Error downloading segment:[/bold red] {e}")
                _debug(f"stream_vod_from_m3u8: segment error {e}")
                return False

        def convert_all_segments_to_mp3() -> Optional[str]:
            files = [f for f in os.listdir(segments_dir) if f.endswith('.ts')]
            if not files:
                print("[yellow]No segments to convert.[/yellow]")
                return None
            # Sort by numeric index when available
            def sort_key(name: str):
                m = re.search(r'(\d+)', name)
                return (int(m.group(1)) if m else 10**12, name)
            files.sort(key=sort_key)

            concat_ts_path = os.path.join(work_dir, f"{safe_basename}.ts")
            mp3_output_path = os.path.join(Config.DOWNLOAD_DIR, f"{safe_basename}.mp3")

            try:
                with open(concat_ts_path, 'wb') as out_f:
                    for i, name in enumerate(files):
                        seg_path = os.path.join(segments_dir, name)
                        try:
                            with open(seg_path, 'rb') as seg_f:
                                while True:
                                    chunk = seg_f.read(1024 * 512)
                                    if not chunk:
                                        break
                                    out_f.write(chunk)
                        except Exception as e:
                            print(f"[yellow]Skipping unreadable segment {name}: {e}[/yellow]")
                        if (i + 1) % 50 == 0 or (i + 1) == len(files):
                            print(f"[cyan]Concatenated {i + 1}/{len(files)} segments[/cyan]", end='\r')
            except Exception as e:
                print(f"[bold red]Failed to concatenate segments:[/bold red] {e}")
                _debug(f"stream_vod_from_m3u8: concat error {e}")
                return None
            print("\n[cyan]Converting concatenated TS to MP3 via ffmpeg...[/cyan]")
            _debug(f"stream_vod_from_m3u8: launching ffmpeg for {concat_ts_path}")
            ffmpeg_cmd = [
                'ffmpeg', '-hide_banner', '-loglevel', 'error',
                '-y',
                '-i', concat_ts_path,
                '-vn',
                '-acodec', 'libmp3lame',
                '-ab', '128k',
                '-ar', '48000',
                mp3_output_path
            ]
            try:
                process = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
                stdout, stderr = process.communicate()
                if process.returncode != 0:
                    print(f"[bold red]ffmpeg failed ({process.returncode}).[/bold red]")
                    if stderr:
                        print(stderr)
                    _debug(f"stream_vod_from_m3u8: ffmpeg failed ({process.returncode}) stderr={stderr}")
                    return None
                print(f"[bold green]MP3 saved:[/bold green] {mp3_output_path}")
                _debug(f"stream_vod_from_m3u8: MP3 saved {mp3_output_path}")
                return mp3_output_path
            except FileNotFoundError:
                print("[bold red]ffmpeg not found. Please install ffmpeg and ensure it is in PATH.[/bold red]")
                _debug("stream_vod_from_m3u8: ffmpeg missing")
                return None

        end_reached = False
        last_playlist_segment_count: Optional[int] = None
        try:
            while True:
                try:
                    if Config.DEBUG_HTTP:
                        print(f"[debug] GET {playlist_url}")
                    resp = self._http_get(playlist_url, headers=headers, timeout=HTTP_TIMEOUT)
                    if Config.DEBUG_HTTP:
                        print(f"[debug] -> HTTP {resp.status_code}")
                except Exception as e:
                    print(f"[yellow]Playlist fetch error: {e}. Retrying in {poll_seconds}s...[/yellow]")
                    time.sleep(poll_seconds)
                    continue

                if resp.status_code != 200:
                    print(f"[yellow]Playlist HTTP {resp.status_code}. Retrying in {poll_seconds}s...[/yellow]")
                    time.sleep(poll_seconds)
                    continue

                segs, ended = parse_playlist(resp.text)
                current_playlist_count = len(segs)
                # Determine new segments to fetch
                new_segs = [(u, n) for (u, n) in segs if n not in downloaded_files]
                if new_segs:
                    if not self.step_logger:
                        print(f"[cyan]New segments: {len(new_segs)}[/cyan]")
                for idx, (seg_url, name) in enumerate(new_segs):
                    local_path = os.path.join(segments_dir, name)
                    ok = download_segment(seg_url, local_path)
                    if ok:
                        downloaded_files.add(name)
                    if (idx + 1) % 10 == 0 or (idx + 1) == len(new_segs):
                        if self.step_logger and seg_step_id:
                            total = len(downloaded_files)
                            self.step_logger.set_detail(seg_step_id, f"total: {total} (batch {idx + 1}/{len(new_segs)})")
                        else:
                            print(f"[green]Downloaded {idx + 1}/{len(new_segs)} new segments[/green]", end='\r')

                # Ignore ENDLIST, it's unreliable on Kick playlists

                # New rule: if no increase in playlist segment count across polls, treat as ended
                if last_playlist_segment_count is not None:
                    if current_playlist_count <= last_playlist_segment_count:
                        if self.step_logger and seg_step_id:
                            self.step_logger.complete_step(seg_step_id, detail=f"total: {len(downloaded_files)}")
                        print("\n[bold green]No new segments in latest poll. Assuming stream ended. Converting...[/bold green]")
                        end_reached = True
                        break
                last_playlist_segment_count = current_playlist_count

                # No end yet: wait and poll again
                time.sleep(poll_seconds)

        except KeyboardInterrupt:
            if self.step_logger and seg_step_id:
                self.step_logger.complete_step(seg_step_id, detail=f"total: {len(downloaded_files)}")
            print("\n[bold yellow]Interrupted by user. Finalizing and converting...[/bold yellow]")
        except Exception as e:
            print(f"[bold red]Unexpected streaming error:[/bold red] {e}")
            print(traceback.format_exc())
            _debug(f"stream_vod_from_m3u8: exception {e}")
        # Always attempt conversion if we have segments
        return convert_all_segments_to_mp3()

    def get_live_m3u8_for_channel(self, channel_name: str, preferred_variant: Optional[str] = None) -> Optional[str]:
        """
        Query Kick API for a channel's current livestream using the browser (to avoid CF),
        and try to resolve an HLS variant playlist URL (.m3u8). If a master playlist is
        returned, attempt to pick the preferred variant (e.g. '480p30').

        Returns the resolved .m3u8 URL or None if not live/unavailable.
        """
        # Prefer browser-based fetch to bypass CF, mirroring live_checkpoint_recorder
        if self.driver:
            url = self._resolve_m3u8_via_browser(channel_name, preferred_variant)
            if url:
                return url
        # As a last resort (if driver not available), attempt page scrape via requests
        print("[yellow]Browser resolution failed or unavailable. Trying page scrape...[/yellow]")
        url = self._resolve_m3u8_from_channel_page(channel_name, preferred_variant, self._build_headers(referer=f"https://kick.com/{channel_name}"))
        return url

    def _resolve_m3u8_from_channel_page(self, channel_name: str, preferred_variant: Optional[str], headers: Optional[dict] = None) -> Optional[str]:
        """
        Fallback: fetch https://kick.com/<channel> and look for any m3u8 URL in the HTML/embedded JSON.
        """
        page_url = f"https://kick.com/{channel_name}"
        html = None
        # Use browser first to avoid CF
        if self.driver:
            try:
                self.driver.get(page_url)
                time.sleep(2)
                html = self.driver.page_source
            except Exception as e:
                html = None
        if html is None:
            try:
                if Config.DEBUG_HTTP:
                    print(f"[debug] GET {page_url}")
                r = self._http_get(page_url, headers=headers or {"User-Agent": "Mozilla/5.0"}, timeout=PLAYLIST_TIMEOUT)
                if Config.DEBUG_HTTP:
                    print(f"[debug] -> HTTP {r.status_code}")
                if r.status_code == 200:
                    html = r.text
            except Exception as e:
                html = None
        if not html:
            print(f"[yellow]Could not load channel page HTML for '{channel_name}'.[/yellow]")
            return None
        # Look for any .m3u8 URLs
        m3u8_matches = re.findall(r'https?://[^"\']+\.m3u8', html)
        if not m3u8_matches:
            print("[yellow]No m3u8 found in channel page HTML.[/yellow]")
            return None
        # Prefer ones hosted on stream.kick.com when available
        preferred_host_matches = [u for u in m3u8_matches if 'stream.kick.com' in u]
        candidate = preferred_host_matches[0] if preferred_host_matches else m3u8_matches[0]
        return self._pick_variant_from_master(candidate, preferred_variant)

    def _resolve_m3u8_via_browser(self, channel_name: str, preferred_variant: Optional[str]) -> Optional[str]:
        """
        Use Selenium browser (if available) to fetch the channel API via window.fetch,
        then extract an m3u8 from the JSON (bypassing 403 from raw requests).
        """
        if not self.driver:
            return None
        try:
            target_url = f"https://kick.com/{channel_name}"
            try:
                self.driver.get(target_url)
                time.sleep(2)
            except Exception:
                pass

            api_url = f"https://kick.com/api/v2/channels/{channel_name}"
            script = f'''
                return await fetch('{api_url}', {{ credentials: 'include' }})
                  .then(r => r.ok ? r.json() : {{ status: r.status, error: 'HTTP ' + r.status }})
                  .catch(e => ({{ error: e && e.message ? e.message : 'fetch error' }}));
            '''
            data = self.driver.execute_script(script)
            if not data or (isinstance(data, dict) and data.get('error')):
                # Try to read any m3u8 from the current DOM as last resort
                page_html = self.driver.page_source or ''
                m3u8_matches = re.findall(r'https?://[^"\']+\.m3u8', page_html)
                if m3u8_matches:
                    preferred = [u for u in m3u8_matches if 'stream.kick.com' in u]
                    candidate = preferred[0] if preferred else m3u8_matches[0]
                    return self._pick_variant_from_master(candidate, preferred_variant)
                return None

            livestream = data.get('livestream') if isinstance(data, dict) else None
            if not livestream:
                return None

            m3u8_urls: List[str] = []
            def collect_urls(obj):
                if isinstance(obj, dict):
                    for v in obj.values():
                        collect_urls(v)
                elif isinstance(obj, list):
                    for v in obj:
                        collect_urls(v)
                elif isinstance(obj, str):
                    if re.match(r'^https?://.+\.m3u8$', obj):
                        m3u8_urls.append(obj)
            collect_urls(livestream)

            if not m3u8_urls:
                return None
            if preferred_variant:
                for u in m3u8_urls:
                    if preferred_variant in u:
                        return u
            candidate = m3u8_urls[0]
            return self._pick_variant_from_master(candidate, preferred_variant)
        except Exception:
            return None

    def get_latest_vod_link(self, channel_name: str) -> Optional[str]:
        """Return the most recent VOD page URL for a channel."""
        try:
            if self.driver:
                vod_links = self.fetch_channel_vod_links(channel_name)
                if vod_links:
                    return vod_links[0]
            # Fallback via requests
            api_url = f"https://kick.com/api/v2/channels/{channel_name}/videos?cursor=0&sort=date&time=all"
            headers = self._build_headers(referer=f"https://kick.com/{channel_name}")
            resp = self._http_get(api_url, headers=headers, timeout=PLAYLIST_TIMEOUT)
            if resp.status_code != 200:
                return None
            data = resp.json()
            if not isinstance(data, list) or not data:
                return None
            for video_info in data:
                if isinstance(video_info, dict) and 'video' in video_info and isinstance(video_info['video'], dict) and 'uuid' in video_info['video']:
                    video_uuid = video_info['video']['uuid']
                    return f"https://kick.com/{channel_name}/videos/{video_uuid}"
            return None
        except Exception:
            return None

    def _resolve_m3u8_from_vod_page(self, vod_page_url: str, preferred_variant: Optional[str]) -> Optional[str]:
        """Fetch the VOD page and try to find any .m3u8, then pick variant. Use browser first to avoid CF."""
        html = None
        if self.driver:
            try:
                self.driver.get(vod_page_url)
                time.sleep(2)
                html = self.driver.page_source
            except Exception:
                html = None
        if not html:
            headers = self._build_headers(referer=vod_page_url)
            try:
                if Config.DEBUG_HTTP:
                    print(f"[debug] GET {vod_page_url}")
                    print(f"[debug] headers: {headers}")
                r = self._http_get(vod_page_url, headers=headers, timeout=PAGE_TIMEOUT)
                if Config.DEBUG_HTTP:
                    print(f"[debug] -> HTTP {r.status_code}")
                if r.status_code == 200:
                    html = r.text
            except Exception:
                html = None
        if not html:
            print("[yellow]Could not load VOD page HTML.[/yellow]")
            return None

        m3u8_matches = re.findall(r'https?://[^"\']+\.m3u8', html)
        if not m3u8_matches:
            return None
        # Prefer stream.kick.com host
        preferred_hosts = [u for u in m3u8_matches if 'stream.kick.com' in u]
        candidate = preferred_hosts[0] if preferred_hosts else m3u8_matches[0]
        if preferred_variant:
            for u in m3u8_matches:
                if preferred_variant in u:
                    candidate = u
                    break
        return self._pick_variant_from_master(candidate, preferred_variant)

    def get_latest_vod_m3u8_for_channel(self, channel_name: str, preferred_variant: Optional[str] = None, require_live: bool = False) -> Optional[str]:
        """
        Resolve the latest VOD page for the channel and return a variant .m3u8 URL.
        If require_live is True, first check liveness and continue only if live.
        """
        try:
            if require_live and not self.is_channel_live(channel_name):
                print(f"[yellow]Channel '{channel_name}' is not live.[/yellow]")
                return None
        except Exception:
            pass

        vod_url = self.get_latest_vod_link(channel_name)
        if not vod_url:
            print(f"[yellow]No VODs found for '{channel_name}'.[/yellow]")
            return None
        print(f"[cyan]Latest VOD URL:[/cyan] {vod_url}")
        return self._resolve_m3u8_from_vod_page(vod_url, preferred_variant)

    def _pick_variant_from_master(self, playlist_url: str, preferred_variant: Optional[str]) -> Optional[str]:
        """If playlist_url is a master playlist, try to select a variant based on preference or bandwidth."""
        headers = {"User-Agent": "Mozilla/5.0"}
        try:
            if Config.DEBUG_HTTP:
                print(f"[debug] GET {playlist_url}")
            resp = self._http_get(playlist_url, headers=headers, timeout=PLAYLIST_TIMEOUT)
            if Config.DEBUG_HTTP:
                print(f"[debug] -> HTTP {resp.status_code}")
        except Exception:
            return playlist_url
        if resp.status_code != 200:
            return playlist_url
        text = resp.text
        if '#EXT-X-STREAM-INF' not in text:
            # Not a master playlist
            return playlist_url

        base_url = playlist_url.rsplit('/', 1)[0]
        # Parse master variants: (#EXT-X-STREAM-INF ... next line is the uri)
        variants: List[Tuple[Optional[int], str]] = []
        lines = [line.strip() for line in text.splitlines()]
        i = 0
        while i < len(lines):
            line = lines[i]
            if line.startswith('#EXT-X-STREAM-INF'):
                bandwidth = None
                m = re.search(r'BANDWIDTH=(\d+)', line)
                if m:
                    try:
                        bandwidth = int(m.group(1))
                    except Exception:
                        bandwidth = None
                # Next non-empty, non-comment line is the URL
                j = i + 1
                while j < len(lines) and (not lines[j] or lines[j].startswith('#')):
                    j += 1
                if j < len(lines):
                    uri = lines[j]
                    if not re.match(r'^https?://', uri):
                        uri = f"{base_url}/{uri}"
                    variants.append((bandwidth, uri))
                    i = j
            i += 1

        if not variants:
            return playlist_url

        # Preferred substring match first
        if preferred_variant:
            for _, uri in variants:
                if preferred_variant in uri:
                    return uri

        # Otherwise pick highest bandwidth available
        variants.sort(key=lambda t: (t[0] or 0), reverse=True)
        return variants[0][1]

    def _parse_uuid_from_vod_url(self, vod_url: str) -> Optional[str]:
        try:
            parts = vod_url.rstrip('/').split('/')
            return parts[-1] if parts else None
        except Exception:
            return None

    def get_video_master_m3u8_by_uuid(self, video_uuid: str) -> Optional[str]:
        """Use browser JS fetch to query Kick v1 video API and return 'source' (master m3u8)."""
        if not video_uuid:
            return None
        api_url = f"https://kick.com/api/v1/video/{video_uuid}"
        if not self.driver:
            # Fallback to requests (may be blocked by CF)
            try:
                headers = self._build_headers(referer=f"https://kick.com/video/{video_uuid}")
                if Config.DEBUG_HTTP:
                    print(f"[debug] GET {api_url}\n[debug] headers: {headers}")
                r = self._http_get(api_url, headers=headers, timeout=PLAYLIST_TIMEOUT)
                if Config.DEBUG_HTTP:
                    print(f"[debug] -> HTTP {r.status_code}")
                if r.status_code != 200:
                    return None
                data = r.json()
                return data.get('source')
            except Exception:
                return None
        # Use Selenium to bypass CF
        try:
            script = f"""
                return await fetch('{api_url}', {{ credentials: 'include' }})
                  .then(r => r.ok ? r.json() : null)
                  .catch(_ => null);
            """
            data = self.driver.execute_script(script)
            if Config.DEBUG_HTTP:
                print(f"[debug] JS fetch {api_url} -> {'ok' if data else 'null'}")
            if isinstance(data, dict) and data.get('source'):
                return data['source']
            return None
        except Exception:
            return None

    def get_video_metadata_by_uuid(self, video_uuid: str) -> Optional[dict]:
        """Return full JSON from v1 video API using browser (credentials) when possible."""
        if not video_uuid:
            return None
        api_url = f"https://kick.com/api/v1/video/{video_uuid}"
        if self.driver:
            try:
                script = f"""
                    return await fetch('{api_url}', {{ credentials: 'include' }})
                      .then(r => r.ok ? r.json() : null)
                      .catch(_ => null);
                """
                data = self.driver.execute_script(script)
                if Config.DEBUG_HTTP:
                    print(f"[debug] JS fetch {api_url} -> {'ok' if data else 'null'}")
                if isinstance(data, dict):
                    return data
            except Exception:
                return None
        # Fallback to requests (may be blocked)
        try:
            headers = self._build_headers(referer=f"https://kick.com/video/{video_uuid}")
            if Config.DEBUG_HTTP:
                print(f"[debug] GET {api_url}\n[debug] headers: {headers}")
            r = self._http_get(api_url, headers=headers, timeout=PLAYLIST_TIMEOUT)
            if Config.DEBUG_HTTP:
                print(f"[debug] -> HTTP {r.status_code}")
            if r.status_code != 200:
                return None
            return r.json()
        except Exception:
            return None

    def build_suggested_basename(self, channel_name: str, video_data: Optional[dict], preferred_variant: Optional[str]) -> str:
        """Build a descriptive basename like 'channel_YYYY-MM-DD_HH-mm_480p'."""
        date_str = None
        if isinstance(video_data, dict):
            ts = video_data.get('created_at')
            if not ts and isinstance(video_data.get('livestream'), dict):
                ts = video_data['livestream'].get('start_time')
            if isinstance(ts, str):
                try:
                    iso = ts.replace('Z', '+00:00')
                    dt = datetime.datetime.fromisoformat(iso)
                    date_str = dt.strftime('%Y-%m-%d_%H-%M')
                except Exception:
                    pass
        if not date_str:
            try:
                date_str = datetime.datetime.utcnow().strftime('%Y-%m-%d_%H-%M')
            except Exception:
                date_str = 'unknown-date'

        variant_label = None
        if preferred_variant:
            m = re.match(r'^(\d+p)', str(preferred_variant))
            if m:
                variant_label = m.group(1)
            else:
                variant_label = str(preferred_variant)
        else:
            variant_label = '480p'

        raw = f"{channel_name}_{date_str}_{variant_label}"
        return re.sub(r'[^A-Za-z0-9_.\-]+', '_', raw)

    def _derive_variant_from_master_url(self, master_url: str, preferred_variant: Optional[str]) -> Optional[str]:
        """If master fetch fails, try building variant URL from known IVS path pattern."""
        if not master_url:
            return None
        if preferred_variant and '/media/hls/master.m3u8' in master_url:
            return master_url.replace('/media/hls/master.m3u8', f'/media/hls/{preferred_variant}/playlist.m3u8')
        if preferred_variant and master_url.endswith('master.m3u8'):
            base = master_url.rsplit('/', 1)[0]
            return f"{base}/{preferred_variant}/playlist.m3u8"
        return master_url

    def get_latest_vod_variant_m3u8(self, channel_name: str, preferred_variant: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
        """
        Required workflow (no live playback URL):
        1) Retrieve VOD links (newest first)
        2) Extract UUID from newest VOD URL
        3) Call v1 video API via browser to get master.m3u8 (source)
        4) Derive variant playlist URL: /media/hls/<variant>/playlist.m3u8

        Returns (variant_playlist_url, vod_page_url). Either may be None on failure.
        """
        if not preferred_variant:
            preferred_variant = '480p30'
        vod_url = self.get_latest_vod_link(channel_name)
        if not vod_url:
            print(f"[yellow]No VOD found for '{channel_name}'.[/yellow]")
            return None, None
        uuid = self._parse_uuid_from_vod_url(vod_url)
        if not uuid:
            print(f"[yellow]Could not parse UUID from VOD URL: {vod_url}[/yellow]")
            return None, vod_url
        master = self.get_video_master_m3u8_by_uuid(uuid)
        if not master:
            print("[yellow]Could not fetch master.m3u8 from v1 video API.[/yellow]")
            return None, vod_url
        variant = self._derive_variant_from_master_url(master, preferred_variant)
        if Config.DEBUG_HTTP:
            print(f"[debug] master: {master}\n[debug] variant: {variant}")
        return variant, vod_url


    def is_channel_live(self, channel_name: str) -> bool:
        api_url = f"https://kick.com/api/v2/channels/{channel_name}"
        # Make the JS robust against fetch errors and non-JSON responses
        script = f'''
            return await fetch('{api_url}')
                .then(response => {{
                    if (!response.ok) {{
                        // console.warn(`Liveness check HTTP error for {channel_name}: ${{response.status}}`);
                        return {{ error: `HTTP error! status: ${{response.status}}`, is_live: false, from_script: true }};
                    }}
                    return response.json();
                }})
                .then(data => {{
                    if (data && typeof data.livestream !== 'undefined' && data.livestream !== null) {{
                        return {{ is_live: true, from_script: true }}; // data.livestream could contain more info if needed
                    }}
                    return {{ is_live: false, from_script: true }}; // No livestream object or it's null
                }})
                .catch(e => {{
                    // console.error('Liveness check fetch API Error in script for {channel_name}:', e);
                    return {{ error: e.message, is_live: false, from_script: true }};
                }});
        '''
        try:
            response_data = self.driver.execute_script(script)

            if isinstance(response_data, dict) and response_data.get('from_script'):
                if 'error' in response_data and response_data['error']:
                    # Optional: log detailed error if needed, but console spam should be avoided here
                    # self.console.print(f"[yellow]API error during liveness check for '{channel_name}': {response_data['error']}[/yellow]")
                    pass
                return bool(response_data.get('is_live', False))
            else:
                # self.console.print(f"[yellow]Liveness check for '{channel_name}': Unexpected script response format.[/yellow]")
                # self.file_manager.save_debug_info(self.driver, prefix="liveness_check_bad_response", vod_url=channel_name)
                return False # Safer to assume not live

        except WebDriverException as e:
            # self.console.print(f"[red]WebDriver Error during liveness check for {channel_name}: {e}[/red]")
            # self.file_manager.save_debug_info(self.driver, prefix="liveness_webdriver_error", vod_url=channel_name)
            return False # Treat as not live or error state
        except Exception as e: # Catch any other unexpected errors
            # self.console.print(f"[red]Unexpected error during liveness check for {channel_name}: {e}[/red]")
            # print(traceback.format_exc()) # For debugging, if necessary
            # self.file_manager.save_debug_info(self.driver, prefix="liveness_unexpected_error", vod_url=channel_name)
            return False
