.. _home:

Pipeline2App
============

Pipeline2App is a package for easily wrapping analysis pipelines to container images that
can be run as independent applications, such as `XNAT's container service <https://wiki.xnat.org/container-service/>`_
pipelines and `BIDS apps <https://bids-apps.neuroimaging.io/>`_ (under development).
It can be used to maintain continuous integration and deployment of pipeline suites (see
`Australian Imaging Service Pipelines <https://github.com/australian-imaging-service/pipelines-core>`_).

Installation
------------

Pipeline2App requires a recent version of Python (>=3.8) to run. So you may
need to upgrade your Python version before it is installed. It can be installed along
with its dependencies from the `Python Package Index <http://pypi.org>`_ using *Pip3*

.. code-block:: console

    $ pip3 install pipeline2app

To add support for building XNAT_ container service Docker images you will also need to
install the extension module ``pipeline2app-xnat``, e.g.


.. code-block:: console

    $ pip3 install pipeline2app-xnat


Licence
-------

Pipeline2App is licenced under the `Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International Public License <https://creativecommons.org/licenses/by-nc-sa/4.0/>`_
(see `LICENCE <https://raw.githubusercontent.com/Australian-Imaging-Service/pipeline2app/master/LICENSE>`_).
Non-commercial usage is permitted freely on the condition that FrameTree is
appropriately acknowledged in related publications.

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


.. _Pydra: http://pydra.readthedocs.io
.. _XNAT: http://xnat.org
.. _BIDS: http://bids.neuroimaging.io/
.. _`Environment Modules`: http://modules.sourceforge.net
