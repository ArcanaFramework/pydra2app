Command-line interface
======================

Arcana's command line interface is grouped into five categories, `store`,
`dataset`, `apply`, `derive`, and `deploy`. Below these categories are the
commands that interact with Arcana's data model, processing and deployment
streams.


Store
-----

Commands used to access remove data stores and save them for further use

.. click:: pipeline2app.core.cli.store:add
   :prog: pipeline2app store add

.. click:: pipeline2app.core.cli.store:rename
   :prog: pipeline2app store rename

.. click:: pipeline2app.core.cli.store:remove
   :prog: pipeline2app store remove

.. click:: pipeline2app.core.cli.store:refresh
   :prog: pipeline2app store refresh

.. click:: pipeline2app.core.cli.store:ls
   :prog: pipeline2app store ls


FrameSet
--------

Commands used to define and work with datasets

.. click:: pipeline2app.core.cli.dataset:define
   :prog: pipeline2app dataset define

.. click:: pipeline2app.core.cli.dataset:add_source
   :prog: pipeline2app dataset add-source

.. click:: pipeline2app.core.cli.dataset:add_sink
   :prog: pipeline2app dataset add-sink

.. click:: pipeline2app.core.cli.dataset:missing_items
   :prog: pipeline2app dataset missing-items


Processing
----------

Commands for configuring tasks/workflows to derive artefacts from the dataset

.. click:: pipeline2app.core.cli.apply:apply
   :prog: pipeline2app apply pipeline

.. click:: pipeline2app.core.cli.derive:derive_column
   :prog: pipeline2app derive column

.. click:: pipeline2app.core.cli.derive:derive_output
   :prog: pipeline2app derive output

.. click:: pipeline2app.core.cli.derive:menu
   :prog: pipeline2app derive menu

.. click:: pipeline2app.core.cli.derive:ignore_diff
   :prog: pipeline2app derive ignore-diff


Deploy
------

Commands for deploying pipeline2app pipelines


.. click:: pipeline2app.core.cli.deploy:build
   :prog: pipeline2app deploy build

.. click:: pipeline2app.core.cli.deploy:test
   :prog: pipeline2app deploy test

.. click:: pipeline2app.core.cli.deploy:make_docs
   :prog: pipeline2app deploy docs

.. click:: pipeline2app.core.cli.deploy:inspect_docker_exec
   :prog: pipeline2app deploy inspect-docker
