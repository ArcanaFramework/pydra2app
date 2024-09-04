class Pipeline2appException(Exception):
    @property
    def msg(self):
        return self.args[0]

    @msg.setter
    def msg(self, msg):
        self.args = (msg,) + self.args[1:]


class Pipeline2appError(Pipeline2appException):
    pass


class Pipeline2appRuntimeError(Pipeline2appError):
    pass


class Pipeline2appNotBoundToAnalysisError(Pipeline2appError):
    pass


class Pipeline2appVersionError(Pipeline2appError):
    pass


class Pipeline2appRequirementNotFoundError(Pipeline2appVersionError):
    pass


class Pipeline2appVersionNotDetectableError(Pipeline2appVersionError):
    pass


class Pipeline2appEnvModuleNotLoadedError(Pipeline2appError):
    pass


class Pipeline2appMissingInputError(Pipeline2appException):
    pass


class Pipeline2appProtectedOutputConflictError(Pipeline2appError):
    pass


class Pipeline2appCantPickleAnalysisError(Pipeline2appError):
    pass


class Pipeline2appRepositoryError(Pipeline2appError):
    pass


class Pipeline2appUsageError(Pipeline2appError):
    pass


class Pipeline2appCacheError(Pipeline2appError):
    pass


class Pipeline2appDesignError(Pipeline2appError):
    pass


class NamedPipeline2appError(Pipeline2appError):
    def __init__(self, name, msg):
        super(NamedPipeline2appError, self).__init__(msg)
        self.name = name


class Pipeline2appNameError(NamedPipeline2appError):
    pass


class Pipeline2appWrongFrequencyError(NamedPipeline2appError):
    pass


class Pipeline2appIndexError(Pipeline2appError):
    def __init__(self, index, msg):
        super(Pipeline2appIndexError, self).__init__(msg)
        self.index = index


class Pipeline2appDataMatchError(Pipeline2appUsageError):
    pass


class Pipeline2appPipelinesStackError(Pipeline2appError):
    pass


class Pipeline2appMissingDataException(Pipeline2appPipelinesStackError):
    pass


class Pipeline2appOutputNotProducedException(Pipeline2appPipelinesStackError):
    """
    Raised when a given spec is not produced due to switches and inputs
    provided to the analysis
    """


class Pipeline2appInsufficientRepoDepthError(Pipeline2appError):
    pass


class Pipeline2appLicenseNotFoundError(Pipeline2appNameError):
    pass


class Pipeline2appUnresolvableFormatException(Pipeline2appException):
    pass


class Pipeline2appFileSetNotCachedException(Pipeline2appException):
    pass


class NoMatchingPipelineException(Pipeline2appException):
    pass


class Pipeline2appModulesError(Pipeline2appError):
    pass


class Pipeline2appModulesNotInstalledException(Pipeline2appException):
    pass


class Pipeline2appJobSubmittedException(Pipeline2appException):
    """
    Signifies that a pipeline has been submitted to a scheduler and
    a return value won't be returned.
    """


class Pipeline2appNoRunRequiredException(Pipeline2appException):
    """
    Used to signify when a pipeline doesn't need to be run as all
    required outputs are already present in the store
    """


class Pipeline2appFileFormatClashError(Pipeline2appError):
    """
    Used when two mismatching data formats are registered with the same
    name or extension
    """


class Pipeline2appConverterNotAvailableError(Pipeline2appError):
    "The converter required to convert between formats is not"
    "available"


class Pipeline2appReprocessException(Pipeline2appException):
    pass


class Pipeline2appWrongRepositoryError(Pipeline2appError):
    pass


class Pipeline2appIvalidParameterError(Pipeline2appError):
    pass


class Pipeline2appRequirementVersionsError(Pipeline2appError):
    pass


class Pipeline2appXnatCommandError(Pipeline2appRepositoryError):
    """
    Error in the command file used to access an XNAT repository via the XNAT
    container service.
    """


class Pipeline2appUriAlreadySetException(Pipeline2appException):
    """Raised when attempting to set the URI of an item is already set"""


class Pipeline2appDataTreeConstructionError(Pipeline2appError):
    "Error in constructing data tree by store find_rows method"


class Pipeline2appBadlyFormattedIDError(Pipeline2appDataTreeConstructionError):
    "Error attempting to extract an ID from a tree path using a user provided regex"


class Pipeline2appWrongAxesError(Pipeline2appError):
    "Provided row_frequency is not a valid member of the dataset's dimensions"


class Pipeline2appNoDirectXnatMountException(Pipeline2appException):
    "Raised when attemptint to access a file-system mount for a row that hasn't been mounted directly"
    pass


class Pipeline2appEmptyDatasetError(Pipeline2appException):
    pass


class Pipeline2appBuildError(Pipeline2appError):
    pass


class NamedError(Exception):
    def __init__(self, name, msg):
        super().__init__(msg)
        self.name = name


class NameError(NamedError):
    pass


class DataNotDerivedYetError(NamedError):
    pass


class DatatypeUnsupportedByStoreError(Pipeline2appError):
    """Raised when a data store doesn't support a given datatype"""

    def __init__(self, datatype, store):
        super().__init__(
            f"'{datatype.mime_like}' data types aren't supported by {type(store)} stores"
        )
