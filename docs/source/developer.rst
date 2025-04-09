Developer guide
===============

Contributions to the project are more welcome in various forms. Please see the
`contribution guide  <https://github.com/ArcanaFramework/pydra2app/blob/main/CONTRIBUTING.md>`_
for details.


Code structure
--------------

The core Pydra2App code base is implemented in the :mod:`pydra2app.core` module. Extensions
which implement data store connectors and analyses are installed in separate namesapces
(e.g. ``pydra2app-xnat``).

All ``App`` classes should beimported into the extension package root
(e.g. ``pydra2app.xnat.__init__.py``) so they can be found by references ``xnat/App``
in the CLI. Extension CLI commands should be implemented as ``click``
commands under the ``pydra2app.core.cli.ext`` group and imported into the subpackage
root.


Authorship
----------

If you contribute code, documentation or bug reports to the repository please
add your name and affiliation to the `Zenodo file <https://github.com/ArcanaFramework/pydra2app/blob/main/.zenodo.json>`_
