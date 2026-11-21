"""Social / username enumeration engine.

Checks a username against a curated set of public profile URLs and reports
the ones that exist. A profile is reported only when the URL returns HTTP 200
*and* the body does not contain a known "not found" marker, which keeps false
positives down. Only plausible single-token handles are probed - a display
name (e.g. "Fei-Fei Li") is reported as a gap instead. This is a lightweight,
dependency-free alternative to heavier tooling.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from ..logger import logger
from ..models.report import Finding
from .base import BaseEngine

# platform -> URL template containing {username}
PLATFORMS: dict[str, str] = {
    "github": "https://github.com/{username}",
    "twitter": "https://twitter.com/{username}",
    "instagram": "https://www.instagram.com/{username}/",
    "reddit": "https://www.reddit.com/user/{username}",
    "medium": "https://medium.com/@{username}",
    "dev.to": "https://dev.to/{username}",
    "keybase": "https://keybase.io/{username}",
    "pinterest": "https://www.pinterest.com/{username}/",
    "tiktok": "https://www.tiktok.com/@{username}",
    "youtube": "https://www.youtube.com/@{username}",
    "telegram": "https://t.me/{username}",
    "gitlab": "https://gitlab.com/{username}",
    "bitbucket": "https://bitbucket.org/{username}/",
    "npm": "https://www.npmjs.com/~{username}",
    "pypi": "https://pypi.org/user/{username}/",
    "hackernews": "https://news.ycombinator.com/user?id={username}",
    "soundcloud": "https://soundcloud.com/{username}",
    "spotify": "https://open.spotify.com/user/{username}",
    "twitch": "https://www.twitch.tv/{username}",
    "steam": "https://steamcommunity.com/id/{username}",
}

# A username is a single-token handle, not a display name. Probing every
# platform with a name like "Fei-Fei Li" (which contains a space) would 200
# on almost all of them, so the target is validated first.
_USERNAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,38})$")

# Body substrings that indicate a non-existent profile despite HTTP 200
# (platform "soft 404" pages that still answer 200).
NOT_FOUND_MARKERS: dict[str, tuple[str, ...]] = {
    "github": ("page not found",),
    "twitter": ("this account doesn",),
    "instagram": ("page not found", "sorry, this page"),
    "reddit": ("page not found", "sorry, nobody on reddit"),
    "medium": ("page not found",),
    "dev.to": ("page not found",),
    "keybase": ("page not found",),
    "pinterest": ("page not found",),
    "tiktok": ("couldn't find this account", "page not available"),
    "youtube": ("this page isn", "this channel does not exist"),
    "telegram": (),
    "gitlab": ("page not found",),
    "bitbucket": ("page not found",),
    "npm": ("page not found",),
    "pypi": ("not found",),
    "hackernews": ("no such user",),
    "soundcloud": ("we can't find that user", "page not found"),
    "spotify": ("page not found",),
    "twitch": ("page not found",),
    "steam": ("the specified profile could not be found",),
}


def _is_username(value: str) -> bool:
    """True when *value* looks like a single-token platform handle."""
    return bool(_USERNAME_RE.match(value))


class SocialEngine(BaseEngine):
    name = "social"
    category = "identity"

    def _check(self, platform: str, template: str, username: str) -> Finding | None:
        url = template.format(username=username)
        try:
            resp = self.session.get(
                url, timeout=self.settings.http.timeout, allow_redirects=True
            )
        except Exception:  # noqa: BLE001
            return None
        if resp.status_code != 200:
            return None
        # A 200 is not proof of existence: many platforms answer 200 with a
        # soft-404 / "user not found" page. Reject those before reporting.
        body = (resp.text or "").lower()
        for marker in NOT_FOUND_MARKERS.get(platform, ()):
            if marker.lower() in body:
                return None
        return self.finding(
            title=f"{platform}: @{username}",
            url=url, confidence=0.7,
            platform=platform, username=username,
            status_code=resp.status_code,
        )

    def run(self, target: str, *, max_workers: int = 10, **kwargs: Any) -> list[Finding]:
        username = target.strip().lstrip("@")
        if not username:
            return []
        if not _is_username(username):
            # A name like "Fei-Fei Li" is not a handle; probing every platform
            # would 200 on almost all of them. Report the gap instead.
            logger.info("[social] '{}' is not a username; skipping", username)
            return [self.finding(
                title=f"'{username}' is not a username",
                detail="Pass a single-token handle (letters, digits, . _ -); "
                       "a display name cannot be enumerated across platforms.",
                confidence=0.3, status="skipped",
            )]
        findings: list[Finding] = []
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(self._check, platform, tmpl, username): platform
                for platform, tmpl in PLATFORMS.items()
            }
            for future in as_completed(futures):
                result = future.result()
                if result:
                    findings.append(result)
        logger.info("[social] {} profiles found for @{}", len(findings), username)
        return findings


__all__ = ["SocialEngine", "PLATFORMS", "NOT_FOUND_MARKERS"]
