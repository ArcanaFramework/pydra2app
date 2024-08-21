Application Programming Interface
=================================

The core of Arcana's framework is located under the ``pydra2app.core`` sub-package,
which contains all the domain-independent logic. Domain-specific extensions
for alternative data stores, dimensions and formats should be placed in
``pydra2app.stores``, ``pydra2app.data.spaces`` and ``pydra2app.data.types``
respectively.


.. warning::
    Under construction



Data Model
----------

Core
~~~~

.. autoclass:: pydra2app.core.data.datatype.BaseFile

.. autoclass:: pydra2app.core.data.datatype.Directory

.. autoclass:: pydra2app.core.data.datatype.WithSideCars


Stores
~~~~~~

.. autoclass:: pydra2app.file_system.data.SimpleStore

.. autoclass:: pydra2app.bids.Bids

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
