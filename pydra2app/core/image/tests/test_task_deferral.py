"""Tests for deferring the loading of tasks that can't be loaded on the build host to
within the image being built"""

import json
import typing as ty
from pathlib import Path

import pytest
from frametree.core.exceptions import FrameTreeUsageError
from frametree.core.serialize import ClassResolver

from pydra2app.core import App
from pydra2app.core.command.base import ContainerCommand
from pydra2app.core.command.components import task_serializer

pytest.importorskip("pydra.compose.monai")

BUNDLE_PATH = "/monai-bundles/spleen_ct_segmentation"


def _app_spec(bundle: str, resources: ty.Dict[str, ty.Any]) -> ty.Dict[str, ty.Any]:
    return {
        "name": "deferral-test",
        "title": "an app with a task that can only be loaded within the image",
        "version": "1.0",
        "base_image": {
            "name": "python",
            "tag": "3.12.5-slim-bookworm",
            "python": "python3",
            "package_manager": "apt",
            "conda_env": None,
        },
        "authors": [{"name": "Some One", "email": "some.one@an.email.org"}],
        "docs": {"info_url": "http://deferral.readthefakedocs.io"},
        "resources": resources,
        "commands": {
            "spleen_ct_segmentation": {
                "task": {"type": "monai", "bundle": bundle},
                "operates_on": "samples/sample",
                "sources": {"image": {"field": "image"}},
                "sinks": {"pred": {"field": "pred"}},
            }
        },
    }


BUNDLE_RESOURCE = {"spleen_ct_segmentation-bundle": {"path": BUNDLE_PATH}}


@pytest.mark.parametrize(
    "bundle",
    [BUNDLE_PATH, BUNDLE_PATH + "/configs/metadata.json"],
)
def test_missing_path_within_resources_is_deferred(bundle: str) -> None:
    app = App.load(_app_spec(bundle, BUNDLE_RESOURCE), allow_deferred=True)
    command = app.command()
    assert command.deferred
    assert command.image is app
    assert command.source_names == ["image"]
    assert command.sink_names == ["pred"]
    assert task_serializer(command.task) == {"type": "monai", "bundle": bundle}


@pytest.mark.parametrize(
    "bundle,resources",
    [
        # not provided by any resource
        (BUNDLE_PATH, {}),
        (BUNDLE_PATH, {"other": {"path": "/opt/other"}}),
        # shares a prefix with the resource's path, but isn't within it
        ("/monai-bundles/spleen", BUNDLE_RESOURCE),
        # relative paths depend on the working directory within the image
        ("monai-bundles/spleen_ct_segmentation", BUNDLE_RESOURCE),
    ],
)
def test_missing_path_outside_resources_is_raised(
    bundle: str, resources: ty.Dict[str, ty.Any]
) -> None:
    with pytest.raises(FileNotFoundError) as excinfo:
        App.load(_app_spec(bundle, resources), allow_deferred=True)
    assert excinfo.value.filename == bundle
    assert any(
        "within one of the image's resources" in n for n in excinfo.value.__notes__
    )


def test_missing_path_without_image_is_raised() -> None:
    """Outside of an app there are no resources to provide the path"""
    with pytest.raises(FileNotFoundError):
        ContainerCommand(
            name="spleen_ct_segmentation",
            task={"type": "monai", "bundle": BUNDLE_PATH},
            operates_on="samples/sample",
        )


def test_broken_task_is_not_deferred(tmp_path: Path) -> None:
    """A task that fails to load for a reason other than a missing path is reported,
    even if it is within the path of one of the image's resources"""
    bundle = tmp_path / "bundle"
    (bundle / "configs").mkdir(parents=True)
    (bundle / "configs" / "metadata.json").write_text("{not json")
    with pytest.raises(json.JSONDecodeError):
        App.load(
            _app_spec(str(bundle), {"bundle": {"path": str(bundle)}}),
            allow_deferred=True,
        )


def test_missing_provider_package_is_deferred() -> None:
    """A task whose provider module isn't installed is still deferred, as it is assumed
    to be installed within the image"""
    spec = _app_spec(BUNDLE_PATH, BUNDLE_RESOURCE)
    spec["commands"]["spleen_ct_segmentation"]["task"] = {
        "type": "notarealcomposetype",
        "executable": "foo",
    }
    app = App.load(spec, allow_deferred=True)
    assert app.command().deferred


