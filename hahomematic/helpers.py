# pylint: disable=line-too-long
"""
Helper functions used within hahomematic
"""
import logging

from hahomematic.const import (
    ATTR_HM_LIST,
    ATTR_HM_LOGIC,
    ATTR_HM_NUMBER,
    ATTR_NAME,
    ATTR_TYPE,
    ATTR_VALUE,
    HA_DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def generate_unique_id(address, parameter=None, prefix=None):
    """
    Build unique id from address and parameter.
    """
    unique_id = address.replace(':', '_').replace('-', '_')
    if parameter:
        unique_id = f"{unique_id}_{parameter}"

    if prefix:
        unique_id = f"{prefix}_{unique_id}"

    return f"{HA_DOMAIN}_{unique_id}".lower()




def make_http_credentials(username=None, password=None):
    """Build auth part for api_url."""
    credentials = ""
    if username is None:
        return credentials
    if username is not None:
        if ":" in username:
            return credentials
        credentials += username
    if credentials and password is not None:
        credentials += f":{password}"
    return f"{credentials}@"


# pylint: disable=too-many-arguments
def build_api_url(host, port, path, username=None, password=None, tls=False):
    """Build XML-RPC API URL from components."""
    credentials = make_http_credentials(username, password)
    scheme = "http"
    if not path:
        path = ""
    if path and not path.startswith("/"):
        path = f"/{path}"
    if tls:
        scheme += "s"
    return f"{scheme}://{credentials}{host}:{port}{path}"


def parse_ccu_sys_var(data):
    """Helper to parse type of system variables of CCU."""
    # pylint: disable=no-else-return
    if data[ATTR_TYPE] == ATTR_HM_LOGIC:
        return data[ATTR_NAME], data[ATTR_VALUE] == "true"
    elif data[ATTR_TYPE] == ATTR_HM_NUMBER:
        return data[ATTR_NAME], float(data[ATTR_VALUE])
    elif data[ATTR_TYPE] == ATTR_HM_LIST:
        return data[ATTR_NAME], int(data[ATTR_VALUE])
    return data[ATTR_NAME], data[ATTR_VALUE]


def get_entity_name(server, interface_id, address, parameter, unique_id) -> str:
    """generate name for entity"""
    name = server.names_cache.get(interface_id, {}).get(address, unique_id)
    if name.count(":") == 1:
        d_name = name.split(":")[0]
        p_name = parameter.title().replace("_", " ")
        c_no = name.split(":")[1]
        c_name = "" if c_no == "0" else f" ch{c_no}"
        name = f"{d_name} {p_name}{c_name}"
    else:
        d_name = name
        p_name = parameter.title().replace("_", " ")
        name = f"{d_name} {p_name}"
    return name


def get_custom_entity_name(
    server, interface_id, address, unique_id, channel_no=None
) -> str:
    """generate name for entity"""
    if channel_no and not ":" in address:
        address = f"{address}:{channel_no}"

    return server.names_cache.get(interface_id, {}).get(address, unique_id)
