from copy import deepcopy

import pytest
import yaml

import pydra2app.core.spec as spec_module
from pydra2app.core.spec import (
    SpecCanonicalizationError,
    canonical_spec_json,
    spec_sha256,
)


def test_canonical_spec_checksum_is_deterministic() -> None:
    first = {
        "name": "example",
        "packages": {"system": ["git", "curl"], "pip": {"pydra": None}},
        "enabled": False,
    }
    second = {
        "enabled": False,
        "packages": {"pip": {"pydra": None}, "system": ["git", "curl"]},
        "name": "example",
    }

    assert canonical_spec_json(first) == canonical_spec_json(second)
    assert spec_sha256(first) == spec_sha256(second)


def test_release_checksum_ignores_version_fields() -> None:
    first = {
        "name": "example",
        "version": "1.0",
        "pydra2app_version": "0.20",
    }
    second = {
        "name": "example",
        "version": "2.0",
        "pydra2app_version": "0.21",
    }

    assert spec_sha256(first) == spec_sha256(second)


def test_release_checksum_ignores_legacy_serialized_access_token() -> None:
    first = {"name": "example", "access_token": "first-token"}
    second = {"name": "example", "access_token": "second-token"}

    assert spec_sha256(first) == spec_sha256(second)


def test_release_checksum_ignores_build_host_paths() -> None:
    first = {
        "name": "example",
        "licenses": [{"name": "tool", "source": "/runner-a/license"}],
        "packages": {"pip": [{"name": "package", "file_path": "/runner-a/package"}]},
    }
    second = {
        "name": "example",
        "licenses": [{"name": "tool", "source": "/runner-b/license"}],
        "packages": {"pip": [{"name": "package", "file_path": "/runner-b/package"}]},
    }

    assert spec_sha256(first) == spec_sha256(second)


def test_release_checksum_changes_with_meaningful_content() -> None:
    first = {"name": "example", "packages": {"system": ["git"]}}
    second = deepcopy(first)
    second["packages"]["system"].append("curl")

    assert spec_sha256(first) != spec_sha256(second)


def test_release_checksum_ignores_nested_sequence_order() -> None:
    first = {
        "name": "example",
        "commands": [
            {"name": "default", "inputs": ["first", "second"]},
            {"name": "alternative"},
        ],
    }
    second = {
        "name": "example",
        "commands": [
            {"name": "alternative"},
            {"name": "default", "inputs": ["second", "first"]},
        ],
    }

    assert spec_sha256(first) == spec_sha256(second)


def test_release_checksum_ignores_repeated_collection_values() -> None:
    first = {"name": "example", "packages": {"system": ["git", "git"]}}
    second = {"name": "example", "packages": {"system": ["git"]}}

    assert spec_sha256(first) == spec_sha256(second)


def test_release_checksum_normalizes_equivalent_numeric_values() -> None:
    integer = {"name": "example", "value": 1, "enabled": True}
    floating_point = {"name": "example", "value": 1.0, "enabled": True}

    assert spec_sha256(integer) == spec_sha256(floating_point)
    assert spec_sha256({"value": True}) != spec_sha256({"value": 1})


def test_release_checksum_rejects_cyclic_yaml_alias() -> None:
    spec = yaml.safe_load("""
name: example
commands: &commands
  - *commands
""")

    with pytest.raises(SpecCanonicalizationError, match="cyclic YAML alias"):
        spec_sha256(spec)


def test_release_checksum_limits_repeated_yaml_alias_traversal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = yaml.safe_load("""
name: example
dependency: &dependency
  name: shared
dependencies:
  - *dependency
  - *dependency
  - *dependency
""")
    monkeypatch.setattr(spec_module, "MAX_CANONICAL_SPEC_NODES", 8)

    with pytest.raises(SpecCanonicalizationError, match="too large"):
        spec_sha256(spec)
