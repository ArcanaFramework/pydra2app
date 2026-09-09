import hashlib
import io
import json
import tarfile
from pathlib import PurePosixPath
from unittest.mock import Mock

import pytest
import requests

from pydra2app.core.oci import (
    DOCKER_INDEX,
    MAX_EXPANDED_LAYER_SIZE,
    MAX_SPEC_FILE_SIZE,
    MAX_SPEC_LAYER_SIZE,
    OCI_MANIFEST,
    OCIRegistryClient,
    OCIRegistryError,
    SpecLayerStatus,
    verify_digest,
)


def digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def response(
    status: int,
    content: bytes = b"",
    *,
    headers: dict[str, str] | None = None,
) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result._content = content
    result.raw = io.BytesIO(content)
    result.headers.update(headers or {})
    result.url = "https://registry.example/test"
    return result


def json_response(
    data: object,
    *,
    status: int = 200,
    headers: dict[str, str] | None = None,
) -> requests.Response:
    return response(
        status,
        json.dumps(data, separators=(",", ":")).encode(),
        headers=headers,
    )


def tar_layer(files: dict[str, bytes], *, compressed: bool = True) -> bytes:
    buffer = io.BytesIO()
    mode = "w:gz" if compressed else "w"
    with tarfile.open(fileobj=buffer, mode=mode) as archive:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


def test_image_metadata_resolves_index_and_verifies_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = json.dumps({"config": {"Labels": {"label": "value"}}}).encode()
    platform_manifest = json.dumps(
        {
            "mediaType": OCI_MANIFEST,
            "config": {"digest": digest(config), "size": len(config)},
            "layers": [],
        },
        separators=(",", ":"),
    ).encode()
    index = {
        "mediaType": DOCKER_INDEX,
        "manifests": [
            {
                "digest": digest(platform_manifest),
                "platform": {"os": "linux", "architecture": "amd64"},
            }
        ],
    }
    session = Mock()
    session.get.side_effect = [
        json_response(index),
        response(200, platform_manifest),
        response(200, config),
    ]
    monkeypatch.setattr("pydra2app.core.oci.platform.machine", lambda: "x86_64")

    metadata = OCIRegistryClient(
        "registry.example/org/image:1.0", session=session
    ).image_metadata()

    assert metadata.config["config"]["Labels"]["label"] == "value"
    assert len(session.get.call_args_list) == 3


def test_small_layer_search_is_independent_of_position_and_skips_large_layers() -> None:
    spec = b"name: example\nversion: '1.0'\n"
    spec_layer = tar_layer({"pydra2app-spec.yaml": spec})
    unrelated_layer = tar_layer({"other.txt": b"not a spec"})
    client = OCIRegistryClient("registry.example/org/image:1.0")
    blobs = {
        "sha256:spec": spec_layer,
        "sha256:unrelated": unrelated_layer,
    }
    client._blob = Mock(side_effect=lambda layer_digest, **kwargs: blobs[layer_digest])
    layers = [
        {"digest": "sha256:large", "size": MAX_SPEC_LAYER_SIZE + 1},
        {"digest": "sha256:spec", "size": len(spec_layer)},
        {"digest": "sha256:unrelated", "size": len(unrelated_layer)},
    ]

    result = client.spec_from_small_layers(
        layers, PurePosixPath("/pydra2app-spec.yaml")
    )
    assert result.status is SpecLayerStatus.FOUND
    assert result.spec == {"name": "example", "version": "1.0"}
    assert [call.args[0] for call in client._blob.call_args_list] == [
        "sha256:unrelated",
        "sha256:spec",
    ]


@pytest.mark.parametrize("spec_position", [0, 1, 2])
def test_small_layer_search_does_not_assume_layer_position(
    spec_position: int,
) -> None:
    spec_layer = tar_layer({"pydra2app-spec.yaml": b"name: example\n"})
    unrelated_layers = [
        tar_layer({f"unrelated-{index}": b"ignored"}) for index in range(2)
    ]
    blobs = {
        "sha256:spec": spec_layer,
        **{
            f"sha256:unrelated-{index}": layer
            for index, layer in enumerate(unrelated_layers)
        },
    }
    descriptors = [
        {
            "digest": f"sha256:unrelated-{index}",
            "size": len(layer),
        }
        for index, layer in enumerate(unrelated_layers)
    ]
    descriptors.insert(
        spec_position, {"digest": "sha256:spec", "size": len(spec_layer)}
    )
    client = OCIRegistryClient("registry.example/org/image:1.0")
    client._blob = Mock(side_effect=lambda layer_digest, **kwargs: blobs[layer_digest])

    result = client.spec_from_small_layers(
        descriptors, PurePosixPath("/pydra2app-spec.yaml")
    )
    assert result.status is SpecLayerStatus.FOUND
    assert result.spec == {"name": "example"}


