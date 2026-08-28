import json
from pathlib import Path
from unittest.mock import Mock, PropertyMock

import pytest
from click.testing import CliRunner

from pydra2app.core.cli import make, plan_builds
from pydra2app.core.exceptions import Pydra2AppBuildError, Pydra2AppReleaseError
from pydra2app.core.image import App
from pydra2app.core.image.components import Version
from pydra2app.core.release import plan_release, ReleaseStatus


def app(
    current: str,
    published: str | None,
    *,
    matches: bool = False,
    name: str = "example",
) -> Mock:
    image_spec = Mock()
    image_spec.name = name
    image_spec.path = f"registry.example/org/{name}"
    image_spec.version = Version.parse(current)
    image_spec.latest_published = (
        Version.parse(published) if published is not None else None
    )
    image_spec.matches_image.return_value = matches
    image_spec.loaded_from = Path(f"/specs/{name}.yaml")
    return image_spec


@pytest.mark.parametrize(
    ("current", "published"),
    [("1.0", None), ("1.1", "1.0")],
)
def test_plan_release_builds_new_image(current: str, published: str | None) -> None:
    image_spec = app(current, published)

    decision = plan_release(image_spec)

    assert decision.status is ReleaseStatus.BUILD
    image_spec.matches_image.assert_not_called()


def test_plan_release_skips_unchanged_image() -> None:
    image_spec = app("1.0", "1.0", matches=True)

    decision = plan_release(image_spec)

    assert decision.status is ReleaseStatus.UNCHANGED
    image_spec.matches_image.assert_called_once_with(
        "registry.example/org/example:1.0"
    )


def test_plan_release_rejects_changed_spec_without_version_increment() -> None:
    decision = plan_release(app("1.0", "1.0", matches=False))

    assert decision.status is ReleaseStatus.INVALID
    assert "without a version increment" in decision.reason


def test_plan_release_rejects_version_decrease() -> None:
    image_spec = app("1.0", "1.1")

    decision = plan_release(image_spec)

    assert decision.status is ReleaseStatus.INVALID
    assert "Version decreased" in decision.reason
    image_spec.matches_image.assert_not_called()


def test_plan_builds_selected_specs_preserve_relative_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec_path = tmp_path / "specs" / "org"
    selected_paths = [
        spec_path / "quality-control" / "phi-finder.yaml",
        spec_path / "mri" / "human" / "neuro" / "preprocess.yml",
    ]
    disabled_path = spec_path / "disabled.yaml"
    for path in selected_paths + [disabled_path]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

    image_specs = {}
    for path in selected_paths:
        image_spec = app("1.0", None, name=path.stem)
        image_spec.loaded_from = path.absolute()
        image_specs[path.resolve()] = image_spec

    loaded_paths = []

    def load_tree(
        cls: type[App], path: Path, **kwargs: object
    ) -> list[Mock]:
        loaded_paths.append(path)
        assert kwargs["root_dir"] == spec_path.parent
        return [image_specs[path.resolve()]]

    monkeypatch.setattr(App, "load_tree", classmethod(load_tree))

    result = CliRunner().invoke(
        plan_builds,
        [
            "common:App",
            str(spec_path),
            "--spec",
            "quality-control/phi-finder",
            "--spec",
            "mri/human/neuro/preprocess.yml",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "build": [
            "mri/human/neuro/preprocess",
            "quality-control/phi-finder",
        ],
        "unchanged": [],
    }
    assert loaded_paths == sorted(selected_paths)


def test_plan_builds_rejects_missing_selected_spec(tmp_path: Path) -> None:
    spec_path = tmp_path / "specs"
    spec_path.mkdir()

    result = CliRunner().invoke(
        plan_builds,
        ["common:App", str(spec_path), "--spec", "missing"],
    )

    assert result.exit_code == 2
    assert "Could not find selected spec 'missing'" in result.output


def test_plan_builds_reports_registry_access_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec_path = tmp_path / "specs"
    spec_path.mkdir()
    image_spec = app("1.0", None)
    image_spec.loaded_from = spec_path / "example.yaml"
    monkeypatch.setattr(
        type(image_spec),
        "latest_published",
        PropertyMock(
            side_effect=Pydra2AppBuildError(
                "Registry access could not be confirmed"
            )
        ),
        raising=False,
    )
    monkeypatch.setattr(
        App,
        "load_tree",
        classmethod(lambda cls, *args, **kwargs: [image_spec]),
    )

    result = CliRunner().invoke(plan_builds, ["common:App", str(spec_path)])

    assert result.exit_code == 1
    assert result.output == "Error: Registry access could not be confirmed\n"
    assert isinstance(result.exception, SystemExit)


def test_make_check_registry_reuses_release_rules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec_path = tmp_path / "org"
    loaded_from = spec_path / "package" / "changed.yaml"
    loaded_from.parent.mkdir(parents=True)
    loaded_from.touch()
    image_spec = app("1.0", "1.0", matches=False, name="package.changed")
    image_spec.loaded_from = loaded_from
    monkeypatch.setattr(
        App,
        "load_tree",
        classmethod(lambda cls, *args, **kwargs: [image_spec]),
    )
    monkeypatch.setattr("pydra2app.core.cli.docker.from_env", Mock())

    result = CliRunner().invoke(
        make,
        ["common:App", str(spec_path), "--check-registry"],
    )

    assert result.exit_code == 1
    assert isinstance(result.exception, Pydra2AppReleaseError)
    assert "without a version increment" in str(result.exception)
    image_spec.make.assert_not_called()
