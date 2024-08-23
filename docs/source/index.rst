.. _home:

Pipeline2App
============

Pipeline2App is a package for easily wrapping analysis pipelines to container images that
can be run as independent applications, such as `XNAT's container service <https://wiki.xnat.org/container-service/>`_
pipelines and `BIDS apps <https://bids-apps.neuroimaging.io/>`_ (under development).
It can be used to maintain continuous integration and deployment of pipeline suites (see
`Australian Imaging Service Pipelines <https://github.com/australian-imaging-service/pipelines-core>`_).

.. toctree::
   :maxdepth: 2
   :hidden:

   basic_usage
   building
   testing
   design
   developer

.. toctree::
   :maxdepth: 2
   :caption: Reference
   :hidden:

   CLI <cli.rst>


|

.. note::
   For the legacy version of Arcana as described in
   *Close TG, et. al. Neuroinformatics. 2020 18(1):109-129. doi:* `10.1007/s12021-019-09430-1 <https://doi.org/10.1007/s12021-019-09430-1>`_
   please see `<https://github.com/MonashBI/pipeline2app-legacy>`_.
   Conceptually, the legacy version and the versions in this repository (version >= 2.0) are similar.
   However, instead of Nipype, versions >= 2 use the Pydra_ workflow engine (Nipype's successor)
   and the syntax has been rewritten from scratch to make it more streamlined and intuitive.


.. _Pydra: http://pydra.readthedocs.io
.. _XNAT: http://xnat.org
.. _BIDS: http://bids.neuroimaging.io/
.. _`Environment Modules`: http://modules.sourceforge.net
