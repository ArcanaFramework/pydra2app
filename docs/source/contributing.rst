Contributing
============

Contributions to the project are more welcome in various forms. Please see the
`contribution guide  <https://github.com/ArcanaFramework/pipeline2app/blob/main/CONTRIBUTING.md>`_
for details.


Code structure
--------------

The core Arcana code base is implemented in the :mod:`pipeline2app.core` module. Extensions
which implement data store connectors and analyses are installed in separate namesapces
(e.g. ``pipeline2app-xnat``, ``pipeline2app-bids``).

All ``Analysis``, ``Store``, ``Axes`` and ``App`` classes, should be
imported into the extension package root (e.g. ``pipeline2app.xnat.__init__.py``) so they can
be found by references ``xnat/App``. CLI commands should be implemented as ``click``
commands under the ``pipeline2app.core.cli.ext.ext`` group and imported into the subpackage
root.


Authorship
----------

If you contribute code, documentation or bug reports to the repository please
add your name and affiliation to the `Zenodo file <https://github.com/ArcanaFramework/pipeline2app/blob/main/.zenodo.json>`_
