Basic usage
===========

The CLI command to build the image from the YAML_ configuration is

.. code-block:: console

    $ pipeline2app make xnat 'your-pipeline-config.yml'
    Successfully built "FSL" image with ["fast"] commands

To build a suite of pipelines from a series of YAML_ files stored in a directory tree
simply provide the root directory instead and Arcana will walk the sub-directories
and attempt to build any YAML_ files it finds, e.g.

.. code-block:: console

    $ pipeline2app make xnat 'config-root-dir'
    ./config-root-dir/mri/neuro/fsl.yml: FSL [fast]
    ./config-root-dir/mri/neuro/mrtrix3.yml: MRtrix3 [dwi2fod, dwi2tensor, tckgen]
    ./config-root-dir/mri/neuro/freesurfer.yml: Freesurfer [recon-all]
    ...


.. _Anaconda: https://www.anaconda.com/
.. _Neurodocker: https://github.com/ReproNim/neurodocker
.. _YAML: https://yaml.org