def test_deferred_app_roundtrip(tmp_path: Path) -> None:
    app = App.load(_app_spec(BUNDLE_PATH, BUNDLE_RESOURCE), allow_deferred=True)
    save_path = tmp_path / (app.name + ".yaml")
    app.save(save_path)
    # the flag isn't saved with the spec, as whether deferral is appropriate depends on
    # where the spec is loaded
    assert "allow_deferred" not in save_path.read_text()
    reloaded = App.load(save_path, allow_deferred=True)
    assert reloaded.command().deferred
    assert reloaded == app


def test_missing_path_not_deferred_unless_enabled() -> None:
    """Deferral has to be enabled explicitly, e.g. it shouldn't happen when the spec is
    loaded within the image, where everything the task needs should be present"""
    with pytest.raises(FileNotFoundError) as excinfo:
        App.load(_app_spec(BUNDLE_PATH, BUNDLE_RESOURCE))
    assert any("allow_deferred" in n for n in excinfo.value.__notes__)


def test_missing_provider_package_not_deferred_unless_enabled() -> None:
    spec = _app_spec(BUNDLE_PATH, BUNDLE_RESOURCE)
    spec["commands"]["spleen_ct_segmentation"]["task"] = {
        "type": "notarealcomposetype",
        "executable": "foo",
    }
    with pytest.raises(ModuleNotFoundError):
        App.load(spec)


def test_broken_module_is_not_deferred(monkeypatch: pytest.MonkeyPatch) -> None:
    """Import errors other than a module not being found mean that the module is
    present but broken or incompatible, which won't be fixed within the image"""
    from pydra2app.core.command import components

    def broken_structure(*args: ty.Any, **kwargs: ty.Any) -> ty.NoReturn:
        raise ImportError("cannot import name 'thing' from 'pydra.compose.monai'")

    monkeypatch.setattr(components, "structure", broken_structure)
    with pytest.raises(ImportError, match="cannot import name"):
        App.load(_app_spec(BUNDLE_PATH, BUNDLE_RESOURCE), allow_deferred=True)


def _unresolvable_python_spec() -> ty.Dict[str, ty.Any]:
    spec = _app_spec(BUNDLE_PATH, BUNDLE_RESOURCE)
    spec["commands"]["spleen_ct_segmentation"]["task"] = {
        "type": "python",
        "function": "missing_package.module:task_function",
        "inputs": {"image": {"type": "fileformats.generic:File"}},
        "outputs": {"pred": {"type": "fileformats.generic:File"}},
    }
    return spec


def test_allow_deferred_permits_unresolvable_classes() -> None:
    """`allow_deferred` also covers classes that can't be resolved (i.e. it enables
    `ClassResolver.FALLBACK_TO_STR` while loading), so callers don't need to"""
    app = App.load(_unresolvable_python_spec(), allow_deferred=True)
    assert app.command().deferred
    # the fallback is only enabled while loading
    assert not ClassResolver.FALLBACK_TO_STR.permit


def test_unresolvable_classes_not_permitted_unless_enabled() -> None:
    with pytest.raises(FrameTreeUsageError, match="missing_package"):
        App.load(_unresolvable_python_spec())


def test_allow_deferred_leaves_outer_fallback_enabled() -> None:
    """Loading an app within an existing `FALLBACK_TO_STR` context doesn't switch it
    off on the way out"""
    with ClassResolver.FALLBACK_TO_STR:
        App.load(_unresolvable_python_spec(), allow_deferred=True)
        assert ClassResolver.FALLBACK_TO_STR.permit
    assert not ClassResolver.FALLBACK_TO_STR.permit


def test_load_doesnt_modify_spec() -> None:
    """The commands of the spec are copied before the name of each command and the
    back-reference to the app are added to them, so that the spec can still be saved"""
    spec = _app_spec(BUNDLE_PATH, BUNDLE_RESOURCE)
    command_spec = spec["commands"]["spleen_ct_segmentation"]
    keys_before = set(command_spec)
    App.load(spec, allow_deferred=True)
    assert set(command_spec) == keys_before
