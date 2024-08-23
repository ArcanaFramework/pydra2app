Designing Apps
==============

Command definitions
-------------------

The XNAT container service uses `command configuration files <https://wiki.xnat.org/container-service/command-resolution-122978876.html>`_
saved in the `org.nrg.commands` image label to resolve metadata for the pipelines
that available on a given Docker image. The :meth:`.XnatViaCS.generate_xnat_command`
method is used to generate the JSON metadata to be saved in this field.

There are four key fields that will determine the functionality of the command
(the rest are metadata fields that are exposed to the XNAT UI):

* ``task``
* ``inputs``
* ``outputs``
* ``parameters``

The ``task`` keyword argument should be the path to an installed
Python module containing a Pydra task followed by a colon and the name of
the task, e.g. ``pydra.tasks.fsl.preprocess.fast:Fast``. Note that Arcana
will attempt to resolve the package that contains the Pydra task and install the
same version (including local development versions) within the Anaconda_ environment
in the image. ``inputs`` and ``parameters`` expose text boxes in the XNAT dialog when
the pipelines are run. ``outputs`` determine where the outputs will
be stored in the XNAT data tree.

Inputs prompt the user to enter selection criteria for
input data and are used by the entrypoint of the Docker containers to add
source columns to the frameset (see FrameTree_). They are specified by
4-tuple consisting of

* name of field in the pydra task input interface
* datatype required by pydra task
* description of input that will be exposed to the XNAT UI
* the row row_frequency of the column (see FrameTree_)

Parameters are passed directly through the pipeline add method (see FrameTree_) that
is run in the container, and consist of a 2-tuple with

* name of field in the pydra task input interface
* description of parameters that will be exposed to the XNAT UI

Outputs do not show up in the XNAT dialog and are specified by a 3-tuple:

* name of field in the pydra task output interface
* datatype produced by pydra task
* destination path (slashes are permitted interpreted as a relative path from the derivatives root)

.. .. code-block:: python

..     import json
..     from pipeline2app.xnat.deploy import XnatCommand
..     from pipeline2app.medimage.data import Clinical
..     from fileformats.medimage.data import NiftiGz

..     xnat_command = XnatCommand(
..         name='example_pipeline',
..         task='pydra.tasks.fsl.preprocess.fast:FAST',
..         image_tag='example/0.1',
..         description=(
..             "FAST (FMRIB's Automated Segmentation Tool) segments a 3D image of "
..             "the brain into different tissue types (Grey Matter, White Matter, "
..             "CSF, etc.), whilst also correcting for spatial intensity variations "
..             "(also known as bias field or RF inhomogeneities)."),
..         version='6.0-1',
..         info_url='https://fsl.fmrib.ox.ac.uk/fsl/fslwiki/FAST',
..         inputs={
..             "field": 'in_files', NiftiGz, 'File to segment', 'session'),
..             ('number_of_classes', int, 'Number of classes', 'session')],
..         outputs=[
..             ('tissue_class_files', NiftiGz, 'fast/tissue-classes'),
..             ('partial_volume_map', NiftiGz, 'fast/partial-volumes'),
..             ('partial_volume_files', NiftiGz, 'fast/partial-volume-files'),
..             ('bias_field', NiftiGz, 'fast/bias-field'),
..             ('probability_maps', NiftiGz, 'fast/probability-map')],
..         parameters=[
..             ('use_priors', 'Use priors'),
..             ('bias_lowpass', 'Low-pass filter bias field')],
..         configuration=[  # If different from the Pydra task
..             ('output_biasfield', True),
..             ('output_biascorrected', True),
..             ('bias_lowpass', 5.0)],
..         row_frequency='session')

..         with open("/path/to/a/file", "w") as f:
..             json.dump(f, xnat_command.make_json())

When working with the CLI, command configurations are stored in YAML_ format,
with keys matching the arguments of :meth:`XnatViaCS.generate_xnat_command`.

.. note::
    ``image_tag`` and ``registry`` are omitted from the YAML representation
    of the commands as they are provided by the image configuration
    (see :ref:`Building`)


.. _FrameTree: https://arcanaframework.github.io/frametree
.. _Anaconda: https://www.anaconda.com/
.. _Neurodocker: https://github.com/ReproNim/neurodocker
.. _YAML: https://yaml.org
