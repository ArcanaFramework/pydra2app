from __future__ import annotations

import hashlib
import ipaddress
import io
import json
import logging
import os
import platform
import re
import tarfile
import typing as ty
import zlib
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
from urllib.parse import quote, urlsplit

import requests
import yaml

from pydra2app.core.exceptions import Pydra2AppBuildError

logger = logging.getLogger("pydra2app")

# OCI and Docker media types are slightly different for the same formats
OCI_INDEX = "application/vnd.oci.image.index.v1+json"
OCI_MANIFEST = "application/vnd.oci.image.manifest.v1+json"
DOCKER_INDEX = "application/vnd.docker.distribution.manifest.list.v2+json"
DOCKER_MANIFEST = "application/vnd.docker.distribution.manifest.v2+json"
MANIFEST_ACCEPT = ", ".join((OCI_INDEX, OCI_MANIFEST, DOCKER_INDEX, DOCKER_MANIFEST))

# Pipeline specs are normally stored in their own ~1 KB layer. Keeping this limit at
# 1 MiB avoids accidentally downloading the larger application layers.
MAX_SPEC_LAYER_SIZE = 1024 * 1024
MAX_SPEC_FILE_SIZE = 1024 * 1024
MAX_EXPANDED_LAYER_SIZE = 8 * 1024 * 1024
MAX_MANIFEST_SIZE = 4 * 1024 * 1024
MAX_CONFIG_SIZE = 4 * 1024 * 1024
REQUEST_TIMEOUT = (10, 60)


class OCIRegistryError(Pydra2AppBuildError):
    """An OCI registry response could not be safely processed."""


class OCIRepositoryNotFound(OCIRegistryError):
    """An authenticated OCI request confirmed that a repository is absent."""


class OCIBlobTooLarge(OCIRegistryError):
    """An OCI blob exceeded the permitted lightweight-inspection size."""


class OCIIntegrityError(OCIRegistryError):
    """OCI content did not match its declared digest."""


class SpecLayerStatus(str, Enum):
    FOUND = "found"
    ABSENT = "absent"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True)
class SpecLayerResult:
    status: SpecLayerStatus
    spec: ty.Optional[ty.Dict[str, ty.Any]] = None


@dataclass(frozen=True)
class OCIImageMetadata:
    config: ty.Dict[str, ty.Any]
    layers: ty.List[ty.Dict[str, ty.Any]]


