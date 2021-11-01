"""
Module for entities implemented using the
switch platform (https://www.home-assistant.io/integrations/switch/).
"""

import logging

from hahomematic.const import HA_PLATFORM_SWITCH, TYPE_ACTION
from hahomematic.entity import GenericEntity

LOG = logging.getLogger(__name__)


# pylint: disable=invalid-name
class HM_Switch(GenericEntity):
    """
    Implementation of a switch.
    This is a default platform that gets automatically generated.
    """

    # pylint: disable=too-many-arguments
    def __init__(self, device, unique_id, address, parameter, parameter_data):
        super().__init__(
            device=device,
            unique_id=unique_id,
            address=address,
            parameter=parameter,
            parameter_data=parameter_data,
            platform=HA_PLATFORM_SWITCH,
        )

    @property
    def STATE(self):
        if self.type == TYPE_ACTION:
            return False

        return self._state

    @STATE.setter
    def STATE(self, value):
        if self.type == TYPE_ACTION:
            self.send_value(True)
        else:
            self.send_value(value)
