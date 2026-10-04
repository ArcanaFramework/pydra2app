import gzip
import io
import shutil
import subprocess
import tarfile
import typing as ty
import zipfile
from pathlib import Path

import pytest

from pydra2app.core.exceptions import Pydra2AppBuildError
from pydra2app.core.image import P2AImage, extraction
from pydra2app.core.image.components import (
    CondaPackage,
    Docs,
    KnownIssue,
    License,
    PipPackage,
    Resource,
)


@pytest.mark.parametrize(
    "version,expected",
    [
        ("1.0.1", "==1.0.1"),
        ("1.0a9", "==1.0a9"),
        ("==1.0.1", "==1.0.1"),
        (">=1.0.1", ">=1.0.1"),
        ("<=1.0.1", "<=1.0.1"),
        ("~=1.0", "~=1.0"),
        ("!=1.0.1", "!=1.0.1"),
        (">1.0.1", ">1.0.1"),
        ("<1.0.1", "<1.0.1"),
        (None, None),
    ],
)
def test_pip_package_version_specifier(
    version: str | None, expected: str | None
) -> None:
    """A bare version number is treated as an exact pin, for backwards
    compatibility with specs that just give a version number, while an
    explicit specifier (e.g. ">=1.0.1") is passed through untouched"""
    assert PipPackage(name="a-package", version=version).version == expected


def test_pip_package_invalid_version_specifier() -> None:
    with pytest.raises(ValueError, match="Invalid version specifier"):
        PipPackage(name="a-package", version="not-a-version!!")


@pytest.mark.parametrize(
    "version,expected",
    [
        ("1.0.1", "a-package==1.0.1"),
        (">=1.0.1", "a-package>=1.0.1"),
        (None, "a-package"),
    ],
)
def test_pip_spec2str(version: str | None, expected: str) -> None:
    """The rendered pip install string carries through whichever comparison
    operator the version specifier was given with (defaulting to an exact
    pin for a bare version number)"""
    pip_spec = PipPackage(name="a-package", version=version)
    assert (
        P2AImage.pip_spec2str(pip_spec, dockerfile=None, build_dir=Path("/tmp"))
        == expected
    )


@pytest.mark.parametrize(
    "version,expected",
    [
        ("1.21", "=1.21"),
        ("==1.21.0", "==1.21.0"),
        (">=1.21", ">=1.21"),
        ("<=1.21", "<=1.21"),
        ("!=1.21", "!=1.21"),
        (">1.21", ">1.21"),
        ("<1.21", "<1.21"),
        ("=1.21", "=1.21"),
        (None, None),
    ],
)
def test_conda_package_version_specifier(
    version: str | None, expected: str | None
) -> None:
    """A bare version number is treated as conda's "starts with" pin (its
    existing, pre-change behaviour), while an explicit constraint (e.g.
    ">=1.21" or an exact "==1.21.0" pin) is passed through untouched"""
    assert CondaPackage(name="a-package", version=version).version == expected


@pytest.mark.parametrize(
    "url",
    [
        "http://concatenate.readthefakedocs.io",
        "https://example.com/path/to/page?query=1#anchor",
        "http://localhost:8080/licenses",
    ],
)
def test_url_validator(url: str) -> None:
    assert Docs(info_url=url).info_url == url
    license = License(
        name="a-license",
        destination="/opt/license.txt",
        description="a license",
        info_url=url,
    )
    assert license.info_url == url
    assert KnownIssue(description="an issue", url=url).url == url
    assert Resource(name="a-resource", path=Path("/opt/resource"), url=url).url == url


@pytest.mark.parametrize(
    "url",
    [
        "",
        "example.com",
        "/a/local/path",
        "ftp://example.com/file.txt",
        "http://",
        "http://example .com",
    ],
)
def test_url_validator_fail(url: str) -> None:
    with pytest.raises(ValueError, match="Invalid URL"):
        Docs(info_url=url)
    with pytest.raises(ValueError, match="Invalid URL"):
        KnownIssue(description="an issue", url=url)
    with pytest.raises(ValueError, match="Invalid URL"):
        Resource(name="a-resource", path=Path("/opt/resource"), url=url)


