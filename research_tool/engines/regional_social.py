"""Regional social-media / username enumeration engine.

The default :class:`~research_tool.engines.social.SocialEngine` covers the
anglophone/global platforms. This companion engine probes platforms that
dominate *outside* that sphere - Russia/CIS, China and East Asia - so a
subject's footprint can be found where it actually lives:

  * **Russia / CIS** - VK, Odnoklassniki, Dzen, Rutube
  * **China** - Weibo, Zhihu, Bilibili, Douyin, QZone
  * **Korea / Japan** - Naver Blog, Tistory, Kakao Story, LINE

As with ``social``, a profile is reported when the URL returns HTTP 200
*and* the body does not contain a known "not found" marker, and only a
plausible single-token handle is probed (a display name is reported as a
gap). Everything degrades gracefully on network errors.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from ..logger import logger
from ..models.report import Finding
from .base import BaseEngine

# A username is a single-token handle, not a display name. Probing every
# platform with a name like "Fei-Fei Li" (which contains a space) would 200
# on almost all of them, so the target is validated first.
_USERNAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,38})$")

# platform key -> (display name, region, URL template containing {username})
REGIONAL_PLATFORMS: dict[str, tuple[str, str, str]] = {
    "vk": ("VKontakte", "ru", "https://vk.com/{username}"),
    "ok": ("Odnoklassniki", "ru", "https://ok.ru/{username}"),
    "dzen": ("Dzen", "ru", "https://dzen.ru/{username}"),
    "rutube": ("Rutube", "ru", "https://rutube.ru/channel/{username}/"),
    "weibo": ("Weibo", "cn", "https://weibo.com/{username}"),
    "zhihu": ("Zhihu", "cn", "https://www.zhihu.com/people/{username}"),
    "bilibili": ("Bilibili", "cn", "https://space.bilibili.com/{username}"),
    "douyin": ("Douyin", "cn", "https://www.douyin.com/user/{username}"),
    "qzone": ("QZone", "cn", "https://user.qzone.qq.com/{username}"),
    "naver_blog": ("Naver Blog", "kr", "https://blog.naver.com/{username}"),
    "tistory": ("Tistory", "kr", "https://{username}.tistory.com"),
    "kakao_story": ("Kakao Story", "kr", "https://story.kakao.com/{username}"),
    "line": ("LINE", "jp", "https://line.me/ti/p/~{username}"),
}

# Body substrings that indicate a non-existent profile despite HTTP 200.
NOT_FOUND_MARKERS: dict[str, tuple[str, ...]] = {
    "vk": ("page not found", "страница не найдена"),
    "ok": ("не найдена", "not found"),
    "weibo": ("抱歉，此用户不存在", "用户不存在"),
    "zhihu": ("你似乎来到了没有知识存在的荒原",),
    "bilibili": ("用户不存在", "找不到"),
    "douyin": ("用户不存在",),
    "naver_blog": ("페이지를 찾을 수 없습니다",),
    "tistory": ("존재하지 않는", "not found"),
    "kakao_story": ("존재하지 않는",),
}


class RegionalSocialEngine(BaseEngine):
    """Enumerate usernames across regional social platforms."""

    name = "regional_social"
    category = "identity"

    def _check(self, key: str, display: str, region: str, template: str,
               username: str) -> Finding | None:
        url = template.format(username=username)
        try:
            resp = self.session.get(
                url, timeout=self.settings.http.timeout, allow_redirects=True,
            )
        except Exception:  # noqa: BLE001 - network errors vary by platform
            return None
        if resp.status_code != 200:
            return None
        body = (resp.text or "").lower()
        for marker in NOT_FOUND_MARKERS.get(key, ()):
            if marker.lower() in body:
                return None
        return self.finding(
            title=f"{display}: @{username}",
            url=url, confidence=0.6,
            platform=key, platform_name=display, region=region,
            username=username, status_code=resp.status_code,
        )

    def run(self, target: str, *, max_workers: int = 10,
            **kwargs: Any) -> list[Finding]:
        username = target.strip().lstrip("@")
        if not username:
            return []
        if not _USERNAME_RE.match(username):
            # A display name (e.g. "Fei-Fei Li") is not a handle; probing every
            # platform would 200 on almost all of them. Report the gap instead.
            logger.info("[regional_social] '{}' is not a username; skipping",
                        username)
            return [self.finding(
                title=f"'{username}' is not a username",
                detail="Pass a single-token handle (letters, digits, . _ -); "
                       "a display name cannot be enumerated across platforms.",
                confidence=0.3, status="skipped",
            )]
        findings: list[Finding] = []
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(self._check, key, display, region, template, username):
                    key
                for key, (display, region, template) in REGIONAL_PLATFORMS.items()
            }
            for future in as_completed(futures):
                try:
                    result = future.result()
                except Exception:  # noqa: BLE001
                    result = None
                if result:
                    findings.append(result)
        logger.info("[regional_social] {} profiles found for @{}",
                    len(findings), username)
        return findings


__all__ = ["RegionalSocialEngine", "REGIONAL_PLATFORMS", "NOT_FOUND_MARKERS"]
