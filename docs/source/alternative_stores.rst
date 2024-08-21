.. _alternative_stores:

Alternative storage systems
===========================

Alternative storage systems can be implemented by writing a new subclass of
:class:`.Store`. The developers are interested in adding support for new systems,
so if you would help to use Arcana with a different storage system please
create an issue for it in the `GitHub Issue Tracker <https://github.com/Australian-Imaging-Service/pydra2app/issues>`__.

Required methods
----------------

When subclassing :class:`.Store`, the following abstract methods must be
overridden to implement the appropriate functionality of the data store. For
a reference implementation please see :class:`pydra2app.file_system.data.SimpleStore`.

.. autoclass:: pydra2app.core.store.Store
    :noindex:
    :members: find_rows, find_cells, get_file_group_paths, download_value, put_file_group_paths, upload_value, save_dataset_definition, load_dataset_definition

Optional methods
----------------

The following methods are not strictly necessary to override, but can offer
significant performance boosts by avoiding unnecessary downloads in the
case of :meth:`.Store.get_checksums` and unnecessary remote connections
in the case of :meth:`.Store.connect` and :meth:`.Store.disconnect`
(by caching the connection between multiple calls).

.. autoclass:: pydra2app.core.store.Store
    :noindex:
    :members: get_checksums, connect, disconnect
