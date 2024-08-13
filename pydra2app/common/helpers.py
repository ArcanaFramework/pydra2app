import re


def value_from_stdout(field, stdout):
    """Extract the output from the stdout using the field name and the output directory
    to be used as a callable in output specs

    Parameters
    ----------
    field : attrs.field
        the output field
    stdout : str
        the stdout from the container

    Returns
    -------
    value : Any
        the value to be used as the output
    """
    try:
        regex = field.metadata["value_regex"]
    except KeyError:
        value = stdout
    else:
        value = re.match(regex, stdout)
    if field.type:
        value = field.type(value)
    return value