def test_url_validator_optional() -> None:
    """URLs of optional fields can be omitted, but required ones still need to be
    valid strings"""
    assert KnownIssue(description="an issue").url is None
    assert Resource(name="a-resource", path=Path("/opt/resource")).url is None
    with pytest.raises(TypeError, match="Invalid URL"):
        Docs(info_url=None)  # type: ignore[arg-type]


RESOURCE_URL = (
    "https://raw.githubusercontent.com/ArcanaFramework/pydra2app/main/LICENSE"
)


def _resource_image(resources: dict[str, ty.Any]) -> P2AImage:
    return P2AImage(
        name="test-resource-url-image",
        version="1.0",
        base_image={
            "name": "python",
            "tag": "3.12.5-slim-bookworm",
            "python": "python3",
            "package_manager": "apt",
            "conda_env": None,
        },
        resources=resources,
    )


def _render_resources(
    img: P2AImage, build_dir: Path, resources: dict[str, Path] | None = None
) -> list[str]:
    build_dir.mkdir(parents=True, exist_ok=True)
    dockerfile = img.init_dockerfile()
    img.add_resources(dockerfile, build_dir, resources=resources, resources_dir=None)
    return dockerfile.render().splitlines()


def test_add_resources_from_url(tmp_path: Path) -> None:
    """Resources that aren't provided locally are downloaded from their URL with curl,
    rather than ADD, so that the download is cached along with the layer"""
    img = _resource_image(
        {"a-resource": {"path": "/internal/path/to/LICENSE", "url": RESOURCE_URL}}
    )
    rendered = "\n".join(_render_resources(img, tmp_path / "build-dir"))
    assert f'curl -fsSL "{RESOURCE_URL}" -o "/internal/path/to/LICENSE"' in rendered
    assert 'mkdir -p "$(dirname "/internal/path/to/LICENSE")"' in rendered
    assert "ADD " not in rendered


def test_add_resources_local_overrides_url(tmp_path: Path) -> None:
    """A locally provided resource is used in preference to its URL"""
    img = _resource_image(
        {"a-resource": {"path": "/internal/path/to/LICENSE", "url": RESOURCE_URL}}
    )
    local_file = tmp_path / "LICENSE"
    local_file.write_text("local license")
    build_dir = tmp_path / "build-dir"
    lines = _render_resources(img, build_dir, resources={"a-resource": local_file})
    assert not any(RESOURCE_URL in ln for ln in lines)
    assert any(ln.startswith("COPY") and "resources/a-resource" in ln for ln in lines)
    assert (build_dir / "resources" / "a-resource").read_text() == "local license"


def test_add_resources_missing_without_url(tmp_path: Path) -> None:
    """Resources without a URL still need to be provided locally"""
    img = _resource_image({"a-resource": "/internal/path/to/a/resource.txt"})
    with pytest.raises(RuntimeError, match="Resource 'a-resource' specified"):
        _render_resources(img, tmp_path / "build-dir")


def _run_instructions(rendered: str) -> ty.List[str]:
    """Splits a rendered Dockerfile into its RUN instructions, joining continuations,
    excluding the one Neurodocker adds to save its specification"""
    return [
        line
        for line in rendered.replace("\\\n", " ").splitlines()
        if line.startswith("RUN ") and not line.startswith("RUN printf")
    ]


