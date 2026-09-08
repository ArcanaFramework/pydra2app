Building
========

Dockerfiles for pipeline images are created using Neurodocker_
and can therefore work with any Debian/Ubuntu or Red-Hat based images
(ensuring that the value for ``base_image>package_manager`` is set to the correct value,
i.e.  ``"apt"`` for Debian based or ``"yum"`` for Red-Hat based). Arcana installs
itself into the Docker image within an Anaconda_ environment named "pydra2app". Therefore,
it shouldn't conflict with packages on existing Docker images for third-party
pipelines.

Extending the YAML_ format used to define the command configurations,
the full configuration required to build an XNAT docker image looks like

.. code-block:: yaml

    schema_version: 1.0
    title: FMRIB Scientific Library (FSL)
    version:
        package: &package_version '6.0.1'
        build: '1'
    authors:
        - name: Thomas G. Close
          email: thomas.close@sydney.edu.au
    base_image:
        name: brainlife/fsl'
        tag: *package_version
        package_manager: apt
    packages:
        neurodocker:
            dcm2niix: v1.0.20201102
        pip:
            pydra-dcm2niix:  # Uses the default version on PyPI
    docs:
        info_url: https://fsl.fmrib.ox.ac.uk/fsl/fslwiki
    command:
        task: pydra.tasks.fsl.preprocess.fast:FAST
        description:
            FAST (FMRIBs Automated Segmentation Tool) segments a 3D image of
            the brain into different tissue types (Grey Matter, White Matter,
            CSF, etc.), whilst also correcting for spatial intensity variations
            (also known as bias field or RF inhomogeneities).
        inputs:
            in_files:
              datatype: medimage/nifti-gz
              column_defaults:
                datatype: medimage/dicom-series
              help: Anatomical image to segment into different tissues
        outputs:
            tissue_classes:
              datatype: medimage/nifti-gz
              path: fast/tissue-classes
              help: Segmented tissue classes
            probability_maps:
              datatype: medimage/nifti-gz
              path: fast/probability-map
              help: Probability maps for tissue classes
        parameters:
            use_priors:
              help: Use priors in tissue estimation
            bias_lowpass:
              help: Low-pass filter bias field
        configuration:
            output_biasfield: true
            bias_lowpass: 5.0
        operates_on: session


The CLI command to build the image from the YAML_ configuration is

.. code-block:: console

    $ pydra2app make xnat 'your-pipeline-config.yml'
    Successfully built "FSL" image with ["fast"] commands

To build a suite of pipelines from a series of YAML_ files stored in a directory tree
simply provide the root directory instead and Arcana will walk the sub-directories
and attempt to build any YAML_ files it finds, e.g.

.. code-block:: console

    $ pydra2app make xnat 'config-root-dir'
    ./config-root-dir/mri/neuro/fsl.yml: FSL [fast]
    ./config-root-dir/mri/neuro/mrtrix3.yml: MRtrix3 [dwi2fod, dwi2tensor, tckgen]
    ./config-root-dir/mri/neuro/freesurfer.yml: Freesurfer [recon-all]
    ...

To inspect the tree without building and produce a JSON build matrix, use
``plan-builds``:

.. code-block:: console

    $ pydra2app plan-builds xnat 'config-root-dir' --registry ghcr.io
    {
      "build": [
        "mri/neuro/fsl"
      ],
      "unchanged": [
        "mri/neuro/freesurfer"
      ]
    }

The command fails if a published spec changed without a version increment or if
the spec version is older than the latest published image.

Pydra2App labels newly built images with
``org.pydra2app.spec-sha256``, a SHA-256 checksum of the canonical release
content. The ``version`` and ``pydra2app_version`` fields are excluded from this
checksum. As with existing spec comparison, mapping keys and collection values
are order independent, and repeated identical collection values are ignored.
Canonicalization rejects cyclic YAML aliases and bounds the traversal depth and
node count. To compare a same-version published image, ``plan-builds`` uses the
following order:

#. Read the checksum label from the image's OCI config blob.
#. For older unlabeled images, inspect all OCI layers no larger than 1 MiB for
   ``/pydra2app-spec.yaml``.
#. If lightweight inspection cannot decide, warn and fall back to pulling the
   complete image.

Manifest, config, and candidate layer blobs are verified against their declared
SHA-256 digests. Both candidate compressed layers and the uncompressed spec member
are limited to 1 MiB, and gzip expansion is limited to 8 MiB. Larger, unsupported,
or obscured candidates trigger the full-pull fallback rather than risking a stale
comparison. GHCR uses the configured access token when authentication is required,
while public images can be inspected anonymously.

To inspect only specs selected by a workflow while preserving their paths relative
to the specification root, repeat ``--spec``. Extensions may be omitted:

.. code-block:: console

    $ pydra2app plan-builds xnat 'config-root-dir' \
        --registry ghcr.io \
        --spec quality-control/phi-finder \
        --spec mri/human/neuro/monai/example



Autodocs
--------

Documentation can be automatically generated using from the
pipeline configuration YAML_ files using

.. code-block:: console

    $ pydra2app make-docs <path-to-yaml-or-directory> <docs-output-dir>

Generated HTML documents will be placed in the output dir, with pipelines
organised hierarchically to match the structure of the source directory.


.. _Anaconda: https://www.anaconda.com/
.. _Neurodocker: https://github.com/ReproNim/neurodocker
.. _YAML: https://yaml.org