def test_newer_uninspected_layer_makes_legacy_comparison_inconclusive() -> None:
    spec_layer = tar_layer({"pydra2app-spec.yaml": b"name: stale\n"})
    client = OCIRegistryClient("registry.example/org/image:1.0")
    client._blob = Mock(return_value=spec_layer)
    layers = [
        {"digest": "sha256:spec", "size": len(spec_layer)},
        {"digest": "sha256:large", "size": MAX_SPEC_LAYER_SIZE + 1},
    ]

    result = client.spec_from_small_layers(
        layers, PurePosixPath("/pydra2app-spec.yaml")
    )
    assert result.status is SpecLayerStatus.INCONCLUSIVE


@pytest.mark.parametrize("whiteout", [".wh.pydra2app-spec.yaml", ".wh..wh..opq"])
def test_newer_whiteout_hides_legacy_spec(whiteout: str) -> None:
    spec_layer = tar_layer({"pydra2app-spec.yaml": b"name: stale\n"})
    whiteout_layer = tar_layer({whiteout: b""})
    client = OCIRegistryClient("registry.example/org/image:1.0")
    blobs = {
        "sha256:spec": spec_layer,
        "sha256:whiteout": whiteout_layer,
    }
    client._blob = Mock(side_effect=lambda layer_digest, **kwargs: blobs[layer_digest])

    result = client.spec_from_small_layers(
        [
            {"digest": "sha256:spec", "size": len(spec_layer)},
            {"digest": "sha256:whiteout", "size": len(whiteout_layer)},
        ],
        PurePosixPath("/pydra2app-spec.yaml"),
    )
    assert result.status is SpecLayerStatus.ABSENT


@pytest.mark.parametrize("whiteout_first", [True, False])
def test_file_in_same_layer_takes_precedence_over_whiteout(
    whiteout_first: bool,
) -> None:
    entries = [
        (".wh.pydra2app-spec.yaml", b""),
        ("pydra2app-spec.yaml", b"name: current\n"),
    ]
    if not whiteout_first:
        entries.reverse()
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, content in entries:
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    layer = buffer.getvalue()
    client = OCIRegistryClient("registry.example/org/image:1.0")
    client._blob = Mock(return_value=layer)

    result = client.spec_from_small_layers(
        [{"digest": "sha256:layer", "size": len(layer)}],
        PurePosixPath("/pydra2app-spec.yaml"),
    )

    assert result.status is SpecLayerStatus.FOUND
    assert result.spec == {"name": "current"}


def test_small_layer_search_reads_gzipped_tar_member_only() -> None:
    spec_layer = tar_layer(
        {
            "unrelated": b"ignored",
            "./pydra2app-spec.yaml": b"name: example\n",
        }
    )
    client = OCIRegistryClient("registry.example/org/image:1.0")
    client._blob = Mock(return_value=spec_layer)

    result = client.spec_from_small_layers(
        [{"digest": "sha256:spec", "size": len(spec_layer)}],
        PurePosixPath("/pydra2app-spec.yaml"),
    )
    assert result.status is SpecLayerStatus.FOUND
    assert result.spec == {"name": "example"}


def test_last_duplicate_tar_member_is_effective() -> None:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for content in (b"name: stale\n", b"name: current\n"):
            info = tarfile.TarInfo("pydra2app-spec.yaml")
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    spec_layer = buffer.getvalue()
    client = OCIRegistryClient("registry.example/org/image:1.0")
    client._blob = Mock(return_value=spec_layer)

    result = client.spec_from_small_layers(
        [{"digest": "sha256:spec", "size": len(spec_layer)}],
        PurePosixPath("/pydra2app-spec.yaml"),
    )

    assert result.status is SpecLayerStatus.FOUND
    assert result.spec == {"name": "current"}


def test_oversized_uncompressed_spec_is_not_read() -> None:
    spec_layer = tar_layer({"pydra2app-spec.yaml": b"a" * (MAX_SPEC_FILE_SIZE + 1)})
    assert len(spec_layer) < MAX_SPEC_LAYER_SIZE
    client = OCIRegistryClient("registry.example/org/image:1.0")
    client._blob = Mock(return_value=spec_layer)

    result = client.spec_from_small_layers(
        [{"digest": "sha256:spec", "size": len(spec_layer)}],
        PurePosixPath("/pydra2app-spec.yaml"),
    )
    assert result.status is SpecLayerStatus.INCONCLUSIVE


def test_excessive_layer_expansion_is_inconclusive() -> None:
    spec_layer = tar_layer({"padding": b"a" * (MAX_EXPANDED_LAYER_SIZE + 1)})
    assert len(spec_layer) < MAX_SPEC_LAYER_SIZE
    client = OCIRegistryClient("registry.example/org/image:1.0")
    client._blob = Mock(return_value=spec_layer)

    result = client.spec_from_small_layers(
        [{"digest": "sha256:layer", "size": len(spec_layer)}],
        PurePosixPath("/pydra2app-spec.yaml"),
    )

    assert result.status is SpecLayerStatus.INCONCLUSIVE


