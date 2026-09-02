from __future__ import annotations

import hashlib
import json
import math
import typing as ty
from collections.abc import Mapping
from numbers import Integral, Real

from pydra2app.core import __version__
from pydra2app.core.exceptions import Pydra2AppBuildError

MAX_CANONICAL_SPEC_NODES = 100_000
MAX_CANONICAL_SPEC_DEPTH = 100


class SpecCanonicalizationError(Pydra2AppBuildError):
    """Raised when a specification cannot be canonicalized safely."""


class _TraversalState:
    def __init__(self) -> None:
        self.nodes = 0
        self.active_containers: ty.Set[int] = set()


def canonical_spec(
    spec: ty.Any, *, check_versions: bool = False
) -> ty.Dict[str, ty.Any]:
    """Return a deterministic representation of an image specification."""
    source = spec if isinstance(spec, Mapping) else spec.asdict()
    normalized = {
        key: value
        for key, value in source.items()
        if not key.startswith("_") and (value or isinstance(value, bool))
    }
    if check_versions:
        normalized.setdefault("pydra2app_version", __version__)
    else:
        normalized.pop("pydra2app_version", None)
        normalized.pop("version", None)
    normalized.pop("type", None)
    normalized.pop("access_token", None)
    return ty.cast(
        ty.Dict[str, ty.Any],
        _canonicalize(normalized, state=_TraversalState()),
    )


def canonical_spec_json(spec: ty.Any, *, check_versions: bool = False) -> str:
    """Serialize an image specification in canonical JSON form."""
    return json.dumps(
        canonical_spec(spec, check_versions=check_versions),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def spec_sha256(spec: ty.Any) -> str:
    """Calculate the release-content checksum for an image specification."""
    return hashlib.sha256(canonical_spec_json(spec).encode("utf-8")).hexdigest()


def _canonicalize(
    value: ty.Any,
    path: ty.Tuple[str, ...] = (),
    *,
    state: _TraversalState,
    depth: int = 0,
) -> ty.Any:
    state.nodes += 1
    if state.nodes > MAX_CANONICAL_SPEC_NODES:
        raise SpecCanonicalizationError(
            "Specification is too large to canonicalize safely "
            f"(more than {MAX_CANONICAL_SPEC_NODES} traversed nodes)"
        )
    if depth > MAX_CANONICAL_SPEC_DEPTH:
        raise SpecCanonicalizationError(
            "Specification is too deeply nested to canonicalize safely "
            f"(more than {MAX_CANONICAL_SPEC_DEPTH} levels)"
        )

    is_container = isinstance(value, (Mapping, list, tuple, set, frozenset))
    container_id = id(value)
    if is_container:
        if container_id in state.active_containers:
            raise SpecCanonicalizationError(
                "Specification contains a cyclic YAML alias"
            )
        state.active_containers.add(container_id)

    try:
        if isinstance(value, Mapping):
            return {
                key: _canonicalize(
                    item,
                    path + (key,),
                    state=state,
                    depth=depth + 1,
                )
                for key, item in sorted(value.items(), key=lambda pair: pair[0])
                if not (
                    (path[:1] == ("licenses",) and key == "source")
                    or (path[:2] == ("packages", "pip") and key == "file_path")
                )
            }
        if isinstance(value, (list, tuple, set, frozenset)):
            items = [
                _canonicalize(item, path, state=state, depth=depth + 1)
                for item in value
            ]
            items_by_json = {
                json.dumps(
                    item, ensure_ascii=True, separators=(",", ":"), sort_keys=True
                ): item
                for item in items
            }
            return [items_by_json[key] for key in sorted(items_by_json)]
        if not isinstance(value, bool):
            if isinstance(value, Integral):
                return int(value)
            if isinstance(value, Real):
                number = float(value)
                return (
                    int(number)
                    if math.isfinite(number) and number.is_integer()
                    else number
                )
        return value
    finally:
        if is_container:
            state.active_containers.remove(container_id)
