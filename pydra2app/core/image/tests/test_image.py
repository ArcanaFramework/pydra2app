import typing as ty
from pathlib import Path
import random
from unittest.mock import Mock
import docker.errors
import os
import logging
from copy import copy
from traceback import format_exc
from pydra2app.core.exceptions import Pydra2AppBuildError
from pydra2app.core.image import App
from pydra2app.core.image.components import Version
from pydra2app.core.oci import (
    OCIIntegrityError,
    OCIImageMetadata,
    OCIRegistryError,
    SpecLayerResult,
    SpecLayerStatus,
)
from pydra2app.core.spec import spec_sha256
from pydra2app.core.utils import DOCKER_HUB, GITHUB_CONTAINER_REGISTRY
import pytest

logger = logging.getLogger("pydra2app")

VERSIONS = [
    "1.0-alpha0",
    "1.0-alpha2",
    "1.0-beta0",
    "1.0.0",
    "1.0-post1",
    "1.0-post2",
    "1.1-alpha0",
    "1.2.0",
    "1.11.0",
    "1.12.1-rc1",
]


@pytest.fixture
def image_spec(command_spec: ty.Dict[str, ty.Any]) -> ty.Dict[str, ty.Any]:
    return {
        "org": "australian-imaging-service",
        "name": "test-pipeline",
        "version": "1.0.0",
        "title": "A pipeline to test pydra2app's deployment tool",
        "commands": {"concatenate-test": command_spec},
        "authors": [{"name": "Thomas G. Close", "email": "thomas.close@sydney.edu.au"}],
        "docs": {
            "info_url": "http://concatenate.readthefakedocs.io",
        },
        "readme": "This is a test pipeline",
        "packages": {
            "system": ["vim", "git"],
        },
    }


REQUIRED_ENVVARS = ("GHCR_USERNAME", "GHCR_TOKEN", "DOCKER_USERNAME", "DOCKER_TOKEN")

REGISTRIES = [GITHUB_CONTAINER_REGISTRY, DOCKER_HUB, "localhost"]


@pytest.fixture(params=REGISTRIES)
def docker_registry(request: pytest.FixtureRequest, local_docker_registry: str) -> str:
    return request.param if request.param != "localhost" else local_docker_registry


@pytest.fixture
def image_tags(
    image_spec: dict[str, ty.Any], docker_registry: str, tmp_path: Path
) -> ty.List[str]:

    registry_prefix = docker_registry.split(".")[0].upper()
    username = os.environ.get(f"{registry_prefix}_USERNAME")
    token = os.environ.get(f"{registry_prefix}_TOKEN")

    dc = docker.from_env()

    if username is not None and token is not None:
        response = dc.login(username=username, password=token, registry=docker_registry)
        if response["Status"] != "Login Succeeded":
            logger.warning("Could not login to '%s':\n\n%s", docker_registry, response)

    pushed = []

    for version in VERSIONS:
        build_dir = tmp_path / f"build-{version}"

        image_spec_cpy = copy(image_spec)

        image_spec_cpy["version"] = version
        if docker_registry == DOCKER_HUB:
            image_spec_cpy["org"] = "australianimagingservice"

        image = App(registry=docker_registry, **image_spec_cpy)

        try:
            dc.api.pull(image.reference)
        except (docker.errors.APIError, docker.errors.NotFound) as e:
            if e.response is not None and e.response.status_code in (404, 500):
                image.make(build_dir=build_dir)
                try:
                    dc.api.push(image.reference)
                except Exception:
                    pytest.skip(
                        f"Could not push '{image.reference}':\n\n{format_exc()}"
                    )
            else:
                raise
        pushed.append(image.tag)

    return sorted(pushed)


def test_sort_versions() -> None:

    rng = random.Random(42)

    shuffled = copy(VERSIONS)
    rng.shuffle(shuffled)

    sorted_versions = sorted(Version.parse(v) for v in shuffled)

    assert sorted_versions == [Version.parse(v) for v in VERSIONS]
    assert [str(v) for v in sorted_versions] == VERSIONS


UNKNOWN_VERSIONS = ["1.0.0-unknown0", "1.0.0-alpha0junk"]


@pytest.mark.parametrize("version", UNKNOWN_VERSIONS)
def test_bad_version(version):
    Version.parse(version).release = version