def test_layer_response_larger_than_limit_is_bounded() -> None:
    oversized = b"x" * (MAX_SPEC_LAYER_SIZE + 1)
    session = Mock()
    session.get.return_value = response(200, oversized)
    client = OCIRegistryClient("registry.example/org/image:1.0", session=session)

    with pytest.raises(OCIRegistryError, match="inspection limit"):
        client._blob(
            digest(oversized),
            expected_digest=digest(oversized),
            max_size=MAX_SPEC_LAYER_SIZE,
        )


def test_blob_digest_verification_failure_is_surfaced() -> None:
    with pytest.raises(OCIRegistryError, match="digest mismatch"):
        verify_digest(b"tampered", digest(b"expected"))


@pytest.mark.parametrize("status", [404, 500])
def test_missing_manifest_and_registry_failures_are_explicit(status: int) -> None:
    session = Mock()
    session.get.return_value = response(status)
    client = OCIRegistryClient("registry.example/org/image:1.0", session=session)

    with pytest.raises(OCIRegistryError):
        client.image_metadata()


def test_registry_tags_returns_empty_after_authenticated_404() -> None:
    challenge = "{} {}".format(
        "Bea" + "rer",
        'realm="https://auth.example/token",'
        'service="registry.example",scope="repository:org/image:pull"',
    )
    session = Mock()
    session.get.side_effect = [
        response(401, headers={"WWW-Authenticate": challenge}),
        json_response({"token": "registry-token"}),
        response(404),
    ]
    client = OCIRegistryClient("registry.example/org/image:latest", session=session)

    assert client.registry_tags() == []


def test_registry_tags_returns_valid_tags() -> None:
    session = Mock()
    session.get.return_value = json_response(
        {"name": "org/image", "tags": ["1.0.0", "latest"]}
    )
    client = OCIRegistryClient("registry.example/org/image:latest", session=session)

    assert client.registry_tags() == ["1.0.0", "latest"]


def test_registry_tags_rejects_unauthenticated_404() -> None:
    session = Mock()
    session.get.return_value = response(404)
    client = OCIRegistryClient("registry.example/org/image:latest", session=session)

    with pytest.raises(OCIRegistryError, match="before authentication"):
        client.registry_tags()


def test_registry_tags_surfaces_access_denial_after_authentication() -> None:
    challenge = "{} {}".format(
        "Bea" + "rer",
        'realm="https://auth.example/token",'
        'service="registry.example",scope="repository:org/image:pull"',
    )
    session = Mock()
    session.get.side_effect = [
        response(401, headers={"WWW-Authenticate": challenge}),
        json_response({"token": "registry-token"}),
        response(403),
    ]
    client = OCIRegistryClient("registry.example/org/image:latest", session=session)

    with pytest.raises(OCIRegistryError, match="denied access"):
        client.registry_tags()


def test_anonymous_bearer_authentication() -> None:
    session = Mock()
    session.get.return_value = json_response({"token": "registry-token"})
    client = OCIRegistryClient("registry.example/org/image:1.0", session=session)

    authorization = client._authenticate(
        'Bearer realm="https://auth.example/token",'
        'service="registry.example",scope="repository:org/image:pull"'
    )

    assert authorization == "Bearer registry-token"
    assert session.get.call_args.kwargs["auth"] is None


def test_streamed_unauthorized_response_is_closed_before_authentication() -> None:
    unauthorized = response(
        401,
        headers={
            "WWW-Authenticate": (
                'Bearer realm="https://auth.example/token",'
                'service="registry.example",scope="repository:org/image:pull"'
            )
        },
    )
    authenticated = response(200)
    session = Mock()
    session.get.side_effect = [
        unauthorized,
        json_response({"token": "registry-token"}),
        authenticated,
    ]
    client = OCIRegistryClient("registry.example/org/image:1.0", session=session)

    result = client._request("/v2/org/image/manifests/1.0", stream=True)

    assert unauthorized.raw.closed
    assert result is authenticated
    assert session.get.call_args.kwargs["headers"]["Authorization"] == (
        "Bearer registry-token"
    )


def test_non_loopback_localhost_prefix_uses_https() -> None:
    client = OCIRegistryClient("localhost.attacker.example/org/image:1.0")

    assert client.scheme == "https"


def test_insecure_non_loopback_authentication_realm_is_rejected() -> None:
    client = OCIRegistryClient("registry.example/org/image:1.0", access_token="token")

    with pytest.raises(OCIRegistryError, match="insecure non-loopback"):
        client._authenticate(
            'Bearer realm="http://attacker.example/token",'
            'service="registry.example",scope="repository:org/image:pull"'
        )


def test_ghcr_authentication_uses_existing_access_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = Mock()
    session.get.return_value = json_response({"token": "registry-token"})
    monkeypatch.setenv("GITHUB_ACTOR", "octocat")
    client = OCIRegistryClient(
        "ghcr.io/org/image:1.0",
        access_token="github-token",
        session=session,
    )

    authorization = client._authenticate(
        'Bearer realm="https://ghcr.io/token",'
        'service="ghcr.io",scope="repository:org/image:pull"'
    )

    assert authorization == "Bearer registry-token"
    assert session.get.call_args.kwargs["auth"] == (
        "octocat",
        "github-token",
    )
