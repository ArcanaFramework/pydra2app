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


def test_ghcr_registry_tags_fails_safely_on_ambiguous_404(
    image_spec: ty.Dict[str, ty.Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "pydra2app.core.image.base.requests.get",
        Mock(return_value=Mock(status_code=404)),
    )
    app = App(
        registry=GITHUB_CONTAINER_REGISTRY,
        access_token="token",
        **image_spec,
    )

    with pytest.raises(Pydra2AppBuildError, match="does not exist or"):
        app.registry_tags()


def test_latest_published_ignores_non_version_tags(
    image_spec: ty.Dict[str, ty.Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    app = App(**image_spec)
    monkeypatch.setattr(
        App, "registry_tags", Mock(return_value=["1.0.0", "latest"])
    )

    assert app.latest_published == Version.parse("1.0.0")
