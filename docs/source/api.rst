Application Programming Interface
=================================

The core of Arcana's framework is located under the ``pipeline2app.core`` sub-package,
which contains all the domain-independent logic. Domain-specific extensions
for alternative data stores, dimensions and formats should be placed in
``pipeline2app.stores``, ``pipeline2app.data.spaces`` and ``pipeline2app.data.types``
respectively.


.. warning::
    Under construction



Data Model
----------

Core
~~~~

.. autoclass:: pipeline2app.core.data.datatype.BaseFile

.. autoclass:: pipeline2app.core.data.datatype.Directory

.. autoclass:: pipeline2app.core.data.datatype.WithSideCars


Stores
~~~~~~

.. autoclass:: pipeline2app.file_system.data.SimpleStore

.. autoclass:: pipeline2app.bids.Bids

.. autoclass:: pipeline2app.medimage.data.Xnat

.. autoclass:: pipeline2app.medimage.data.XnatViaCS
    :members: generate_xnat_command, generate_dockerfile, create_wrapper_image


Processing
----------

.. autoclass:: pipeline2app.core.analysis.pipeline.Pipeline


Enums
~~~~~

.. autoclass:: pipeline2app.core.enum.ColumnSalience
    :members:
    :undoc-members:
    :member-order: bysource

.. autoclass:: pipeline2app.core.enum.ParameterSalience
    :members:
    :undoc-members:
    :member-order: bysource

.. autoclass:: pipeline2app.core.enum.DataQuality
    :members:
    :undoc-members:
    :member-order: bysource