def test_registry_tags(
    image_tags: ty.List[str],
    tmp_path: Path,
    docker_registry: str,
    image_spec: ty.Dict[str, ty.Any],
) -> None:
    if docker_registry == "ghcr.io":
        pytest.skip("No login credentials for GitHub Container Registry")

    image_spec_cpy = copy(image_spec)
    if docker_registry == DOCKER_HUB:
        image_spec_cpy["org"] = "australianimagingservice"

    app = App(registry=docker_registry, **image_spec_cpy)
    assert sorted(app.registry_tags()) == sorted(image_tags)


def test_ghcr_registry_tags_ignores_untagged_and_paginates(
    image_spec: ty.Dict[str, ty.Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    first_response = Mock(
        status_code=200,
        links={"next": {"url": "https://api.github.com/next-page"}},
    )
    first_response.json.return_value = [
        {"metadata": {"container": {"tags": []}}},
        {"metadata": {"container": {"tags": ["1.0.0", "latest"]}}},
    ]
    second_response = Mock(status_code=200, links={})
    second_response.json.return_value = [
        {"metadata": {"container": {"tags": ["1.1.0"]}}},
    ]
    get = Mock(side_effect=[first_response, second_response])
    monkeypatch.setattr("pydra2app.core.image.base.requests.get", get)
    app = App(
        registry=GITHUB_CONTAINER_REGISTRY,
        access_token="token",
        **image_spec,
    )

    assert app.registry_tags() == ["1.0.0", "latest", "1.1.0"]
    assert get.call_args_list[0].kwargs["params"] == {"per_page": 100}
    assert get.call_args_list[1].kwargs["params"] is None


def test_ghcr_registry_tags_supports_anonymous_public_access(
    image_spec: ty.Dict[str, ty.Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    registry_response = Mock(status_code=200, links={})
    registry_response.json.return_value = [
        {"metadata": {"container": {"tags": ["1.0.0"]}}},
    ]
    get = Mock(return_value=registry_response)
    monkeypatch.setattr("pydra2app.core.image.base.requests.get", get)
    app = App(registry=GITHUB_CONTAINER_REGISTRY, **image_spec)

    assert app.registry_tags() == ["1.0.0"]
    assert "Authorization" not in get.call_args.kwargs["headers"]


def test_ghcr_registry_tags_returns_empty_when_oci_confirms_package_absent(
    image_spec: ty.Dict[str, ty.Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "pydra2app.core.image.base.requests.get",
        Mock(return_value=Mock(status_code=404)),
    )
    client = Mock()
    client.registry_tags.return_value = []
    client_cls = Mock(return_value=client)
    monkeypatch.setattr("pydra2app.core.image.base.OCIRegistryClient", client_cls)
    app = App(
        registry=GITHUB_CONTAINER_REGISTRY,
        access_token="token",
        **image_spec,
    )

    assert app.registry_tags() == []
    client_cls.assert_called_once_with(app.reference, access_token="token")


def test_ghcr_registry_tags_surfaces_oci_access_denial(
    image_spec: ty.Dict[str, ty.Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "pydra2app.core.image.base.requests.get",
        Mock(return_value=Mock(status_code=404)),
    )
    client = Mock()
    client.registry_tags.side_effect = OCIRegistryError(
        "OCI registry 'ghcr.io' denied access"
    )
    monkeypatch.setattr(
        "pydra2app.core.image.base.OCIRegistryClient", Mock(return_value=client)
    )
    app = App(
        registry=GITHUB_CONTAINER_REGISTRY,
        access_token="token",
        **image_spec,
    )

    with pytest.raises(Pydra2AppBuildError, match="denied access"):
        app.registry_tags()


@pytest.mark.parametrize(
    ("registry", "scheme"),
    [
        ("localhost:5000", "http"),
        ("127.0.0.1:5000", "http"),
        ("[::1]:5000", "http"),
        ("localhost.attacker.example", "https"),
    ],
)
def test_registry_tags_only_uses_http_for_exact_loopback_hosts(
    image_spec: ty.Dict[str, ty.Any],
    monkeypatch: pytest.MonkeyPatch,
    registry: str,
    scheme: str,
) -> None:
    response = Mock(status_code=200)
    response.json.return_value = {"tags": []}
    get = Mock(return_value=response)
    monkeypatch.setattr("pydra2app.core.image.base.requests.get", get)
    app = App(registry=registry, **image_spec)

    assert app.registry_tags() == []
    assert get.call_args.args[0].startswith(f"{scheme}://{registry}/")


def test_latest_published_ignores_non_version_tags(
    image_spec: ty.Dict[str, ty.Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    app = App(**image_spec)
    monkeypatch.setattr(App, "registry_tags", Mock(return_value=["1.0.0", "latest"]))

    assert app.latest_published == Version.parse("1.0.0")


def test_generated_dockerfile_has_spec_checksum_and_custom_labels(
    image_spec: ty.Dict[str, ty.Any], tmp_path: Path
) -> None:
    app = App(labels={"org.example.custom": "custom-value"}, **image_spec)

    dockerfile = app.construct_dockerfile(tmp_path)

    rendered = dockerfile.render()
    assert f'{app.SPEC_CHECKSUM_LABEL}="{spec_sha256(app)}"' in rendered
    assert 'org.example.custom="custom-value"' in rendered


def test_access_token_is_not_serialized_or_hashed(
    image_spec: ty.Dict[str, ty.Any],
) -> None:
    without_token = App(**image_spec)
    with_token = App(access_token="secret-token", **image_spec)

    assert "access_token" not in with_token.asdict()
    assert spec_sha256(with_token) == spec_sha256(without_token)


@pytest.mark.parametrize("matches", [True, False])
def test_matches_image_uses_checksum_without_full_pull(
    image_spec: ty.Dict[str, ty.Any],
    monkeypatch: pytest.MonkeyPatch,
    matches: bool,
) -> None:
    app = App(**image_spec)
    checksum = spec_sha256(app) if matches else "0" * 64
    client = Mock()
    client.image_metadata.return_value = OCIImageMetadata(
        config={"config": {"Labels": {app.SPEC_CHECKSUM_LABEL: checksum}}},
        layers=[],
    )
    client_cls = Mock(return_value=client)
    full_pull = Mock()
    monkeypatch.setattr("pydra2app.core.image.base.OCIRegistryClient", client_cls)
    monkeypatch.setattr(
        "pydra2app.core.image.base.extract_file_from_docker_image", full_pull
    )

    assert app.matches_image("registry.example/org/image:1.0") is matches
    client.spec_from_small_layers.assert_not_called()
    full_pull.assert_not_called()


def test_matches_image_uses_targeted_layer_for_legacy_image(
    image_spec: ty.Dict[str, ty.Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    app = App(**image_spec)
    published_spec = app.asdict()
    published_spec["version"] = "0.9"
    client = Mock()
    client.image_metadata.return_value = OCIImageMetadata(
        config={"config": {"Labels": {}}},
        layers=[{"digest": "sha256:spec", "size": 1000}],
    )
    client.spec_from_small_layers.return_value = SpecLayerResult(
        SpecLayerStatus.FOUND, published_spec
    )
    full_pull = Mock()
    monkeypatch.setattr(
        "pydra2app.core.image.base.OCIRegistryClient", Mock(return_value=client)
    )
    monkeypatch.setattr(
        "pydra2app.core.image.base.extract_file_from_docker_image", full_pull
    )

    assert app.matches_image("registry.example/org/image:1.0")
    client.spec_from_small_layers.assert_called_once()
    full_pull.assert_not_called()


def test_matches_image_targeted_layer_accepts_saved_legacy_spec(
    image_spec: ty.Dict[str, ty.Any],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    app = App(**image_spec)
    saved_spec = tmp_path / "saved.yaml"
    app.save(saved_spec)
    client = Mock()
    client.image_metadata.return_value = OCIImageMetadata(
        config={"config": {"Labels": {}}},
        layers=[{"digest": "sha256:spec", "size": 1000}],
    )
    client.spec_from_small_layers.return_value = SpecLayerResult(
        SpecLayerStatus.FOUND, App._load_yaml(saved_spec)
    )
    full_pull = Mock()
    monkeypatch.setattr(
        "pydra2app.core.image.base.OCIRegistryClient", Mock(return_value=client)
    )
    monkeypatch.setattr(
        "pydra2app.core.image.base.extract_file_from_docker_image", full_pull
    )

    assert app.matches_image("registry.example/org/image:1.0")
    full_pull.assert_not_called()


def test_matches_image_full_pull_only_when_lightweight_comparison_is_inconclusive(
    image_spec: ty.Dict[str, ty.Any],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    app = App(**image_spec)
    client = Mock()
    client.image_metadata.return_value = OCIImageMetadata(
        config={"config": {}},
        layers=[{"digest": "sha256:large", "size": 10_000_000}],
    )
    client.spec_from_small_layers.return_value = SpecLayerResult(
        SpecLayerStatus.INCONCLUSIVE
    )
    extracted_spec = tmp_path / "pydra2app-spec.yaml"
    extracted_spec.touch()
    full_pull = Mock(return_value=extracted_spec)
    monkeypatch.setattr(
        "pydra2app.core.image.base.OCIRegistryClient", Mock(return_value=client)
    )
    monkeypatch.setattr(
        "pydra2app.core.image.base.extract_file_from_docker_image", full_pull
    )
    monkeypatch.setattr(App, "_load_yaml", Mock(return_value=app.asdict()))

    assert app.matches_image("registry.example/org/image:1.0")
    full_pull.assert_called_once()


def test_matches_image_returns_different_when_fallback_spec_is_missing(
    image_spec: ty.Dict[str, ty.Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    app = App(**image_spec)
    client = Mock()
    client.image_metadata.return_value = OCIImageMetadata(
        config={"config": {}},
        layers=[],
    )
    client.spec_from_small_layers.return_value = SpecLayerResult(
        SpecLayerStatus.INCONCLUSIVE
    )
    full_pull = Mock(return_value=None)
    monkeypatch.setattr(
        "pydra2app.core.image.base.OCIRegistryClient", Mock(return_value=client)
    )
    monkeypatch.setattr(
        "pydra2app.core.image.base.extract_file_from_docker_image", full_pull
    )

    assert not app.matches_image("registry.example/org/image:1.0")


def test_matches_image_does_not_pull_when_targeted_spec_is_absent(
    image_spec: ty.Dict[str, ty.Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    app = App(**image_spec)
    client = Mock()
    client.image_metadata.return_value = OCIImageMetadata(
        config={"config": {}},
        layers=[],
    )
    client.spec_from_small_layers.return_value = SpecLayerResult(SpecLayerStatus.ABSENT)
    full_pull = Mock()
    monkeypatch.setattr(
        "pydra2app.core.image.base.OCIRegistryClient", Mock(return_value=client)
    )
    monkeypatch.setattr(
        "pydra2app.core.image.base.extract_file_from_docker_image", full_pull
    )

    assert not app.matches_image("registry.example/org/image:1.0")
    full_pull.assert_not_called()


def test_matches_image_falls_back_when_oci_inspection_is_unsupported(
    image_spec: ty.Dict[str, ty.Any],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    app = App(**image_spec)
    client = Mock()
    client.image_metadata.side_effect = OCIRegistryError("unsupported authentication")
    extracted_spec = tmp_path / "pydra2app-spec.yaml"
    extracted_spec.touch()
    full_pull = Mock(return_value=extracted_spec)
    monkeypatch.setattr(
        "pydra2app.core.image.base.OCIRegistryClient", Mock(return_value=client)
    )
    monkeypatch.setattr(
        "pydra2app.core.image.base.extract_file_from_docker_image", full_pull
    )
    monkeypatch.setattr(App, "_load_yaml", Mock(return_value=app.asdict()))

    assert app.matches_image("registry.example/org/image:1.0")
    full_pull.assert_called_once()


def test_matches_image_surfaces_oci_integrity_failure_without_pull(
    image_spec: ty.Dict[str, ty.Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    app = App(**image_spec)
    client = Mock()
    client.image_metadata.side_effect = OCIIntegrityError("digest mismatch")
    full_pull = Mock()
    monkeypatch.setattr(
        "pydra2app.core.image.base.OCIRegistryClient", Mock(return_value=client)
    )
    monkeypatch.setattr(
        "pydra2app.core.image.base.extract_file_from_docker_image", full_pull
    )

    with pytest.raises(OCIIntegrityError, match="digest mismatch"):
        app.matches_image("registry.example/org/image:1.0")
    full_pull.assert_not_called()
