from __future__ import annotations

import typing as ty
from dataclasses import dataclass
from enum import Enum

from pydra2app.core.image import App
from pydra2app.core.image.components import Version


class ReleaseStatus(str, Enum):
    BUILD = "build"
    UNCHANGED = "unchanged"
    INVALID = "invalid"


@dataclass(frozen=True)
class ReleaseDecision:
    status: ReleaseStatus
    app: App
    published_version: ty.Optional[Version] = None
    reason: ty.Optional[str] = None


def plan_release(app: App) -> ReleaseDecision:
    """Determine whether an app spec requires a new image build."""
    published_version = app.latest_published
    if published_version is None or app.version > published_version:
        return ReleaseDecision(
            status=ReleaseStatus.BUILD,
            app=app,
            published_version=published_version,
        )

    if app.version < published_version:
        return ReleaseDecision(
            status=ReleaseStatus.INVALID,
            app=app,
            published_version=published_version,
            reason=(
                f"Version decreased for '{app.name}': spec version {app.version} is "
                f"older than published version {published_version}"
            ),
        )

    published_reference = f"{app.path}:{published_version}"
    if app.matches_image(published_reference):
        return ReleaseDecision(
            status=ReleaseStatus.UNCHANGED,
            app=app,
            published_version=published_version,
        )

    return ReleaseDecision(
        status=ReleaseStatus.INVALID,
        app=app,
        published_version=published_version,
        reason=(
            f"Spec changed for '{app.name}' without a version increment: "
            f"{app.version} is already published"
        ),
    )