class OCIRegistryClient:
    """Minimal OCI Distribution API client for reading image metadata and small blobs."""

    def __init__(
        self,
        image_reference: str,
        *,
        access_token: ty.Optional[str] = None,
        session: ty.Optional[requests.Session] = None,
    ) -> None:
        self.registry, self.repository, self.reference = parse_image_reference(
            image_reference
        )
        self.access_token = access_token
        self.session = session or requests.Session()
        registry_host = urlsplit(f"//{self.registry}").hostname
        self.scheme = "http" if is_loopback_host(registry_host) else "https"
        self.api_registry = (
            "registry-1.docker.io" if self.registry == "docker.io" else self.registry
        )
        self._authorization: ty.Optional[str] = None

    def image_metadata(self) -> OCIImageMetadata:
        manifest = self._manifest(self.reference)
        media_type = manifest.get("mediaType")
        if media_type in (OCI_INDEX, DOCKER_INDEX) or "manifests" in manifest:
            descriptor = self._select_platform_manifest(manifest["manifests"])
            if not descriptor.get("digest"):
                raise OCIRegistryError(
                    "Selected OCI image-index descriptor is missing its digest"
                )
            manifest = self._manifest(
                descriptor["digest"], expected_digest=descriptor["digest"]
            )

        try:
            config_descriptor = manifest["config"]
            layers = manifest["layers"]
        except KeyError as e:
            raise OCIRegistryError(
                f"OCI manifest for '{self.repository}:{self.reference}' is missing {e}"
            ) from e
        if (
            not isinstance(config_descriptor, dict)
            or not isinstance(config_descriptor.get("digest"), str)
            or not config_descriptor["digest"]
        ):
            raise OCIRegistryError(
                f"OCI manifest for '{self.repository}:{self.reference}' has an "
                "invalid config descriptor"
            )
        if not isinstance(layers, list):
            raise OCIRegistryError(
                f"OCI manifest for '{self.repository}:{self.reference}' has invalid "
                "layers"
            )
        config_blob = self._blob(
            config_descriptor["digest"],
            expected_digest=config_descriptor["digest"],
            max_size=MAX_CONFIG_SIZE,
        )
        try:
            config = json.loads(config_blob)
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise OCIRegistryError(
                f"Image config for '{self.repository}:{self.reference}' is not valid JSON"
            ) from e
        if not isinstance(config, dict):
            raise OCIRegistryError(
                f"Image config for '{self.repository}:{self.reference}' is not a mapping"
            )
        return OCIImageMetadata(config=config, layers=layers)

    def registry_tags(self) -> ty.List[str]:
        """List repository tags, returning an empty list for confirmed absence."""
        try:
            response = self._request(
                f"/v2/{_quote_repository(self.repository)}/tags/list",
                stream=True,
                authenticated_not_found=True,
            )
        except OCIRepositoryNotFound:
            return []
        content = self._read_bounded_response(response, MAX_MANIFEST_SIZE)
        try:
            data = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise OCIRegistryError(
                f"Registry returned invalid tag-list JSON for '{self.repository}'"
            ) from e
        if not isinstance(data, dict):
            raise OCIRegistryError(
                f"Registry returned an invalid tag list for '{self.repository}'"
            )
        tags = data.get("tags")
        if tags is None:
            return []
        if not isinstance(tags, list) or not all(
            isinstance(tag, str) for tag in tags
        ):
            raise OCIRegistryError(
                f"Registry returned an invalid tag list for '{self.repository}'"
            )
        return tags

    def spec_from_small_layers(
        self,
        layers: ty.Iterable[ty.Dict[str, ty.Any]],
        spec_path: PurePosixPath,
    ) -> SpecLayerResult:
        """Read a spec from eligible layers without extracting other archive members."""
        skipped_newer_layer = False
        for descriptor in reversed(list(layers)):
            if not isinstance(descriptor, dict):
                raise OCIRegistryError("OCI layer descriptor is not a mapping")
            size = descriptor.get("size")
            if not isinstance(size, int) or size < 0:
                raise OCIRegistryError("OCI layer descriptor has an invalid size")
            if size > MAX_SPEC_LAYER_SIZE:
                skipped_newer_layer = True
                continue
            digest = descriptor.get("digest")
            if not isinstance(digest, str) or not digest:
                raise OCIRegistryError("OCI layer descriptor is missing its digest")
            try:
                blob = self._blob(
                    digest,
                    expected_digest=digest,
                    max_size=MAX_SPEC_LAYER_SIZE,
                )
            except OCIBlobTooLarge:
                skipped_newer_layer = True
                continue
            layer_status, spec_bytes = _read_tar_member(blob, spec_path)
            if layer_status is None:
                continue
            if layer_status is SpecLayerStatus.INCONCLUSIVE:
                skipped_newer_layer = True
                continue
            if skipped_newer_layer:
                return SpecLayerResult(SpecLayerStatus.INCONCLUSIVE)
            if layer_status is SpecLayerStatus.ABSENT:
                return SpecLayerResult(SpecLayerStatus.ABSENT)
            assert spec_bytes is not None
            try:
                spec = yaml.safe_load(spec_bytes)
            except yaml.YAMLError as e:
                raise OCIRegistryError(
                    f"Spec in OCI layer {digest} is not valid YAML"
                ) from e
            if not isinstance(spec, dict):
                raise OCIRegistryError(
                    f"Spec in OCI layer {digest} did not contain a mapping"
                )
            return SpecLayerResult(SpecLayerStatus.FOUND, spec)
        return SpecLayerResult(
            SpecLayerStatus.INCONCLUSIVE
            if skipped_newer_layer
            else SpecLayerStatus.ABSENT
        )

    def _manifest(
        self, reference: str, expected_digest: ty.Optional[str] = None
    ) -> ty.Dict[str, ty.Any]:
        response = self._request(
            f"/v2/{_quote_repository(self.repository)}/manifests/{quote(reference, safe=':')}",
            headers={"Accept": MANIFEST_ACCEPT},
            stream=True,
        )
        content = self._read_bounded_response(response, MAX_MANIFEST_SIZE)
        declared_digest = expected_digest or response.headers.get(
            "Docker-Content-Digest"
        )
        if declared_digest:
            verify_digest(content, declared_digest)
        try:
            manifest = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise OCIRegistryError(
                f"Registry returned an invalid manifest for "
                f"'{self.repository}:{reference}'"
            ) from e
        if not isinstance(manifest, dict):
            raise OCIRegistryError(
                f"Registry returned an invalid manifest for "
                f"'{self.repository}:{reference}'"
            )
        return manifest

    def _blob(
        self,
        digest: str,
        *,
        expected_digest: str,
        max_size: ty.Optional[int] = None,
    ) -> bytes:
        response = self._request(
            f"/v2/{_quote_repository(self.repository)}/blobs/"
            f"{quote(digest, safe=':')}",
            stream=max_size is not None,
        )
        content = (
            response.content
            if max_size is None
            else self._read_bounded_response(response, max_size)
        )
        verify_digest(content, expected_digest)
        return content

    @staticmethod
    def _read_bounded_response(response: requests.Response, max_size: int) -> bytes:
        content_length = response.headers.get("Content-Length")
        try:
            exceeds_header_limit = (
                content_length is not None and int(content_length) > max_size
            )
        except ValueError as e:
            response.close()
            raise OCIRegistryError("OCI response has an invalid Content-Length") from e
        if exceeds_header_limit:
            response.close()
            raise OCIBlobTooLarge(
                f"OCI response exceeds the {max_size}-byte inspection limit"
            )
        try:
            content = ty.cast(bytes, response.raw.read(max_size + 1))
        finally:
            response.close()
        if len(content) > max_size:
            raise OCIBlobTooLarge(
                f"OCI response exceeds the {max_size}-byte inspection limit"
            )
        return content

    def _request(
        self,
        path: str,
        *,
        headers: ty.Optional[ty.Dict[str, str]] = None,
        stream: bool = False,
        authenticated_not_found: bool = False,
    ) -> requests.Response:
        url = f"{self.scheme}://{self.api_registry}{path}"
        request_headers = {"Accept-Encoding": "identity", **(headers or {})}
        if self._authorization:
            request_headers["Authorization"] = self._authorization
        try:
            response = self.session.get(
                url,
                headers=request_headers,
                stream=stream,
                timeout=REQUEST_TIMEOUT,
            )
            if response.status_code == 401:
                challenge = response.headers.get("WWW-Authenticate")
                response.close()
                if not challenge:
                    raise OCIRegistryError(
                        f"Registry '{self.registry}' rejected access without an "
                        "authentication challenge"
                    )
                self._authorization = self._authenticate(challenge)
                request_headers["Authorization"] = self._authorization
                response = self.session.get(
                    url,
                    headers=request_headers,
                    stream=stream,
                    timeout=REQUEST_TIMEOUT,
                )
        except requests.RequestException as e:
            raise OCIRegistryError(
                f"Could not read '{self.repository}:{self.reference}' from OCI registry "
                f"'{self.registry}': {e}"
            ) from e
        if response.status_code == 404:
            if authenticated_not_found and self._authorization:
                raise OCIRepositoryNotFound(
                    f"OCI repository '{self.repository}' was not found in registry "
                    f"'{self.registry}' after successful authentication"
                )
            if authenticated_not_found:
                raise OCIRegistryError(
                    f"Could not confirm whether OCI repository '{self.repository}' "
                    f"exists in registry '{self.registry}': the registry returned 404 "
                    "before authentication"
                )
            raise OCIRegistryError(
                f"OCI manifest or blob for '{self.repository}:{self.reference}' "
                f"was not found in registry '{self.registry}'"
            )
        if response.status_code in (401, 403):
            raise OCIRegistryError(
                f"OCI registry '{self.registry}' denied access to "
                f"'{self.repository}:{self.reference}'"
            )
        if not response.ok:
            raise OCIRegistryError(
                f"OCI registry '{self.registry}' returned HTTP "
                f"{response.status_code} for '{self.repository}:{self.reference}'"
            )
        return response

    def _authenticate(self, challenge: str) -> str:
        scheme, separator, parameters = challenge.partition(" ")
        if scheme.lower() != "bearer" or not separator:
            raise OCIRegistryError(
                f"OCI registry '{self.registry}' requested unsupported authentication "
                f"scheme '{scheme}'"
            )
        values = dict(re.findall(r'(\w+)="([^"]*)"', parameters))
        realm = values.pop("realm", None)
        if not realm:
            raise OCIRegistryError(
                f"OCI registry '{self.registry}' returned a Bearer challenge without "
                "a token realm"
            )
        realm_url = urlsplit(realm)
        if realm_url.scheme != "https" and not is_loopback_host(realm_url.hostname):
            raise OCIRegistryError(
                f"OCI registry '{self.registry}' requested authentication over an "
                "insecure non-loopback connection"
            )
        auth: ty.Optional[ty.Tuple[str, str]] = None
        headers: ty.Dict[str, str] = {}
        if self.access_token:
            if self.registry == "ghcr.io":
                auth = (self._github_username(), self.access_token)
            else:
                headers["Authorization"] = f"Bearer {self.access_token}"
        try:
            response = self.session.get(
                realm,
                params={
                    key: value
                    for key, value in values.items()
                    if key in ("service", "scope")
                },
                headers=headers,
                auth=auth,
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as e:
            raise OCIRegistryError(
                f"Could not authenticate with OCI registry '{self.registry}': {e}"
            ) from e
        if not response.ok:
            raise OCIRegistryError(
                f"OCI registry '{self.registry}' authentication failed with HTTP "
                f"{response.status_code}"
            )
        try:
            auth_response = response.json()
        except (requests.JSONDecodeError, json.JSONDecodeError) as e:
            raise OCIRegistryError(
                f"OCI registry '{self.registry}' returned invalid authentication JSON"
            ) from e
        token = auth_response.get("token") or auth_response.get("access_token")
        if not token:
            raise OCIRegistryError(
                f"OCI registry '{self.registry}' authentication response had no token"
            )
        return f"Bearer {token}"

    def _github_username(self) -> str:
        actor = os.environ.get("GITHUB_ACTOR")
        if actor:
            return actor
        try:
            response = self.session.get(
                "https://api.github.com/user",
                timeout=REQUEST_TIMEOUT,
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {self.access_token}",
                },
            )
        except requests.RequestException as e:
            raise OCIRegistryError(
                f"Could not identify the GitHub user for GHCR authentication: {e}"
            ) from e
        if not response.ok or not response.json().get("login"):
            raise OCIRegistryError(
                "Could not identify the GitHub user for GHCR authentication"
            )
        return ty.cast(str, response.json()["login"])

    @staticmethod
    def _select_platform_manifest(
        manifests: ty.Sequence[ty.Dict[str, ty.Any]],
    ) -> ty.Dict[str, ty.Any]:
        if not isinstance(manifests, list) or not manifests:
            raise OCIRegistryError("OCI image index does not contain any manifests")
        machine = platform.machine().lower()
        architecture = {
            "x86_64": "amd64",
            "aarch64": "arm64",
        }.get(machine, machine)
        for preferred_arch in (architecture, "amd64"):
            for descriptor in manifests:
                if not isinstance(descriptor, dict):
                    continue
                image_platform = descriptor.get("platform", {})
                if not isinstance(image_platform, dict):
                    continue
                if (
                    image_platform.get("os") == "linux"
                    and image_platform.get("architecture") == preferred_arch
                ):
                    return descriptor
        raise OCIRegistryError(
            f"OCI image index has no Linux manifest for architecture {architecture!r} "
            "or 'amd64'"
        )


