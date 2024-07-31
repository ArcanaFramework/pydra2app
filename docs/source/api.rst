Application Programming Interface
=================================

The core of Arcana's framework is located under the ``pydra2app.core`` sub-package,
which contains all the domain-independent logic. Domain-specific extensions
for alternative data stores, dimensions and formats should be placed in
``pydra2app.data.stores``, ``pydra2app.data.spaces`` and ``pydra2app.data.types``
respectively.


.. warning::
    Under construction



Data Model
----------

Core
~~~~

.. autoclass:: pydra2app.core.data.store.DataStore

.. autoclass:: pydra2app.core.data.set.Dataset
    :members: add_source, add_sink

.. autoclass:: pydra2app.core.data.space.DataSpace

.. autoclass:: pydra2app.core.data.row.DataRow

.. autoclass:: pydra2app.core.data.column.DataSource

.. autoclass:: pydra2app.core.data.column.DataSink

.. autoclass:: pydra2app.core.data.datatype.DataType
    :members: get, put

.. autoclass:: pydra2app.core.data.datatype.FileSet

.. autoclass:: pydra2app.core.data.datatype.Field

.. autoclass:: pydra2app.core.data.datatype.BaseFile

.. autoclass:: pydra2app.core.data.datatype.Directory

.. autoclass:: pydra2app.core.data.datatype.WithSideCars


Stores
~~~~~~

.. autoclass:: pydra2app.dirtree.data.SimpleStore

.. autoclass:: pydra2app.bids.data.Bids

.. autoclass:: pydra2app.medimage.data.Xnat

.. autoclass:: pydra2app.medimage.data.XnatViaCS
    :members: generate_xnat_command, generate_dockerfile, create_wrapper_image


Processing
----------

.. autoclass:: pydra2app.core.analysis.pipeline.Pipeline


Enums
~~~~~

.. autoclass:: pydra2app.core.enum.ColumnSalience
    :members:
    :undoc-members:
    :member-order: bysource

.. autoclass:: pydra2app.core.enum.ParameterSalience
    :members:
    :undoc-members:
    :member-order: bysource

.. autoclass:: pydra2app.core.enum.DataQuality
    :members:
    :undoc-members:
    :member-order: bysource
