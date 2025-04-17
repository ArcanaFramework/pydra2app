class Pydra2AppException(Exception):
    @property
    def msg(self):
        return self.args[0]

    @msg.setter
    def msg(self, msg):
        self.args = (msg,) + self.args[1:]


class Pydra2AppError(Pydra2AppException):
    pass


class Pydra2AppRuntimeError(Pydra2AppError):
    pass


class Pydra2AppNotBoundToAnalysisError(Pydra2AppError):
    pass


class Pydra2AppVersionError(Pydra2AppError):
    pass


class Pydra2AppRequirementNotFoundError(Pydra2AppVersionError):
    pass


class Pydra2AppVersionNotDetectableError(Pydra2AppVersionError):
    pass


class Pydra2AppEnvModuleNotLoadedError(Pydra2AppError):
    pass


class Pydra2AppMissingInputError(Pydra2AppException):
    pass


class Pydra2AppProtectedOutputConflictError(Pydra2AppError):
    pass


class Pydra2AppCantPickleAnalysisError(Pydra2AppError):
    pass


class Pydra2AppRepositoryError(Pydra2AppError):
    pass


class Pydra2AppUsageError(Pydra2AppError):
    pass


class Pydra2AppCacheError(Pydra2AppError):
    pass


class Pydra2AppDesignError(Pydra2AppError):
    pass


class NamedPydra2AppError(Pydra2AppError):
    def __init__(self, name, msg):
        super(NamedPydra2AppError, self).__init__(msg)
        self.name = name


class Pydra2AppNameError(NamedPydra2AppError):
    pass


class Pydra2AppWrongFrequencyError(NamedPydra2AppError):
    pass


class Pydra2AppIndexError(Pydra2AppError):
    def __init__(self, index, msg):
        super(Pydra2AppIndexError, self).__init__(msg)
        self.index = index


class Pydra2AppDataMatchError(Pydra2AppUsageError):
    pass


class Pydra2AppPipelinesStackError(Pydra2AppError):
    pass


class Pydra2AppMissingDataException(Pydra2AppPipelinesStackError):
    pass


class Pydra2AppOutputNotProducedException(Pydra2AppPipelinesStackError):
    """
    Raised when a given spec is not produced due to switches and inputs
    provided to the analysis
    """


class Pydra2AppInsufficientRepoDepthError(Pydra2AppError):
    pass


class Pydra2AppLicenseNotFoundError(Pydra2AppNameError):
    pass


class Pydra2AppUnresolvableFormatException(Pydra2AppException):
    pass


class Pydra2AppFileSetNotCachedException(Pydra2AppException):
    pass


class NoMatchingPipelineException(Pydra2AppException):
    pass


class Pydra2AppModulesError(Pydra2AppError):
    pass


class Pydra2AppModulesNotInstalledException(Pydra2AppException):
    pass


class Pydra2AppJobSubmittedException(Pydra2AppException):
    """
    Signifies that a pipeline has been submitted to a scheduler and
    a return value won't be returned.
    """


class Pydra2AppNoRunRequiredException(Pydra2AppException):
    """
    Used to signify when a pipeline doesn't need to be run as all
    required outputs are already present in the store
    """


class Pydra2AppFileFormatClashError(Pydra2AppError):
    """
    Used when two mismatching data formats are registered with the same
    name or extension
    """


class Pydra2AppConverterNotAvailableError(Pydra2AppError):
    "The converter required to convert between formats is not"

    "available"


class Pydra2AppReprocessException(Pydra2AppException):
    pass


class Pydra2AppWrongRepositoryError(Pydra2AppError):
    pass


class Pydra2AppIvalidParameterError(Pydra2AppError):
    pass


class Pydra2AppRequirementVersionsError(Pydra2AppError):
    pass


class Pydra2AppXnatCommandError(Pydra2AppRepositoryError):
    """
    Error in the command file used to access an XNAT repository via the XNAT
    container service.
    """


class Pydra2AppUriAlreadySetException(Pydra2AppException):
    """Raised when attempting to set the URI of an item is already set"""


class Pydra2AppDataTreeConstructionError(Pydra2AppError):
    "Error in constructing data tree by store find_rows method"


class Pydra2AppBadlyFormattedIDError(Pydra2AppDataTreeConstructionError):
    "Error attempting to extract an ID from a tree path using a user provided regex"


class Pydra2AppWrongAxesError(Pydra2AppError):
    "Provided row_frequency is not a valid member of the dataset's dimensions"


class Pydra2AppNoDirectXnatMountException(Pydra2AppException):
    "Raised when attemptint to access a file-system mount for a row that hasn't been mounted directly"

    pass


class Pydra2AppEmptyDatasetError(Pydra2AppException):
    pass


class Pydra2AppBuildError(Pydra2AppError):
    pass


class NamedError(Exception):
    def __init__(self, name, msg):
        super().__init__(msg)
        self.name = name


class NameError(NamedError):
    pass


class DataNotDerivedYetError(NamedError):
    pass


class DatatypeUnsupportedByStoreError(Pydra2AppError):
    """Raised when a data store doesn't support a given datatype"""

    def __init__(self, datatype, store):
        super().__init__(
            f"'{datatype.mime_like}' data types aren't supported by {type(store)} stores"
        )
