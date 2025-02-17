"""Functions for entity creation."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime
import logging
from typing import Any, Final, Generic, TypeVar, cast

import voluptuous as vol

from hahomematic import central_unit as hmcu, client as hmcl, support as hms
from hahomematic.const import (
    EVENT_ADDRESS,
    EVENT_CHANNEL_NO,
    EVENT_DEVICE_TYPE,
    EVENT_INTERFACE_ID,
    EVENT_PARAMETER,
    EVENT_VALUE,
    INIT_DATETIME,
    KEY_CHANNEL_OPERATION_MODE_VISIBILITY,
    MAX_CACHE_AGE,
    NO_CACHE_ENTRY,
    PARAM_CHANNEL_OPERATION_MODE,
    HmCallSource,
    HmDescription,
    HmEntityUsage,
    HmFlag,
    HmOperations,
    HmParamsetKey,
    HmPlatform,
    HmType,
)
from hahomematic.platforms import device as hmd
from hahomematic.platforms.support import (
    EntityNameData,
    PayloadMixin,
    config_property,
    convert_value,
    generate_channel_unique_identifier,
    value_property,
)

_LOGGER = logging.getLogger(__name__)

_CONFIGURABLE_CHANNEL: Final[tuple[str, ...]] = (
    "KEY_TRANSCEIVER",
    "MULTI_MODE_INPUT_TRANSMITTER",
)

_FIX_UNIT_REPLACE: Final[dict[str, str]] = {
    '"': "",
    "100%": "%",
    "% rF": "%",
    "degree": "°C",
    "Lux": "lx",
    "m3": "m³",
}

_FIX_UNIT_BY_PARAM: Final[dict[str, str]] = {
    "ACTUAL_TEMPERATURE": "°C",
    "CURRENT_ILLUMINATION": "lx",
    "HUMIDITY": "%",
    "ILLUMINATION": "lx",
    "LEVEL": "%",
    "MASS_CONCENTRATION_PM_10_24H_AVERAGE": "µg/m³",
    "MASS_CONCENTRATION_PM_1_24H_AVERAGE": "µg/m³",
    "MASS_CONCENTRATION_PM_2_5_24H_AVERAGE": "µg/m³",
    "OPERATING_VOLTAGE": "V",
    "RSSI_DEVICE": "dBm",
    "RSSI_PEER": "dBm",
    "SUNSHINEDURATION": "min",
    "WIND_DIRECTION": "°",
    "WIND_DIRECTION_RANGE": "°",
}

HM_EVENT_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(EVENT_ADDRESS): str,
        vol.Required(EVENT_CHANNEL_NO): int,
        vol.Required(EVENT_DEVICE_TYPE): str,
        vol.Required(EVENT_INTERFACE_ID): str,
        vol.Required(EVENT_PARAMETER): str,
        vol.Optional(EVENT_VALUE): vol.Any(bool, int),
    }
)


class CallbackEntity(ABC):
    """Base class for callback entities."""

    _attr_platform: HmPlatform

    def __init__(self, unique_identifier: str) -> None:
        """Init the callback entity."""
        self._attr_unique_identifier: Final = unique_identifier
        self._update_callbacks: list[Callable] = []
        self._remove_callbacks: list[Callable] = []

    @property
    @abstractmethod
    def available(self) -> bool:
        """Return the availability of the device."""

    @config_property
    @abstractmethod
    def full_name(self) -> str:
        """Return the full name of the entity."""

    @config_property
    @abstractmethod
    def name(self) -> str | None:
        """Return the name of the entity."""

    @config_property
    def platform(self) -> HmPlatform:
        """Return, the platform of the entity."""
        return self._attr_platform

    @config_property
    def unique_identifier(self) -> str:
        """Return the unique_identifier."""
        return self._attr_unique_identifier

    @config_property
    def usage(self) -> HmEntityUsage:
        """Return the entity usage."""
        return HmEntityUsage.ENTITY

    @config_property
    def enabled_default(self) -> bool:
        """Return, if entity should be enabled based on usage attribute."""
        return self.usage in (
            HmEntityUsage.CE_PRIMARY,
            HmEntityUsage.ENTITY,
            HmEntityUsage.EVENT,
        )

    def register_update_callback(self, update_callback: Callable) -> None:
        """Register update callback."""
        if callable(update_callback):
            self._update_callbacks.append(update_callback)

    def unregister_update_callback(self, update_callback: Callable) -> None:
        """Unregister update callback."""
        if update_callback in self._update_callbacks:
            self._update_callbacks.remove(update_callback)

    def register_remove_callback(self, remove_callback: Callable) -> None:
        """Register the remove callback."""
        if callable(remove_callback) and remove_callback not in self._remove_callbacks:
            self._remove_callbacks.append(remove_callback)

    def unregister_remove_callback(self, remove_callback: Callable) -> None:
        """Unregister the remove callback."""
        if remove_callback in self._remove_callbacks:
            self._remove_callbacks.remove(remove_callback)

    def update_entity(self, *args: Any, **kwargs: Any) -> None:
        """Do what is needed when the value of the entity has been updated."""
        for _callback in self._update_callbacks:
            _callback(*args, **kwargs)

    def remove_entity(self, *args: Any) -> None:
        """Do what is needed when the entity has been removed."""
        for _callback in self._remove_callbacks:
            _callback(*args)


class BaseEntity(CallbackEntity, PayloadMixin):
    """Base class for regular entities."""

    def __init__(
        self,
        device: hmd.HmDevice,
        unique_identifier: str,
        channel_no: int | None,
        is_in_multiple_channels: bool,
    ) -> None:
        """Initialize the entity."""
        PayloadMixin.__init__(self)
        super().__init__(unique_identifier=unique_identifier)
        self.device: Final = device
        self._attr_channel_no: Final = channel_no
        self._attr_channel_address: Final[str] = hms.get_channel_address(
            device_address=device.device_address, channel_no=channel_no
        )
        self._attr_channel_unique_identifier: Final = generate_channel_unique_identifier(
            central=device.central, address=self._attr_channel_address
        )
        self._attr_is_in_multiple_channels: Final = is_in_multiple_channels
        self._central: Final[hmcu.CentralUnit] = device.central
        self._channel_type: Final = str(device.channels[self._attr_channel_address].type)
        self._attr_function: Final = self._central.device_details.get_function_text(
            address=self._attr_channel_address
        )
        self._client: Final[hmcl.Client] = device.central.get_client(
            interface_id=device.interface_id
        )

        self._attr_usage: HmEntityUsage = self._get_entity_usage()
        entity_name_data: Final = self._get_entity_name()
        self._attr_channel_name: Final = entity_name_data.channel_name
        self._attr_full_name: Final = entity_name_data.full_name
        self._attr_name: Final = entity_name_data.entity_name

    @property
    def address_path(self) -> str:
        """Return the address pass of the entity."""
        return f"{self._attr_platform}/{self.device.interface_id}/{self._attr_unique_identifier}/"

    @property
    def available(self) -> bool:
        """Return the availability of the device."""
        return self.device.available

    @config_property
    def channel_address(self) -> str:
        """Return the channel_address of the entity."""
        return self._attr_channel_address

    @config_property
    def channel_name(self) -> str:
        """Return the channel_name of the entity."""
        return self._attr_channel_name

    @config_property
    def channel_no(self) -> int | None:
        """Return the channel_no of the entity."""
        return self._attr_channel_no

    @config_property
    def channel_unique_identifier(self) -> str:
        """Return the channel_unique_identifier of the entity."""
        return self._attr_channel_unique_identifier

    @config_property
    def function(self) -> str | None:
        """Return the function of the entity."""
        return self._attr_function

    @config_property
    def full_name(self) -> str:
        """Return the full name of the entity."""
        return self._attr_full_name

    @config_property
    def is_in_multiple_channels(self) -> bool:
        """Return the parameter/CE is also in multiple channels."""
        return self._attr_is_in_multiple_channels

    @config_property
    def name(self) -> str | None:
        """Return the name of the entity."""
        return self._attr_name

    @config_property
    def usage(self) -> HmEntityUsage:
        """Return the entity usage."""
        return self._attr_usage

    def set_usage(self, usage: HmEntityUsage) -> None:
        """Set the entity usage."""
        self._attr_usage = usage

    def update_entity(self, *args: Any, **kwargs: Any) -> None:
        """Do what is needed when the value of the entity has been updated."""
        super().update_entity(*args, **kwargs)
        self._central.fire_entity_data_event_callback(
            interface_id=self.device.interface_id, entity=self
        )

    @abstractmethod
    async def load_entity_value(
        self, call_source: HmCallSource, max_age_seconds: int = MAX_CACHE_AGE
    ) -> None:
        """Init the entity data."""

    @abstractmethod
    def _get_entity_name(self) -> EntityNameData:
        """Generate the name for the entity."""

    @abstractmethod
    def _get_entity_usage(self) -> HmEntityUsage:
        """Generate the usage for the entity."""

    def __str__(self) -> str:
        """Provide some useful information."""
        return (
            f"address_path: {self.address_path}, type: {self.device.device_type}, "
            f"name: {self.full_name}"
        )


InputParameterT = TypeVar("InputParameterT", bool, int, float, str, int | str, float | str, None)
ParameterT = TypeVar("ParameterT", bool, int, float, str, int | str, None)


class BaseParameterEntity(Generic[ParameterT, InputParameterT], BaseEntity):
    """Base class for stateless entities."""

    def __init__(
        self,
        device: hmd.HmDevice,
        unique_identifier: str,
        channel_address: str,
        paramset_key: str,
        parameter: str,
        parameter_data: dict[str, Any],
    ) -> None:
        """Initialize the entity."""
        self._attr_paramset_key: Final[str] = paramset_key
        # required for name in BaseEntity
        self._attr_parameter: Final[str] = parameter

        super().__init__(
            device=device,
            unique_identifier=unique_identifier,
            channel_no=hms.get_channel_no(address=channel_address),
            is_in_multiple_channels=device.central.paramset_descriptions.is_in_multiple_channels(
                channel_address=channel_address, parameter=parameter
            ),
        )
        self._attr_value: ParameterT | None = None
        self._attr_last_update: datetime = INIT_DATETIME
        self._attr_state_uncertain: bool = True
        self._assign_parameter_data(parameter_data=parameter_data)

    def _assign_parameter_data(self, parameter_data: dict[str, Any]) -> None:
        """Assign parameter data to instance variables."""
        self._attr_type: HmType = HmType(parameter_data[HmDescription.TYPE])
        self._attr_value_list: tuple[str, ...] | None = None
        if HmDescription.VALUE_LIST in parameter_data:
            self._attr_value_list = tuple(parameter_data[HmDescription.VALUE_LIST])
        self._attr_max: ParameterT = self._convert_value(parameter_data[HmDescription.MAX])
        self._attr_min: ParameterT = self._convert_value(parameter_data[HmDescription.MIN])
        self._attr_default: ParameterT = self._convert_value(
            parameter_data.get(HmDescription.DEFAULT, self._attr_min)
        )
        flags: int = parameter_data[HmDescription.FLAGS]
        self._attr_visible: bool = flags & HmFlag.VISIBLE == HmFlag.VISIBLE
        self._attr_service: bool = flags & HmFlag.SERVICE == HmFlag.SERVICE
        self._attr_operations: int = parameter_data[HmDescription.OPERATIONS]
        self._attr_special: dict[str, Any] | None = parameter_data.get(HmDescription.SPECIAL)
        self._attr_raw_unit: str | None = parameter_data.get(HmDescription.UNIT)
        self._attr_unit: str | None = self._fix_unit(raw_unit=self._attr_raw_unit)

    @config_property
    def default(self) -> ParameterT:
        """Return default value."""
        return self._attr_default

    @config_property
    def hmtype(self) -> HmType:
        """Return the HomeMatic type."""
        return self._attr_type

    @config_property
    def is_unit_fixed(self) -> bool:
        """Return if the unit is fixed."""
        return self._attr_raw_unit != self._attr_unit

    @config_property
    def max(self) -> ParameterT:
        """Return max value."""
        return self._attr_max

    @config_property
    def min(self) -> ParameterT:
        """Return min value."""
        return self._attr_min

    @config_property
    def multiplier(self) -> int:
        """Return multiplier value."""
        return 100 if self._attr_raw_unit and self._attr_raw_unit == "100%" else 1

    @config_property
    def parameter(self) -> str:
        """Return parameter name."""
        return self._attr_parameter

    @config_property
    def paramset_key(self) -> str:
        """Return paramset_key name."""
        return self._attr_paramset_key

    @config_property
    def raw_unit(self) -> str | None:
        """Return raw unit value."""
        return self._attr_raw_unit

    @property
    def is_readable(self) -> bool:
        """Return, if entity is readable."""
        return bool(self._attr_operations & HmOperations.READ)

    @value_property
    def is_valid(self) -> bool:
        """Return, if the value of the entity is valid based on the last updated datetime."""
        return self._attr_last_update > INIT_DATETIME

    @property
    def is_writeable(self) -> bool:
        """Return, if entity is writeable."""
        return bool(self._attr_operations & HmOperations.WRITE)

    @value_property
    def last_update(self) -> datetime:
        """Return the last updated datetime value."""
        return self._attr_last_update

    @value_property
    def state_uncertain(self) -> bool:
        """Return, if the state is uncertain."""
        return self._attr_state_uncertain

    @value_property
    def value(self) -> ParameterT | None:
        """Return the value of the entity."""
        return self._attr_value

    @property
    def supports_events(self) -> bool:
        """Return, if entity is supports events."""
        return bool(self._attr_operations & HmOperations.EVENT)

    @config_property
    def unit(self) -> str | None:
        """Return unit value."""
        return self._attr_unit

    @value_property
    def value_list(self) -> tuple[str, ...] | None:
        """Return the value_list."""
        return self._attr_value_list

    @property
    def visible(self) -> bool:
        """Return the if entity is visible in ccu."""
        return self._attr_visible

    @property
    def _channel_operation_mode(self) -> str | None:
        """Return the channel operation mode if available."""
        cop: BaseParameterEntity | None = self.device.generic_entities.get(
            (self._attr_channel_address, PARAM_CHANNEL_OPERATION_MODE)
        )
        if cop and cop.value:
            return str(cop.value)
        return None

    @property
    def _enabled_by_channel_operation_mode(self) -> bool | None:
        """Return, if the entity/event must be enabled."""
        if self._channel_type not in _CONFIGURABLE_CHANNEL:
            return None
        if self._attr_parameter not in KEY_CHANNEL_OPERATION_MODE_VISIBILITY:
            return None
        if (cop := self._channel_operation_mode) is None:
            return None
        return cop in KEY_CHANNEL_OPERATION_MODE_VISIBILITY[self._attr_parameter]

    def _fix_unit(self, raw_unit: str | None) -> str | None:
        """Replace given unit."""
        if new_unit := _FIX_UNIT_BY_PARAM.get(self._attr_parameter):
            return new_unit
        if not raw_unit:
            return None
        for check, fix in _FIX_UNIT_REPLACE.items():
            if check in raw_unit:
                return fix
        return raw_unit

    @abstractmethod
    def event(self, value: Any) -> None:
        """Handle event for which this handler has subscribed."""

    async def load_entity_value(
        self, call_source: HmCallSource, max_age_seconds: int = MAX_CACHE_AGE
    ) -> None:
        """Init the entity data."""
        if hms.updated_within_seconds(
            last_update=self._attr_last_update, max_age_seconds=max_age_seconds
        ):
            return

        # Check, if entity is readable
        if not self.is_readable:
            return

        self.update_value(
            value=await self.device.value_cache.get_value(
                channel_address=self._attr_channel_address,
                paramset_key=self._attr_paramset_key,
                parameter=self._attr_parameter,
                call_source=call_source,
            )
        )

    def update_value(self, value: Any) -> None:
        """Update value of the entity."""
        if value == NO_CACHE_ENTRY:
            if self.last_update != INIT_DATETIME:
                self._attr_state_uncertain = True
                self.update_entity()
            return
        self._attr_value = self._convert_value(value)
        self._attr_state_uncertain = False
        self._set_last_update()
        self.update_entity()

    def update_parameter_data(self) -> None:
        """Update parameter data."""
        self._assign_parameter_data(
            parameter_data=self.device.central.paramset_descriptions.get_parameter_data(
                interface_id=self.device.interface_id,
                channel_address=self._attr_channel_address,
                paramset_key=self._attr_paramset_key,
                parameter=self._attr_parameter,
            )
        )

    def _convert_value(self, value: Any) -> ParameterT:
        """Convert to value to ParameterT."""
        if value is None:
            return None  # type: ignore[return-value]
        try:
            if (
                self._attr_type == HmType.BOOL
                and self._attr_value_list is not None
                and value is not None
                and isinstance(value, str)
            ):
                return convert_value(  # type: ignore[no-any-return]
                    value=self._attr_value_list.index(value),
                    target_type=self._attr_type,
                    value_list=self.value_list,
                )
            return convert_value(  # type: ignore[no-any-return]
                value=value, target_type=self._attr_type, value_list=self.value_list
            )
        except ValueError:  # pragma: no cover
            _LOGGER.debug(
                "CONVERT_VALUE: conversion failed for %s, %s, %s, value: [%s]",
                self.device.interface_id,
                self._attr_channel_address,
                self._attr_parameter,
                value,
            )
            return None  # type: ignore[return-value]

    def get_event_data(self, value: Any = None) -> dict[str, Any]:
        """Get the event_data."""
        event_data = {
            EVENT_ADDRESS: self.device.device_address,
            EVENT_CHANNEL_NO: self._attr_channel_no,
            EVENT_DEVICE_TYPE: self.device.device_type,
            EVENT_INTERFACE_ID: self.device.interface_id,
            EVENT_PARAMETER: self._attr_parameter,
        }
        if value is not None:
            event_data[EVENT_VALUE] = value
        return cast(dict[str, Any], HM_EVENT_DATA_SCHEMA(event_data))

    def _set_last_update(self) -> None:
        """Set last_update to current datetime."""
        self._attr_last_update = datetime.now()


class CallParameterCollector:
    """Create a Paramset based on given generic entities."""

    def __init__(self, client: hmcl.Client) -> None:
        """Init the generator."""
        self._client: Final = client
        self._use_put_paramset: bool = True
        self._paramsets: Final[dict[str, dict[str, Any]]] = {}

    def add_entity(
        self, entity: BaseParameterEntity, value: Any, use_put_paramset: bool = True
    ) -> None:
        """Add a generic entity."""
        if use_put_paramset is False:
            self._use_put_paramset = False
        if entity.channel_address not in self._paramsets:
            self._paramsets[entity.channel_address] = {}
        self._paramsets[entity.channel_address][entity.parameter] = value

    async def send_data(self) -> bool:
        """Send data to backend."""
        for channel_address, paramset in self._paramsets.items():
            if len(paramset.values()) == 1 or self._use_put_paramset is False:
                for parameter, value in paramset.items():
                    if not await self._client.set_value(
                        channel_address=channel_address,
                        paramset_key=HmParamsetKey.VALUES,
                        parameter=parameter,
                        value=value,
                    ):
                        return False  # pragma: no cover
            elif not await self._client.put_paramset(
                address=channel_address, paramset_key=HmParamsetKey.VALUES, value=paramset
            ):
                return False  # pragma: no cover
        return True
