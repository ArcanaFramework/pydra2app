Command-line interface
======================

Pipeline2Apps's command line interface consists of a number of sub-commands under the
`pipeline2app` command. To save on keystrokes the main command is also aliased to `p2a`.


.. click:: pipeline2app.core.cli:bootstrap
   :prog: pipeline2app bootstrap

.. click:: pipeline2app.core.cli:make
   :prog: pipeline2app make

.. click:: pipeline2app.core.cli:make_docs
   :prog: pipeline2app make-docs

.. click:: pipeline2app.core.cli:list_images
   :prog: pipeline2app list-images

.. click:: pipeline2app.core.cli:inspect_docker_exec
   :prog: pipeline2app inspect-docker-exec

.. click:: pipeline2app.core.cli:required_packages
   :prog: pipeline2app required-packages

.. click:: pipeline2app.core.cli:changelog
   :prog: pipeline2app changelog

.. click:: pipeline2app.core.cli:pipeline_entrypoint
   :prog: pipeline2app pipeline-entrypoint