def parse_image_reference(image_reference: str) -> ty.Tuple[str, str, str]:
    """Split an image reference into registry, repository, and tag/digest."""
    name, separator, digest = image_reference.rpartition("@")
    if separator:
        image_name, reference = name, digest
    else:
        image_name, colon, tag = image_reference.rpartition(":")
        if not colon or "/" in tag:
            image_name, reference = image_reference, "latest"
        else:
            reference = tag
    parts = image_name.split("/")
    if "." in parts[0] or ":" in parts[0] or parts[0] == "localhost":
        registry = parts.pop(0)
    else:
        registry = "docker.io"
    if not parts:
        raise OCIRegistryError(f"Invalid image reference {image_reference!r}")
    if registry == "docker.io" and len(parts) == 1:
        parts.insert(0, "library")
    return registry, "/".join(parts), reference


def verify_digest(content: bytes, declared_digest: str) -> None:
    """Verify content against an OCI descriptor digest."""
    algorithm, separator, expected = declared_digest.partition(":")
    if separator != ":" or algorithm != "sha256":
        raise OCIRegistryError(f"Unsupported OCI digest {declared_digest!r}")
    actual = hashlib.sha256(content).hexdigest()
    if actual != expected:
        raise OCIIntegrityError(
            f"OCI blob digest mismatch: expected {declared_digest}, got sha256:{actual}"
        )


