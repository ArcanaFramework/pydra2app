Command-line interface
======================

Pydra2Apps's command line interface consists of a number of sub-commands under the
`pydra2app` command. To save on keystrokes the main command is also aliased to `p2a`.


.. click:: pydra2app.core.cli:bootstrap
   :prog: pydra2app bootstrap

.. click:: pydra2app.core.cli:make
   :prog: pydra2app make

.. click:: pydra2app.core.cli:plan_builds
   :prog: pydra2app plan-builds

.. click:: pydra2app.core.cli:make_docs
   :prog: pydra2app make-docs

.. click:: pydra2app.core.cli:list_images
   :prog: pydra2app list-images

.. click:: pydra2app.core.cli:inspect_docker_exec
   :prog: pydra2app inspect-docker-exec

.. click:: pydra2app.core.cli:required_packages
   :prog: pydra2app required-packages

.. click:: pydra2app.core.cli:changelog
   :prog: pydra2app changelog

.. click:: pydra2app.core.cli:pipeline_entrypoint
   :prog: pydra2app pipeline-entrypoint
