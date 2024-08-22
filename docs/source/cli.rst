Command-line interface
======================

Arcana's command line interface is grouped into five categories, `store`,
`dataset`, `apply`, `derive`, and `deploy`. Below these categories are the
commands that interact with Arcana's data model, processing and deployment
streams.


Store
-----

Commands used to access remove data stores and save them for further use

.. click:: pydra2app.core.cli.store:add
   :prog: pydra2app store add

.. click:: pydra2app.core.cli.store:rename
   :prog: pydra2app store rename

.. click:: pydra2app.core.cli.store:remove
   :prog: pydra2app store remove

.. click:: pydra2app.core.cli.store:refresh
   :prog: pydra2app store refresh

.. click:: pydra2app.core.cli.store:ls
   :prog: pydra2app store ls


FrameSet
--------

Commands used to define and work with datasets

.. click:: pydra2app.core.cli.dataset:define
   :prog: pydra2app dataset define

.. click:: pydra2app.core.cli.dataset:add_source
   :prog: pydra2app dataset add-source

.. click:: pydra2app.core.cli.dataset:add_sink
   :prog: pydra2app dataset add-sink

.. click:: pydra2app.core.cli.dataset:missing_items
   :prog: pydra2app dataset missing-items


Processing
----------

Commands for configuring tasks/workflows to derive artefacts from the dataset

.. click:: pydra2app.core.cli.apply:apply
   :prog: pydra2app apply pipeline

.. click:: pydra2app.core.cli.derive:derive_column
   :prog: pydra2app derive column

.. click:: pydra2app.core.cli.derive:derive_output
   :prog: pydra2app derive output

.. click:: pydra2app.core.cli.derive:menu
   :prog: pydra2app derive menu

.. click:: pydra2app.core.cli.derive:ignore_diff
   :prog: pydra2app derive ignore-diff


Deploy
------

Commands for deploying pydra2app pipelines


.. click:: pydra2app.core.cli.deploy:build
   :prog: pydra2app deploy build

.. click:: pydra2app.core.cli.deploy:test
   :prog: pydra2app deploy test

.. click:: pydra2app.core.cli.deploy:make_docs
   :prog: pydra2app deploy docs

.. click:: pydra2app.core.cli.deploy:inspect_docker_exec
   :prog: pydra2app deploy inspect-docker