def _read_tar_member(
    archive: bytes, requested_path: PurePosixPath
) -> ty.Tuple[ty.Optional[SpecLayerStatus], ty.Optional[bytes]]:
    if archive.startswith(b"\x1f\x8b"):
        try:
            decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
            archive = decompressor.decompress(archive, MAX_EXPANDED_LAYER_SIZE + 1)
        except zlib.error:
            return SpecLayerStatus.INCONCLUSIVE, None
        if len(archive) > MAX_EXPANDED_LAYER_SIZE or not decompressor.eof:
            return SpecLayerStatus.INCONCLUSIVE, None
    elif archive.startswith((b"BZh", b"\xfd7zXZ")):
        return SpecLayerStatus.INCONCLUSIVE, None

    requested_relative = PurePosixPath(*requested_path.parts[1:])
    whiteout_name = requested_relative.with_name(".wh." + requested_relative.name)
    opaque_whiteout = requested_relative.parent / ".wh..wh..opq"
    try:
        target_status: ty.Optional[SpecLayerStatus] = None
        whiteout_seen = False
        content: ty.Optional[bytes] = None
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
            for member in tar:
                member_path = PurePosixPath(member.name)
                while member_path.parts and member_path.parts[0] in ("/", "."):
                    member_path = PurePosixPath(*member_path.parts[1:])
                if member_path in (whiteout_name, opaque_whiteout):
                    whiteout_seen = True
                    continue
                if member_path != requested_relative:
                    continue
                if not member.isfile():
                    target_status = SpecLayerStatus.INCONCLUSIVE
                    content = None
                    continue
                if member.size > MAX_SPEC_FILE_SIZE:
                    target_status = SpecLayerStatus.INCONCLUSIVE
                    content = None
                    continue
                extracted = tar.extractfile(member)
                if extracted is None:
                    target_status = SpecLayerStatus.INCONCLUSIVE
                    content = None
                    continue
                candidate = extracted.read(MAX_SPEC_FILE_SIZE + 1)
                if len(candidate) <= MAX_SPEC_FILE_SIZE:
                    target_status = SpecLayerStatus.FOUND
                    content = candidate
                else:
                    target_status = SpecLayerStatus.INCONCLUSIVE
                    content = None
        if target_status is not None:
            return target_status, content
        if whiteout_seen:
            return SpecLayerStatus.ABSENT, None
        return None, None
    except (tarfile.TarError, OSError):
        return SpecLayerStatus.INCONCLUSIVE, None
    return None, None


def _quote_repository(repository: str) -> str:
    return "/".join(quote(part, safe="") for part in repository.split("/"))


def is_loopback_host(host: ty.Optional[str]) -> bool:
    if host == "localhost":
        return True
    if host is None:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