def test_add_resources_extract_remote(tmp_path: Path) -> None:
    """A remote archive is downloaded, unpacked and deleted in the one layer, which
    also installs the tools needed and removes them again, so that neither the archive
    nor the tools take up space in the image"""
    img = _resource_image(
        {
            "archive": {
                "path": "/opt/archive",
                "url": "https://example.org/data.tar.gz",
                "extract": True,
            }
        }
    )
    rendered = "\n".join(_render_resources(img, tmp_path / "build"))
    assert "ADD " not in rendered
    runs = _run_instructions(rendered)
    assert len(runs) == 1
    run = runs[0]
    steps = [
        "apt-get install -y -qq --no-install-recommends $missing",
        'curl -fsSL "https://example.org/data.tar.gz" -o "/tmp/archive-data.tar.gz"',
        'tar -xzf "/tmp/archive-data.tar.gz" -C "/opt/archive"',
        'rm -f "/tmp/archive-data.tar.gz"',
        "apt-get purge -y -qq --auto-remove $missing",
    ]
    positions = [run.index(step) for step in steps]
    assert positions == sorted(positions)
    for command, packages in [
        ("curl", "curl ca-certificates"),
        ("tar", "tar"),
        ("gzip", "gzip"),
    ]:
        assert f"command -v {command} >/dev/null 2>&1 || for p in {packages};" in run


def test_add_resources_remote_with_yum(tmp_path: Path) -> None:
    img = P2AImage(
        name="test-extract-remote-yum",
        version="1.0",
        base_image={
            "name": "rockylinux",
            "tag": "9",
            "python": "python3",
            "package_manager": "yum",
            "conda_env": None,
        },
        resources={
            "archive": {
                "path": "/opt/archive",
                "url": "https://example.org/data.zip",
                "extract": True,
            }
        },
    )
    rendered = "\n".join(_render_resources(img, tmp_path / "build"))
    assert "yum install -y -q $missing" in rendered
    assert "yum remove -y -q $missing" in rendered
    assert 'rpm -q "$p"' in rendered
    assert "for p in unzip;" in rendered
    assert "apt-get" not in rendered


def test_download_command_only_removes_tools_it_installed(tmp_path: Path) -> None:
    """Runs the generated command against stubbed tools, to check that only packages
    that weren't there before are installed, and that they are removed afterwards"""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "log"
    # the only real tools on the path, so that the commands that are checked for
    # can be stubbed in or left out as required
    for tool in ("mkdir", "rm", "chmod", "touch"):
        (bin_dir / tool).symlink_to(shutil.which(tool))  # type: ignore[arg-type]
    curl_stub = f'#!/bin/sh\necho "curl $*" >> "{log}"\ntouch "$4"\n'
    stubs = {
        # 'ca-certificates' and 'tar' are installed, 'curl' and 'gzip' aren't
        "dpkg": 'shift; [ "$1" = "ca-certificates" ] || [ "$1" = "tar" ]',
        # installing 'curl' makes the 'curl' command available
        "apt-get": (
            f'echo "apt-get $*" >> "{log}"\n'
            f'if [ "$1" = "install" ]; then printf \'{curl_stub}\' > "{bin_dir}/curl"; '
            f'chmod +x "{bin_dir}/curl"; fi'
        ),
        "tar": f'echo "tar $*" >> "{log}"',
    }
    for name, body in stubs.items():
        stub = bin_dir / name
        stub.write_text(f"#!/bin/sh\n{body}\n")
        stub.chmod(0o755)

    # NB: only the archive's own path is redirected into tmp_path, as on Linux tmp_path
    # is itself within /tmp
    command = (
        extraction.download_command(
            "https://example.org/data.tar.gz",
            str(tmp_path / "dest"),
            "apt",
            extraction.method_for("data.tar.gz"),
        )
        .replace('"/tmp/dest-data.tar.gz"', f'"{tmp_path}/dest-data.tar.gz"')
        .replace("/var/lib/apt/lists", str(tmp_path / "lists"))
    )
    subprocess.run(["/bin/sh", "-c", command], check=True, env={"PATH": str(bin_dir)})

    archive = tmp_path / "dest-data.tar.gz"
    assert log.read_text().splitlines() == [
        "apt-get update -qq",
        "apt-get install -y -qq --no-install-recommends curl gzip",
        f"curl -fsSL https://example.org/data.tar.gz -o {archive}",
        f"tar -xzf {archive} -C {tmp_path / 'dest'}",
        "apt-get purge -y -qq --auto-remove curl gzip",
    ]
    assert not archive.exists()


