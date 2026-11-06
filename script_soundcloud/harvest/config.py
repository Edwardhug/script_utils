from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"


@dataclass
class SlskdConfig:
    url: str = "http://localhost:5030"
    api_key: str = ""
    wait_timeout_s: int = 900


@dataclass
class PathsConfig:
    data_dir: str = "data"
    downloads_dir: str = "data/slskd/downloads"
    staging_dir: str = "data/staging"
    music_dir: str = "/mnt/e/Music/dj"
    reports_dir: str = "reports"
    cache_dir: str = "data/cache/soundcloud"


@dataclass
class QualityConfig:
    preferred_ext: list = field(default_factory=lambda: ["flac", "wav", "mp3"])
    min_mp3_bitrate: int = 320
    duration_tolerance_s: float = 4.0


@dataclass
class SearchConfig:
    wait_timeout_s: int = 35
    max_candidates_kept: int = 10
    min_candidate_score: float = 25.0
    interval_s: float = 3.0


@dataclass
class DownloadConfig:
    poll_interval_s: int = 10
    track_timeout_s: int = 1800
    max_candidate_tries: int = 3
    max_active: int = 4


@dataclass
class OrganizeConfig:
    filename_template: str = "{artist} - {title} [{quality}]"
    unknown_genre_folder: str = "_À classer"
    genre_map: dict = field(default_factory=dict)


@dataclass
class SoundcloudConfig:
    likes_url: str = ""
    delay_s: float = 1.2


@dataclass
class Config:
    slskd: SlskdConfig = field(default_factory=SlskdConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)
    quality: QualityConfig = field(default_factory=QualityConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    download: DownloadConfig = field(default_factory=DownloadConfig)
    organize: OrganizeConfig = field(default_factory=OrganizeConfig)
    soundcloud: SoundcloudConfig = field(default_factory=SoundcloudConfig)
    root: Path = field(default_factory=lambda: PROJECT_ROOT)

    # ------------------------------------------------------------------ paths
    def resolve(self, value: str) -> Path:
        p = Path(value).expanduser()
        return p if p.is_absolute() else (self.root / p)

    @property
    def db_path(self) -> Path:
        return self.resolve(self.paths.data_dir) / "harvest.db"

    @property
    def downloads_dir(self) -> Path:
        return self.resolve(self.paths.downloads_dir)

    @property
    def staging_dir(self) -> Path:
        return self.resolve(self.paths.staging_dir)

    @property
    def music_dir(self) -> Path:
        return self.resolve(self.paths.music_dir)

    @property
    def reports_dir(self) -> Path:
        return self.resolve(self.paths.reports_dir)

    @property
    def cache_dir(self) -> Path:
        return self.resolve(self.paths.cache_dir)

    def ensure_dirs(self) -> None:
        for path in (
            self.resolve(self.paths.data_dir),
            self.downloads_dir,
            self.staging_dir,
            self.music_dir,
            self.reports_dir,
            self.cache_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> Config:
    cfg_path = Path(path)
    if not cfg_path.exists():
        raise FileNotFoundError(
            f"Configuration introuvable : {cfg_path}\n"
            "Copie config.example.yaml vers config.yaml et remplis les valeurs."
        )
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    config = Config(root=cfg_path.resolve().parent)

    slskd = raw.get("slskd") or {}
    config.slskd = SlskdConfig(
        url=str(slskd.get("url") or config.slskd.url).rstrip("/"),
        api_key=str(slskd.get("api_key") or ""),
        wait_timeout_s=int(slskd.get("wait_timeout_s") or config.slskd.wait_timeout_s),
    )

    paths = raw.get("paths") or {}
    config.paths = PathsConfig(
        data_dir=str(paths.get("data_dir") or config.paths.data_dir),
        downloads_dir=str(paths.get("downloads_dir") or config.paths.downloads_dir),
        staging_dir=str(paths.get("staging_dir") or config.paths.staging_dir),
        music_dir=str(paths.get("music_dir") or config.paths.music_dir),
        reports_dir=str(paths.get("reports_dir") or config.paths.reports_dir),
        cache_dir=str(paths.get("cache_dir") or config.paths.cache_dir),
    )

    quality = raw.get("quality") or {}
    config.quality = QualityConfig(
        preferred_ext=list(quality.get("preferred_ext") or config.quality.preferred_ext),
        min_mp3_bitrate=int(quality.get("min_mp3_bitrate") or config.quality.min_mp3_bitrate),
        duration_tolerance_s=float(
            quality.get("duration_tolerance_s") or config.quality.duration_tolerance_s
        ),
    )

    search = raw.get("search") or {}
    config.search = SearchConfig(
        wait_timeout_s=int(search.get("wait_timeout_s") or config.search.wait_timeout_s),
        max_candidates_kept=int(
            search.get("max_candidates_kept") or config.search.max_candidates_kept
        ),
        min_candidate_score=float(
            search.get("min_candidate_score") or config.search.min_candidate_score
        ),
        interval_s=float(search.get("interval_s") or config.search.interval_s),
    )

    download = raw.get("download") or {}
    config.download = DownloadConfig(
        poll_interval_s=int(download.get("poll_interval_s") or config.download.poll_interval_s),
        track_timeout_s=int(download.get("track_timeout_s") or config.download.track_timeout_s),
        max_candidate_tries=int(
            download.get("max_candidate_tries") or config.download.max_candidate_tries
        ),
        max_active=int(download.get("max_active") or config.download.max_active),
    )

    organize = raw.get("organize") or {}
    config.organize = OrganizeConfig(
        filename_template=str(
            organize.get("filename_template") or config.organize.filename_template
        ),
        unknown_genre_folder=str(
            organize.get("unknown_genre_folder") or config.organize.unknown_genre_folder
        ),
        genre_map=dict(organize.get("genre_map") or config.organize.genre_map),
    )

    soundcloud = raw.get("soundcloud") or {}
    config.soundcloud = SoundcloudConfig(
        likes_url=str(soundcloud.get("likes_url") or ""),
        delay_s=float(soundcloud.get("delay_s") or config.soundcloud.delay_s),
    )

    return config
