Testing
=======

After an image has been built successfully, it can be tested against previously
generated results to check for consistency with previous versions. This can be
particularly useful when updating dependency versions. Tests that don't match
previous results within a given tolerance will be flagged for manual review.

To avoid expensive runs when not necessarily (particularly within CI/CD
pipelines), in the case that the provenance data saved along the generated
reference data will be checked before running the pipelines. If the provenance
data would be unchanged (including software dependency versions), then the
pipeline test will be skipped.

Test data, both inputs to the pipeline and reference data to check against
pipeline outputs, need to be stored in separate directories for each command.
Under the pipeline data directory, there should be one or more subdirectories
for different tests of the pipeline, and in each of these subdirectories there
should be an ``inputs`` and an ``outputs`` directory, and optionally a YAML_
file named ``parameters.yml``. Inside the ``inputs`` directory there should be
file-groups named after each input of the pipeline, and likewise in the
``outputs`` directory there should be file-groups named after each output
of the pipeline. Any field inputs or outputs should be placed alongside the
file-groups in a JSON file called ``__fields__.json``.

Specifying two tests ('test1' and 'test2') for the FSL FAST example given above
(see :ref:`Building`) the directory structure would look like:

.. code-block::

     FAST
     ├── test1
     │   ├── inputs
     │   │   └── in_files.nii.gz
     │   ├── outputs
     |   │   └── fast
     |   │       ├── tissue_class_files.nii.gz
     |   │       ├── partial_volumes.nii.gz
     |   │       ├── partial-volume-files.nii.gz
     |   │       ├── bias-field.nii.gz
     |   │       └── probability-map.nii.gz
     │   └── parameters.yml
     └── test2
         ├── inputs
         │   └── in_files.nii.gz
         ├── outputs
         │   └── fast
         │       ├── tissue_class_files.nii.gz
         │       ├── partial_volumes.nii.gz
         │       ├── partial-volume-files.nii.gz
         │       ├── bias-field.nii.gz
         │       └── probability-map.nii.gz
         └── parameters.yml

To run a test via the CLI point the test command to the YAML_ configuration
file and the data directory containing the test data, e.g.

.. code-block:: console

    $ pipeline2app deploy test ./fast.yml ./fast-data
    Pipeline test 'test1' ran successfully and outputs matched saved
    Pipeline test 'test2' ran successfully and outputs matched saved

To run tests over a suite of image configurations in a directory containing a
number of YAML_ configuration files (i.e. same as building) simply provide the
directory to ``pipeline2app deploy test`` instead of the path to the YAML_ config
file and supply a directory tree containing the test data, with matching
sub-directory structure to the configuration dir. For example, given the following
directory structure for the configuration files

.. code-block::

    mri
    └── neuro
        ├── fsl.yml
        ├── mrtrix3.yml
        ...

The test data should be laid out like

.. code-block::

    mri-data
    └── neuro
        ├── fsl
        │   └── fast
        |       ├── test1
        |       │   ├── inputs
        |       │   │   └── in_files.nii.gz
        |       │   ├── outputs
        |       |   │   └── fast
        |       |   │       ├── tissue_class_files.nii.gz
        |       |   │       ├── partial_volumes.nii.gz
        |       |   │       ├── partial-volume-files.nii.gz
        |       |   │       ├── bias-field.nii.gz
        |       |   │       └── probability-map.nii.gz
        |       │   └── parameters.yml
        |       └── test2
        |           ├── inputs
        |           │   └── in_files.nii.gz
        |           ├── outputs
        |           │   └── fast
        |           │       ├── tissue_class_files.nii.gz
        |           │       ├── partial_volumes.nii.gz
        |           │       ├── partial-volume-files.nii.gz
        |           │       ├── bias-field.nii.gz
        |           │       └── probability-map.nii.gz
        |           └── parameters.yml
        └── mrtrix3
            ├── dwi2fod
            |   ├── test1
            |   |   ├── inputs
        ...

Like in the case of a single YAML_ configuration file, the CLI command to test
a suite of image/command configurations is.

.. code-block:: console

    $ pipeline2app deploy test ./mri ./mri-data --output test-results.json
    ...E..F..

While not strictly necessary, it is strongly advised to store test data alongside
image/command configurations inside some kind of version control. However, storing
large files inside vanilla Git repositories is **not recommended**, therefore, you
will probably want to use one of the extensions designed for dealing with large
files:

* `git-lfs <https://git-lfs.github.com/>`_ - integrates with GitHub but GitHub requires you to pay for storage/egest
* `git-annex <https://git-annex.branchable.com/>`_ - complicated to set up and use, even for experienced Git users, but much more flexible in your storage options.


.. _Anaconda: https://www.anaconda.com/
.. _Neurodocker: https://github.com/ReproNim/neurodocker
.. _YAML: https://yaml.org