def test_download_command_installs_nothing_when_tools_present(tmp_path: Path) -> None:
    command = extraction.download_command(
        "https://example.org/file.txt", "/opt/file.txt", "apt"
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "log"
    for tool in ("mkdir", "dirname"):
        (bin_dir / tool).symlink_to(shutil.which(tool))  # type: ignore[arg-type]
    for name in ("curl", "apt-get", "dpkg"):
        stub = bin_dir / name
        stub.write_text(f'#!/bin/sh\necho "{name} $*" >> "{log}"\n')
        stub.chmod(0o755)
    command = command.replace("/opt/file.txt", str(tmp_path / "opt" / "file.txt"))
    subprocess.run(["/bin/sh", "-c", command], check=True, env={"PATH": str(bin_dir)})
    assert log.read_text().splitlines() == [
        f"curl -fsSL https://example.org/file.txt -o {tmp_path / 'opt' / 'file.txt'}"
    ]
    assert (tmp_path / "opt").is_dir()


def test_add_resources_extract_local(tmp_path: Path) -> None:
    """A local archive is extracted on the build host, so it doesn't enter the image
    at all, and needs no extraction tool installed in it"""
    archive = tmp_path / "payload.zip"
    contents = tmp_path / "payload"
    (contents / "nested").mkdir(parents=True)
    (contents / "nested" / "a.txt").write_text("a")
    with zipfile.ZipFile(archive, "w") as zfile:
        zfile.write(contents / "nested" / "a.txt", "payload/nested/a.txt")

    img = _resource_image({"payload": {"path": "/opt/payload", "extract": True}})
    build_dir = tmp_path / "build"
    rendered = "\n".join(
        _render_resources(img, build_dir, resources={"payload": archive})
    )
    assert 'COPY ["resources/payload", \\\n      "/opt/payload"]' in rendered
    # nothing to install or extract within the image
    assert _run_instructions(rendered) == []
    # the archive's top-level entries, as extracting within the image would give
    staged = build_dir / "resources" / "payload"
    assert (staged / "payload" / "nested" / "a.txt").read_text() == "a"


def test_add_resources_extract_local_failure(tmp_path: Path) -> None:
    """A local archive that can't be extracted is reported rather than copied in"""
    archive = tmp_path / "broken.tar.gz"
    archive.write_text("not really an archive")
    img = _resource_image({"broken": {"path": "/opt/broken", "extract": True}})
    with pytest.raises(Pydra2AppBuildError, match="Could not extract 'broken'"):
        _render_resources(img, tmp_path / "build", resources={"broken": archive})


def test_extraction_method_detection() -> None:
    """The tool to extract with is determined by the file extension"""
    assert extraction.method_for("data.tar.gz").name == "tar+gzip"
    assert extraction.method_for("data.tgz").name == "tar+gzip"
    assert extraction.method_for("data.tar").name == "tar"
    assert extraction.method_for("data.zip").name == "zip"
    assert extraction.method_for("data.tar.xz").name == "tar+xz"
    # the more specific suffix wins over the one it ends with
    assert extraction.method_for("data.gz").name == "gzip"
    # a URL may carry a query string after the file name
    assert extraction.method_for("https://e.org/d.zip?raw=true").name == "zip"
    with pytest.raises(extraction.UnrecognisedArchiveError, match="Did not recognise"):
        extraction.method_for("data.txt")


def test_extraction_packages_differ_by_package_manager() -> None:
    method = extraction.method_for("data.tar.xz")
    assert method.system_packages("apt") == ("tar", "xz-utils")
    assert method.system_packages("yum") == ("tar", "xz")


def _make_archive(path: Path, members: dict[str, str]) -> None:
    """Writes `members` (relative path -> contents) into an archive at `path`, of the
    type given by its extension"""
    name = path.name
    if name.endswith(".zip"):
        with zipfile.ZipFile(path, "w") as zfile:
            for member, text in members.items():
                zfile.writestr(member, text)
        return
    for suffix, mode in [
        (".tar.gz", "w:gz"),
        (".tar.bz2", "w:bz2"),
        (".tar.xz", "w:xz"),
        (".tar", "w"),
    ]:
        if name.endswith(suffix):
            with tarfile.open(path, mode) as tfile:  # type: ignore[call-overload]
                for member, text in members.items():
                    data = text.encode()
                    info = tarfile.TarInfo(member)
                    info.size = len(data)
                    tfile.addfile(info, io.BytesIO(data))
            return
    raise ValueError(name)


@pytest.mark.parametrize(
    "archive_name,members",
    [
        # a single top-level directory
        ("a.tar.gz", {"payload/hello.txt": "hi"}),
        ("a.zip", {"payload/nested/hello.txt": "hi"}),
        # several top-level entries, which the previous fileformats-based extraction
        # couldn't handle
        ("a.zip", {"one.txt": "one", "two.txt": "two"}),
        ("a.tar.bz2", {"one.txt": "one", "sub/two.txt": "two"}),
        # a single file
        ("a.tar.xz", {"lone.txt": "just a file"}),
        ("a.zip", {"lone.txt": "just a file"}),
        ("a.tar", {"lone.txt": "just a file"}),
    ],
)
def test_extract_locally_matches_the_in_image_layout(
    tmp_path: Path, archive_name: str, members: dict[str, str]
) -> None:
    """Extracting on the build host gives the same layout as the command that would
    extract it within the image"""
    archive = tmp_path / archive_name
    _make_archive(archive, members)

    host = tmp_path / "host"
    extraction.extract_locally(archive, host)
    for member, text in members.items():
        assert (host / member).read_text() == text

    if shutil.which("unzip") is None and archive_name.endswith(".zip"):
        return
    in_image = tmp_path / "in-image"
    in_image.mkdir()
    subprocess.run(
        extraction.extract_command(
            extraction.method_for(archive_name), str(archive), str(in_image)
        ),
        shell=True,
        check=True,
    )
    assert sorted(str(p.relative_to(host)) for p in host.rglob("*")) == sorted(
        str(p.relative_to(in_image)) for p in in_image.rglob("*")
    )


def test_extract_locally_single_compressed_file(tmp_path: Path) -> None:
    """A compressed file that isn't a tar is decompressed under its own stem"""
    archive = tmp_path / "data.csv.gz"
    with gzip.open(archive, "wb") as f:
        f.write(b"a,b\n1,2\n")
    dest = tmp_path / "dest"
    extraction.extract_locally(archive, dest)
    assert (dest / "data.csv").read_bytes() == b"a,b\n1,2\n"


def test_extract_locally_keeps_zip_permissions(tmp_path: Path) -> None:
    """Executables in a zip stay executable, as they would be when unzipped"""
    archive = tmp_path / "tools.zip"
    with zipfile.ZipFile(archive, "w") as zfile:
        info = zipfile.ZipInfo("bin/run.sh")
        info.external_attr = 0o755 << 16
        zfile.writestr(info, "#!/bin/sh\necho hi\n")
    dest = tmp_path / "dest"
    extraction.extract_locally(archive, dest)
    assert (dest / "bin" / "run.sh").stat().st_mode & 0o777 == 0o755


def test_extract_locally_rejects_paths_outside_dest(tmp_path: Path) -> None:
    """A tar member that would be written outside of the destination is refused"""
    archive = tmp_path / "evil.tar"
    _make_archive(archive, {"../escaped.txt": "gotcha"})
    with pytest.raises(tarfile.OutsideDestinationError):
        extraction.extract_locally(archive, tmp_path / "dest")
    assert not (tmp_path / "escaped.txt").exists()


def test_extract_locally_unsupported_type(tmp_path: Path) -> None:
    """Archive types that can only be extracted in the image are reported"""
    archive = tmp_path / "a.7z"
    archive.write_bytes(b"")
    with pytest.raises(extraction.UnrecognisedArchiveError, match="build host"):
        extraction.extract_locally(archive, tmp_path / "dest")


@pytest.mark.parametrize(
    "spec,version,expected",
    [
        # single bounds
        (">=0.19.0", "0.19.0", True),
        (">=0.19.0", "0.20.0", True),
        (">=0.19.0", "0.18.9", False),
        (">0.19.0", "0.19.0", False),
        (">0.19.0", "0.19.1", True),
        ("<=1.0", "1.0", True),
        ("<=1.0", "1.0.1", False),
        ("<1.0", "0.9.9", True),
        ("<1.0", "1.0", False),
        ("==1.0.1", "1.0.1", True),
        ("==1.0.1", "1.0.2", False),
        ("!=1.0.1", "1.0.1", False),
        ("!=1.0.1", "1.0.2", True),
        # whitespace between operator and version
        (">= 0.19.0", "0.20.0", True),
        (">= 0.19.0", "0.18.0", False),
        # trailing zeros are insignificant
        ("==1.0", "1.0.0", True),
        (">=1.0", "1", True),
        # multiple, comma-separated constraints must all be satisfied
        (">=1.0,<2.0", "1.5", True),
        (">=1.0,<2.0", "0.9", False),
        (">=1.0,<2.0", "2.0", False),
        (">=1.0, <2.0, !=1.5", "1.5", False),
        (">=1.0, <2.0, !=1.5", "1.6", True),
        # a bare version is treated as an exact pin
        ("1.2.3", "1.2.3", True),
        ("1.2.3", "1.2.4", False),
        # compatible release
        ("~=1.4", "1.4", True),
        ("~=1.4", "1.9.3", True),
        ("~=1.4", "2.0", False),
        ("~=1.4.2", "1.4.5", True),
        ("~=1.4.2", "1.5", False),
        ("~=1.4.2", "1.4.1", False),
        # wildcards
        ("==1.4.*", "1.4.7", True),
        ("==1.4.*", "1.5.0", False),
        # pre/post/dev-releases, which are matched as they are often installed
        # locally during development
        (">=1.0", "1.0rc1", False),
        (">=1.0rc1", "1.0rc2", True),
        (">=1.0", "1.0.post1", True),
        (">=1.0", "1.1.dev3", True),
        ("<1.0.post1", "1.0", True),
        # numeric rather than lexical comparison of release components
        (">=1.9", "1.10", True),
        ("<1.10", "1.9", True),
        # local version labels
        (">=1.0", "1.1+g1234abc", True),
        # versions that aren't PEP 440 compliant never match
        (">=1.0", "not-a-version", False),
    ],
)
def test_pip_package_version_matches(spec: str, version: str, expected: bool) -> None:
    assert PipPackage(name="a-package", version=spec).version_matches(version) is expected


def test_pip_package_version_matches_unversioned() -> None:
    """A package without a version specifier is satisfied by any version"""
    assert PipPackage(name="a-package").version_matches("0.0.1")


@pytest.mark.parametrize("spec", ["=>1.0", "=1.0", "~=1", "1.0 || 2.0"])
def test_pip_package_malformed_version_specifier(spec: str) -> None:
    """Malformed specifiers are rejected rather than partially parsed"""
    with pytest.raises(ValueError, match="Invalid version specifier"):
        PipPackage(name="a-package", version=spec)
