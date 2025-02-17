"""
Module for entities implemented using the light platform.

See https://www.home-assistant.io/integrations/light/.
"""
from __future__ import annotations

from abc import abstractmethod
import math
from typing import Any, Final, TypedDict

from hahomematic.const import (
    HM_ARG_OFF,
    HM_ARG_ON,
    HM_ARG_ON_TIME,
    HmEntityUsage,
    HmEvent,
    HmPlatform,
)
from hahomematic.decorators import bind_collector
from hahomematic.platforms import device as hmd
from hahomematic.platforms.custom import definition as hmed
from hahomematic.platforms.custom.const import (
    FIELD_CHANNEL_COLOR,
    FIELD_CHANNEL_LEVEL,
    FIELD_COLOR,
    FIELD_COLOR_BEHAVIOUR,
    FIELD_COLOR_LEVEL,
    FIELD_COLOR_TEMPERATURE,
    FIELD_DEVICE_OPERATION_MODE,
    FIELD_DIRECTION,
    FIELD_EFFECT,
    FIELD_HUE,
    FIELD_LEVEL,
    FIELD_ON_TIME_UNIT,
    FIELD_ON_TIME_VALUE,
    FIELD_PROGRAM,
    FIELD_RAMP_TIME_TO_OFF_UNIT,
    FIELD_RAMP_TIME_TO_OFF_VALUE,
    FIELD_RAMP_TIME_UNIT,
    FIELD_RAMP_TIME_VALUE,
    FIELD_SATURATION,
    HmEntityDefinition,
)
from hahomematic.platforms.custom.entity import CustomEntity
from hahomematic.platforms.custom.support import CustomConfig, ExtendedConfig
from hahomematic.platforms.entity import CallParameterCollector
from hahomematic.platforms.generic.action import HmAction
from hahomematic.platforms.generic.number import HmFloat, HmInteger
from hahomematic.platforms.generic.select import HmSelect
from hahomematic.platforms.generic.sensor import HmSensor
from hahomematic.platforms.support import OnTimeMixin, config_property, value_property

_HM_ARG_BRIGHTNESS: Final = "brightness"
_HM_ARG_COLOR_NAME: Final = "color_name"
_HM_ARG_COLOR_TEMP: Final = "color_temp"
_HM_ARG_CHANNEL_COLOR: Final = "channel_color"
_HM_ARG_CHANNEL_LEVEL: Final = "channel_level"
_HM_ARG_EFFECT: Final = "effect"
_HM_ARG_HS_COLOR: Final = "hs_color"
_HM_ARG_RAMP_TIME: Final = "ramp_time"

_DOM_PWM: Final = "4_PWM"
_DOM_RGB: Final = "RGB"
_DOM_RGBW: Final = "RGBW"
_DOM_TUNABLE_WHITE: Final = "2_TUNABLE_WHITE"

_HM_EFFECT_OFF: Final = "Off"

_HM_MAX_MIREDS: Final = 500
_HM_MIN_MIREDS: Final = 153

_HM_DIMMER_OFF: Final = 0.0

_TIME_UNIT_SECONDS: Final = 0
_TIME_UNIT_MINUTES: Final = 1
_TIME_UNIT_HOURS: Final = 2

_COLOR_BEHAVIOUR_DO_NOT_CARE: Final = "DO_NOT_CARE"
_COLOR_BEHAVIOUR_OFF: Final = "OFF"
_COLOR_BEHAVIOUR_OLD_VALUE: Final = "OLD_VALUE"
_COLOR_BEHAVIOUR_ON: Final = "ON"

_COLOR_BLACK: Final = "BLACK"
_COLOR_BLUE: Final = "BLUE"
_COLOR_DO_NOT_CARE: Final = "DO_NOT_CARE"
_COLOR_GREEN: Final = "GREEN"
_COLOR_OLD_VALUE: Final = "OLD_VALUE"
_COLOR_PURPLE: Final = "PURPLE"
_COLOR_RED: Final = "RED"
_COLOR_TURQUOISE: Final = "TURQUOISE"
_COLOR_WHITE: Final = "WHITE"
_COLOR_YELLOW: Final = "YELLOW"

_NO_COLOR: Final = (
    _COLOR_BLACK,
    _COLOR_DO_NOT_CARE,
    _COLOR_OLD_VALUE,
)

_EXCLUDE_FROM_COLOR_BEHAVIOUR: Final = (
    _COLOR_BEHAVIOUR_DO_NOT_CARE,
    _COLOR_BEHAVIOUR_OFF,
    _COLOR_BEHAVIOUR_OLD_VALUE,
)

_OFF_COLOR_BEHAVIOUR: Final = (
    _COLOR_BEHAVIOUR_DO_NOT_CARE,
    _COLOR_BEHAVIOUR_OFF,
    _COLOR_BEHAVIOUR_OLD_VALUE,
)


class HmLightArgs(TypedDict, total=False):
    """Matcher for the light arguments."""

    brightness: int
    color_name: str
    color_temp: int
    effect: str
    hs_color: tuple[float, float]
    on_time: float
    ramp_time: float


class BaseHmLight(CustomEntity, OnTimeMixin):
    """Base class for HomeMatic light entities."""

    _attr_platform = HmPlatform.LIGHT

    def _init_entity_fields(self) -> None:
        """Init the entity fields."""
        OnTimeMixin.__init__(self)
        super()._init_entity_fields()
        self._e_level: HmFloat = self._get_entity(field_name=FIELD_LEVEL, entity_type=HmFloat)
        self._e_on_time_value: HmAction = self._get_entity(
            field_name=FIELD_ON_TIME_VALUE, entity_type=HmAction
        )
        self._e_ramp_time_value: HmAction = self._get_entity(
            field_name=FIELD_RAMP_TIME_VALUE, entity_type=HmAction
        )

    @value_property
    @abstractmethod
    def is_on(self) -> bool | None:
        """Return true if light is on."""

    @value_property
    @abstractmethod
    def brightness(self) -> int | None:
        """Return the brightness of this light between 0..255."""

    @value_property
    def color_temp(self) -> int | None:
        """Return the color temperature in mireds of this light between 153..500."""
        return None

    @value_property
    def hs_color(self) -> tuple[float, float] | None:
        """Return the hue and saturation color value [float, float]."""
        return None

    @config_property
    def supports_brightness(self) -> bool:
        """Flag if light supports brightness."""
        return isinstance(self._e_level, HmFloat)

    @config_property
    def supports_color_temperature(self) -> bool:
        """Flag if light supports color temperature."""
        return False

    @config_property
    def supports_effects(self) -> bool:
        """Flag if light supports effects."""
        return False

    @config_property
    def supports_hs_color(self) -> bool:
        """Flag if light supports color."""
        return False

    @config_property
    def supports_transition(self) -> bool:
        """Flag if light supports transition."""
        return isinstance(self._e_ramp_time_value, HmAction)

    @value_property
    def effect(self) -> str | None:
        """Return the current effect."""
        return None

    @value_property
    def effect_list(self) -> list[str] | None:
        """Return the list of supported effects."""
        return None

    @bind_collector
    async def turn_on(
        self,
        collector: CallParameterCollector | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn the light on."""
        if not self.is_state_change(on=True, **kwargs):
            return
        if ramp_time := kwargs.get(_HM_ARG_RAMP_TIME):
            await self._set_ramp_time_on_value(ramp_time=float(ramp_time), collector=collector)
        if (on_time := kwargs.get(HM_ARG_ON_TIME)) or (on_time := self.get_on_time_and_cleanup()):
            await self._set_on_time_value(on_time=on_time, collector=collector)

        brightness = kwargs.get(_HM_ARG_BRIGHTNESS, self.brightness)
        if not brightness:
            brightness = 255
        level = brightness / 255.0
        await self._e_level.send_value(value=level, collector=collector)

    @bind_collector
    async def turn_off(
        self, collector: CallParameterCollector | None = None, **kwargs: Any
    ) -> None:
        """Turn the light off."""
        if not self.is_state_change(off=True, **kwargs):
            return
        if ramp_time := kwargs.get(_HM_ARG_RAMP_TIME):
            await self._set_ramp_time_off_value(ramp_time=float(ramp_time), collector=collector)

        await self._e_level.send_value(value=_HM_DIMMER_OFF, collector=collector)

    @bind_collector
    async def _set_on_time_value(
        self, on_time: float, collector: CallParameterCollector | None = None
    ) -> None:
        """Set the on time value in seconds."""
        await self._e_on_time_value.send_value(value=on_time, collector=collector)

    async def _set_ramp_time_on_value(
        self, ramp_time: float, collector: CallParameterCollector | None = None
    ) -> None:
        """Set the ramp time value in seconds."""
        await self._e_ramp_time_value.send_value(value=ramp_time, collector=collector)

    async def _set_ramp_time_off_value(
        self, ramp_time: float, collector: CallParameterCollector | None = None
    ) -> None:
        """Set the ramp time value in seconds."""
        await self._set_ramp_time_on_value(ramp_time=ramp_time, collector=collector)

    def is_state_change(self, **kwargs: Any) -> bool:
        """Check if the state changes due to kwargs."""
        if kwargs.get(HM_ARG_ON) is not None and self.is_on is not True and len(kwargs) == 1:
            return True
        if kwargs.get(HM_ARG_OFF) is not None and self.is_on is not False and len(kwargs) == 1:
            return True
        if (
            brightness := kwargs.get(_HM_ARG_BRIGHTNESS)
        ) is not None and brightness != self.brightness:
            return True
        if (hs_color := kwargs.get(_HM_ARG_HS_COLOR)) is not None and hs_color != self.hs_color:
            return True
        if (
            color_temp := kwargs.get(_HM_ARG_COLOR_TEMP)
        ) is not None and color_temp != self.color_temp:
            return True
        if (effect := kwargs.get(_HM_ARG_EFFECT)) is not None and effect != self.effect:
            return True
        if kwargs.get(_HM_ARG_RAMP_TIME) is not None:
            return True
        if kwargs.get(HM_ARG_ON_TIME) is not None:
            return True
        return super().is_state_change(**kwargs)


class CeDimmer(BaseHmLight):
    """Class for HomeMatic dimmer entities."""

    def _init_entity_fields(self) -> None:
        """Init the entity fields."""
        super()._init_entity_fields()
        self._e_channel_level: HmSensor = self._get_entity(
            field_name=FIELD_CHANNEL_LEVEL, entity_type=HmSensor
        )

    @value_property
    def is_on(self) -> bool | None:
        """Return true if dimmer is on."""
        return self._e_level.value is not None and self._e_level.value > _HM_DIMMER_OFF

    @value_property
    def brightness(self) -> int | None:
        """Return the brightness of this light between 0..255."""
        return int((self._e_level.value or 0.0) * 255)

    @value_property
    def channel_brightness(self) -> int | None:
        """Return the channel_brightness of this light between 0..255."""
        if self._e_channel_level.value is not None:
            return int(self._e_channel_level.value * 255)
        return None


class CeColorDimmer(CeDimmer):
    """Class for HomeMatic dimmer with color entities."""

    def _init_entity_fields(self) -> None:
        """Init the entity fields."""
        super()._init_entity_fields()
        self._e_color: HmInteger = self._get_entity(field_name=FIELD_COLOR, entity_type=HmInteger)

    @value_property
    def hs_color(self) -> tuple[float, float] | None:
        """Return the hue and saturation color value [float, float]."""
        if self._e_color.value is not None:
            color = self._e_color.value
            if color >= 200:
                # 200 is a special case (white), so we have a saturation of 0.
                # Larger values are undefined.
                # For the sake of robustness we return "white" anyway.
                return 0.0, 0.0

            # For all other colors we assume saturation of 1
            return color / 200 * 360, 100
        return 0.0, 0.0

    @config_property
    def supports_hs_color(self) -> bool:
        """Flag if light supports color temperature."""
        return True

    @config_property
    def supports_effects(self) -> bool:
        """Flag if light supports effects."""
        return False

    @bind_collector
    async def turn_on(
        self, collector: CallParameterCollector | None = None, **kwargs: Any
    ) -> None:
        """Turn the light on."""
        if not self.is_state_change(on=True, **kwargs):
            return
        if (hs_color := kwargs.get(_HM_ARG_HS_COLOR)) is not None:
            khue, ksaturation = hs_color
            hue = khue / 360
            saturation = ksaturation / 100
            color = 200 if saturation < 0.1 else int(round(max(min(hue, 1), 0) * 199))
            await self._e_color.send_value(value=color, collector=collector)
        await super().turn_on(collector=collector, **kwargs)


class CeColorDimmerEffect(CeColorDimmer):
    """Class for HomeMatic dimmer with color entities."""

    _effect_list: list[str] = [
        _HM_EFFECT_OFF,
        "Slow color change",
        "Medium color change",
        "Fast color change",
        "Campfire",
        "Waterfall",
        "TV simulation",
    ]

    def _init_entity_fields(self) -> None:
        """Init the entity fields."""
        super()._init_entity_fields()
        self._e_effect: HmInteger = self._get_entity(
            field_name=FIELD_PROGRAM, entity_type=HmInteger
        )

    @config_property
    def supports_effects(self) -> bool:
        """Flag if light supports effects."""
        return True

    @value_property
    def effect(self) -> str | None:
        """Return the current effect."""
        if self._e_effect.value is not None:
            return self._effect_list[int(self._e_effect.value)]
        return None

    @value_property
    def effect_list(self) -> list[str] | None:
        """Return the list of supported effects."""
        return self._effect_list

    @bind_collector
    async def turn_on(
        self, collector: CallParameterCollector | None = None, **kwargs: Any
    ) -> None:
        """Turn the light on."""
        if not self.is_state_change(on=True, **kwargs):
            return

        if (
            _HM_ARG_EFFECT not in kwargs
            and self.supports_effects
            and self.effect != _HM_EFFECT_OFF
        ):
            await self._e_effect.send_value(value=0, collector=collector)

        if self.supports_effects and (effect := kwargs.get(_HM_ARG_EFFECT)) is not None:
            effect_idx = self._effect_list.index(effect)
            if effect_idx is not None:
                await self._e_effect.send_value(value=effect_idx, collector=collector)

        await super().turn_on(collector=collector, **kwargs)


class CeColorTempDimmer(CeDimmer):
    """Class for HomeMatic dimmer with color temperature entities."""

    def _init_entity_fields(self) -> None:
        """Init the entity fields."""
        super()._init_entity_fields()
        self._e_color_level: HmFloat = self._get_entity(
            field_name=FIELD_COLOR_LEVEL, entity_type=HmFloat
        )

    @value_property
    def color_temp(self) -> int | None:
        """Return the color temperature in mireds of this light between 153..500."""
        return int(
            _HM_MAX_MIREDS - (_HM_MAX_MIREDS - _HM_MIN_MIREDS) * (self._e_color_level.value or 0.0)
        )

    @config_property
    def supports_color_temperature(self) -> bool:
        """Flag if light supports color temperature."""
        return True

    @bind_collector
    async def turn_on(
        self, collector: CallParameterCollector | None = None, **kwargs: Any
    ) -> None:
        """Turn the light on."""
        if not self.is_state_change(on=True, **kwargs):
            return
        if (color_temp := kwargs.get(_HM_ARG_COLOR_TEMP)) is not None:
            color_level = (_HM_MAX_MIREDS - color_temp) / (_HM_MAX_MIREDS - _HM_MIN_MIREDS)
            await self._e_color_level.send_value(value=color_level, collector=collector)

        await super().turn_on(collector=collector, **kwargs)


class CeIpRGBWLight(BaseHmLight):
    """Class for HomematicIP HmIP-RGBW light entities."""

    def _init_entity_fields(self) -> None:
        """Init the entity fields."""
        super()._init_entity_fields()
        self._e_activity_state: HmSelect = self._get_entity(
            field_name=FIELD_DIRECTION, entity_type=HmSelect
        )
        self._e_color_temperature_kelvin: HmInteger = self._get_entity(
            field_name=FIELD_COLOR_TEMPERATURE, entity_type=HmInteger
        )
        self._e_device_operation_mode: HmSelect = self._get_entity(
            field_name=FIELD_DEVICE_OPERATION_MODE, entity_type=HmSelect
        )
        self._e_effect: HmAction = self._get_entity(field_name=FIELD_EFFECT, entity_type=HmAction)
        self._e_hue: HmInteger = self._get_entity(field_name=FIELD_HUE, entity_type=HmInteger)
        self._e_ramp_time_to_off_unit: HmAction = self._get_entity(
            field_name=FIELD_RAMP_TIME_TO_OFF_UNIT, entity_type=HmAction
        )
        self._e_ramp_time_to_off_value: HmAction = self._get_entity(
            field_name=FIELD_RAMP_TIME_TO_OFF_VALUE, entity_type=HmAction
        )
        self._e_ramp_time_unit: HmAction = self._get_entity(
            field_name=FIELD_RAMP_TIME_UNIT, entity_type=HmAction
        )
        self._e_saturation: HmFloat = self._get_entity(
            field_name=FIELD_SATURATION, entity_type=HmFloat
        )

    @value_property
    def is_on(self) -> bool | None:
        """Return true if light is on."""
        return self._e_level.value is not None and self._e_level.value > _HM_DIMMER_OFF

    @value_property
    def brightness(self) -> int | None:
        """Return the brightness of this light between 0..255."""
        return int((self._e_level.value or 0.0) * 255)

    @value_property
    def color_temp(self) -> int | None:
        """Return the color temperature in mireds of this light between 153..500."""
        if not self._e_color_temperature_kelvin.value:
            return None
        return math.floor(1000000 / self._e_color_temperature_kelvin.value)

    @value_property
    def hs_color(self) -> tuple[float, float] | None:
        """Return the hue and saturation color value [float, float]."""
        if self._e_hue.value is not None and self._e_saturation.value is not None:
            return self._e_hue.value, self._e_saturation.value * 100
        return None

    @config_property
    def supports_color_temperature(self) -> bool:
        """Flag if light supports color temperature."""
        return self._e_device_operation_mode.value == _DOM_TUNABLE_WHITE

    @config_property
    def supports_effects(self) -> bool:
        """Flag if light supports effects."""
        return True

    @config_property
    def supports_hs_color(self) -> bool:
        """Flag if light supports color."""
        return self._e_device_operation_mode.value in (_DOM_RGBW, _DOM_RGB)

    @config_property
    def supports_transition(self) -> bool:
        """Flag if light supports transition."""
        return True

    @config_property
    def usage(self) -> HmEntityUsage:
        """
        Return the entity usage.

        Avoid creating entities that are not usable in selected device operation mode.
        """
        if (
            self._e_device_operation_mode.value in (_DOM_RGB, _DOM_RGBW)
            and self.channel_no in (2, 3, 4)
        ) or (
            self._e_device_operation_mode.value == _DOM_TUNABLE_WHITE and self.channel_no in (3, 4)
        ):
            return HmEntityUsage.NO_CREATE
        return self._attr_usage

    @value_property
    def effect_list(self) -> list[str] | None:
        """Return the list of supported effects."""
        return list(self._e_effect.value_list or ())

    @bind_collector
    async def turn_on(
        self,
        collector: CallParameterCollector | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn the light on."""
        if not self.is_state_change(on=True, **kwargs):
            return
        if (hs_color := kwargs.get(_HM_ARG_HS_COLOR)) is not None:
            hue, ksaturation = hs_color
            saturation = ksaturation / 100
            await self._e_hue.send_value(value=int(hue), collector=collector)
            await self._e_saturation.send_value(value=saturation, collector=collector)
        if color_temp := kwargs.get(_HM_ARG_COLOR_TEMP):
            color_temp_kelvin = math.floor(1000000 / color_temp)
            await self._e_color_temperature_kelvin.send_value(
                value=color_temp_kelvin, collector=collector
            )
        if self.supports_effects and (effect := kwargs.get(_HM_ARG_EFFECT)) is not None:
            await self._e_effect.send_value(value=effect, collector=collector)

        await super().turn_on(collector=collector, **kwargs)

    async def _set_ramp_time_on_value(
        self, ramp_time: float, collector: CallParameterCollector | None = None
    ) -> None:
        """Set the ramp time value in seconds."""
        ramp_time, ramp_time_unit = _recalc_unit_timer(time=ramp_time)
        await self._e_ramp_time_unit.send_value(value=ramp_time_unit, collector=collector)
        await self._e_ramp_time_value.send_value(value=float(ramp_time), collector=collector)

    async def _set_ramp_time_off_value(
        self, ramp_time: float, collector: CallParameterCollector | None = None
    ) -> None:
        """Set the ramp time value in seconds."""
        ramp_time, ramp_time_unit = _recalc_unit_timer(time=ramp_time)
        await self._e_ramp_time_to_off_unit.send_value(value=ramp_time_unit, collector=collector)
        await self._e_ramp_time_to_off_value.send_value(
            value=float(ramp_time), collector=collector
        )


class CeIpFixedColorLight(BaseHmLight):
    """Class for HomematicIP HmIP-BSL light entities."""

    _color_switcher: dict[str, tuple[float, float]] = {
        _COLOR_WHITE: (0.0, 0.0),
        _COLOR_RED: (0.0, 100.0),
        _COLOR_YELLOW: (60.0, 100.0),
        _COLOR_GREEN: (120.0, 100.0),
        _COLOR_TURQUOISE: (180.0, 100.0),
        _COLOR_BLUE: (240.0, 100.0),
        _COLOR_PURPLE: (300.0, 100.0),
    }

    @value_property
    def color_name(self) -> str | None:
        """Return the name of the color."""
        return self._e_color.value

    @value_property
    def channel_color_name(self) -> str | None:
        """Return the name of the channel color."""
        return self._e_channel_color.value

    def _init_entity_fields(self) -> None:
        """Init the entity fields."""
        super()._init_entity_fields()
        self._e_color: HmSelect = self._get_entity(field_name=FIELD_COLOR, entity_type=HmSelect)
        self._e_channel_color: HmSensor = self._get_entity(
            field_name=FIELD_CHANNEL_COLOR, entity_type=HmSensor
        )
        self._e_level: HmFloat = self._get_entity(field_name=FIELD_LEVEL, entity_type=HmFloat)
        self._e_channel_level: HmSensor = self._get_entity(
            field_name=FIELD_CHANNEL_LEVEL, entity_type=HmSensor
        )
        self._e_on_time_unit: HmAction = self._get_entity(
            field_name=FIELD_ON_TIME_UNIT, entity_type=HmAction
        )
        self._e_ramp_time_unit: HmAction = self._get_entity(
            field_name=FIELD_RAMP_TIME_UNIT, entity_type=HmAction
        )

    @value_property
    def is_on(self) -> bool | None:
        """Return true if dimmer is on."""
        return self._e_level.value is not None and self._e_level.value > 0.0

    @value_property
    def brightness(self) -> int | None:
        """Return the brightness of this light between 0..255."""
        return int((self._e_level.value or 0.0) * 255)

    @value_property
    def channel_brightness(self) -> int | None:
        """Return the channel brightness of this light between 0..255."""
        if self._e_channel_level.value is not None:
            return int(self._e_channel_level.value * 255)
        return None

    @value_property
    def hs_color(self) -> tuple[float, float] | None:
        """Return the hue and saturation color value [float, float]."""
        if (
            self._e_color.value is not None
            and (hs_color := self._color_switcher.get(self._e_color.value)) is not None
        ):
            return hs_color
        return 0.0, 0.0

    @value_property
    def channel_hs_color(self) -> tuple[float, float] | None:
        """Return the channel hue and saturation color value [float, float]."""
        if self._e_channel_color.value is not None:
            return self._color_switcher.get(self._e_channel_color.value, (0.0, 0.0))
        return None

    @config_property
    def supports_hs_color(self) -> bool:
        """Flag if light supports color."""
        return True

    @bind_collector
    async def turn_on(
        self, collector: CallParameterCollector | None = None, **kwargs: Any
    ) -> None:
        """Turn the light on."""
        if not self.is_state_change(on=True, **kwargs):
            return
        if (hs_color := kwargs.get(_HM_ARG_HS_COLOR)) is not None:
            simple_rgb_color = _convert_color(hs_color)
            await self._e_color.send_value(value=simple_rgb_color, collector=collector)
        elif self.color_name in _NO_COLOR:
            await self._e_color.send_value(value=_COLOR_WHITE, collector=collector)

        await super().turn_on(collector=collector, **kwargs)

    @bind_collector
    async def _set_on_time_value(
        self, on_time: float, collector: CallParameterCollector | None = None
    ) -> None:
        """Set the on time value in seconds."""
        on_time, on_time_unit = _recalc_unit_timer(time=on_time)
        await self._e_on_time_unit.send_value(value=on_time_unit, collector=collector)
        await self._e_on_time_value.send_value(value=float(on_time), collector=collector)

    async def _set_ramp_time_on_value(
        self, ramp_time: float, collector: CallParameterCollector | None = None
    ) -> None:
        """Set the ramp time value in seconds."""
        ramp_time, ramp_time_unit = _recalc_unit_timer(time=ramp_time)
        await self._e_ramp_time_unit.send_value(value=ramp_time_unit, collector=collector)
        await self._e_ramp_time_value.send_value(value=float(ramp_time), collector=collector)


class CeIpFixedColorLightWired(CeIpFixedColorLight):
    """Class for HomematicIP HmIPW-WRC6 light entities."""

    def _init_entity_fields(self) -> None:
        """Init the entity fields."""
        super()._init_entity_fields()
        self._e_color_behaviour: HmSelect = self._get_entity(
            field_name=FIELD_COLOR_BEHAVIOUR, entity_type=HmSelect
        )
        self._effect_list = (
            [
                item
                for item in self._e_color_behaviour.value_list
                if item not in _EXCLUDE_FROM_COLOR_BEHAVIOUR
            ]
            if (self._e_color_behaviour and self._e_color_behaviour.value_list)
            else []
        )

    @config_property
    def supports_effects(self) -> bool:
        """Flag if light supports effects."""
        return True

    @value_property
    def effect(self) -> str | None:
        """Return the current effect."""
        if (effect := self._e_color_behaviour.value) is not None and effect in self._effect_list:
            return effect
        return None

    @value_property
    def effect_list(self) -> list[str] | None:
        """Return the list of supported effects."""
        return self._effect_list

    @bind_collector
    async def turn_on(
        self, collector: CallParameterCollector | None = None, **kwargs: Any
    ) -> None:
        """Turn the light on."""
        if not self.is_state_change(on=True, **kwargs):
            return

        if (effect := kwargs.get(_HM_ARG_EFFECT)) is not None and effect in self._effect_list:
            await self._e_color_behaviour.send_value(value=effect, collector=collector)
        elif self._e_color_behaviour.value not in self._effect_list:
            await self._e_color_behaviour.send_value(
                value=_COLOR_BEHAVIOUR_ON, collector=collector
            )
        elif (color_behaviour := self._e_color_behaviour.value) is not None:
            await self._e_color_behaviour.send_value(value=color_behaviour, collector=collector)

        await super().turn_on(collector=collector, **kwargs)


def _recalc_unit_timer(time: float) -> tuple[float, int]:
    """Recalculate unit and value of timer."""
    ramp_time_unit = _TIME_UNIT_SECONDS
    if time > 16343:
        time /= 60
        ramp_time_unit = _TIME_UNIT_MINUTES
    if time > 16343:
        time /= 60
        ramp_time_unit = _TIME_UNIT_HOURS
    return time, ramp_time_unit


def _convert_color(color: tuple[float, float]) -> str:
    """
    Convert the given color to the reduced color of the device.

    Device contains only 8 colors including white and black,
    so a conversion is required.
    """
    hue: int = int(color[0])
    saturation: int = int(color[1])
    if saturation < 5:
        return _COLOR_WHITE
    if 30 < hue <= 90:
        return _COLOR_YELLOW
    if 90 < hue <= 150:
        return _COLOR_GREEN
    if 150 < hue <= 210:
        return _COLOR_TURQUOISE
    if 210 < hue <= 270:
        return _COLOR_BLUE
    if 270 < hue <= 330:
        return _COLOR_PURPLE
    return _COLOR_RED


def make_ip_dimmer(
    device: hmd.HmDevice,
    group_base_channels: tuple[int, ...],
    extended: ExtendedConfig | None = None,
) -> tuple[CustomEntity, ...]:
    """Create HomematicIP dimmer entities."""
    return hmed.make_custom_entity(
        device=device,
        custom_entity_class=CeDimmer,
        device_enum=HmEntityDefinition.IP_DIMMER,
        group_base_channels=group_base_channels,
        extended=extended,
    )


def make_rf_dimmer(
    device: hmd.HmDevice,
    group_base_channels: tuple[int, ...],
    extended: ExtendedConfig | None = None,
) -> tuple[CustomEntity, ...]:
    """Create HomeMatic classic dimmer entities."""
    return hmed.make_custom_entity(
        device=device,
        custom_entity_class=CeDimmer,
        device_enum=HmEntityDefinition.RF_DIMMER,
        group_base_channels=group_base_channels,
        extended=extended,
    )


def make_rf_dimmer_color(
    device: hmd.HmDevice,
    group_base_channels: tuple[int, ...],
    extended: ExtendedConfig | None = None,
) -> tuple[CustomEntity, ...]:
    """Create HomeMatic classic dimmer with color entities."""
    return hmed.make_custom_entity(
        device=device,
        custom_entity_class=CeColorDimmer,
        device_enum=HmEntityDefinition.RF_DIMMER_COLOR,
        group_base_channels=group_base_channels,
        extended=extended,
    )


def make_rf_dimmer_color_effect(
    device: hmd.HmDevice,
    group_base_channels: tuple[int, ...],
    extended: ExtendedConfig | None = None,
) -> tuple[CustomEntity, ...]:
    """Create HomeMatic classic dimmer and effect with color entities."""
    return hmed.make_custom_entity(
        device=device,
        custom_entity_class=CeColorDimmerEffect,
        device_enum=HmEntityDefinition.RF_DIMMER_COLOR,
        group_base_channels=group_base_channels,
        extended=extended,
    )


def make_rf_dimmer_color_temp(
    device: hmd.HmDevice,
    group_base_channels: tuple[int, ...],
    extended: ExtendedConfig | None = None,
) -> tuple[CustomEntity, ...]:
    """Create HomeMatic classic dimmer with color temperature entities."""
    return hmed.make_custom_entity(
        device=device,
        custom_entity_class=CeColorTempDimmer,
        device_enum=HmEntityDefinition.RF_DIMMER_COLOR_TEMP,
        group_base_channels=group_base_channels,
        extended=extended,
    )


def make_rf_dimmer_with_virt_channel(
    device: hmd.HmDevice,
    group_base_channels: tuple[int, ...],
    extended: ExtendedConfig | None = None,
) -> tuple[CustomEntity, ...]:
    """Create HomeMatic classic dimmer entities."""
    return hmed.make_custom_entity(
        device=device,
        custom_entity_class=CeDimmer,
        device_enum=HmEntityDefinition.RF_DIMMER_WITH_VIRT_CHANNEL,
        group_base_channels=group_base_channels,
        extended=extended,
    )


def make_ip_fixed_color_light(
    device: hmd.HmDevice,
    group_base_channels: tuple[int, ...],
    extended: ExtendedConfig | None = None,
) -> tuple[CustomEntity, ...]:
    """Create fixed color light entities like HmIP-BSL."""
    return hmed.make_custom_entity(
        device=device,
        custom_entity_class=CeIpFixedColorLight,
        device_enum=HmEntityDefinition.IP_FIXED_COLOR_LIGHT,
        group_base_channels=group_base_channels,
        extended=extended,
    )


def make_ip_simple_fixed_color_light_wired(
    device: hmd.HmDevice,
    group_base_channels: tuple[int, ...],
    extended: ExtendedConfig | None = None,
) -> tuple[CustomEntity, ...]:
    """Create simple fixed color light entities like HmIPW-WRC6."""
    return hmed.make_custom_entity(
        device=device,
        custom_entity_class=CeIpFixedColorLightWired,
        device_enum=HmEntityDefinition.IP_SIMPLE_FIXED_COLOR_LIGHT_WIRED,
        group_base_channels=group_base_channels,
        extended=extended,
    )


def make_ip_rgbw_light(
    device: hmd.HmDevice,
    group_base_channels: tuple[int, ...],
    extended: ExtendedConfig | None = None,
) -> tuple[CustomEntity, ...]:
    """Create simple fixed color light entities like HmIP-RGBW."""
    return hmed.make_custom_entity(
        device=device,
        custom_entity_class=CeIpRGBWLight,
        device_enum=HmEntityDefinition.IP_RGBW_LIGHT,
        group_base_channels=group_base_channels,
        extended=extended,
    )


# Case for device model is not relevant
DEVICES: dict[str, CustomConfig | tuple[CustomConfig, ...]] = {
    "263 132": CustomConfig(func=make_rf_dimmer, channels=(1,)),
    "263 133": CustomConfig(func=make_rf_dimmer_with_virt_channel, channels=(1,)),
    "263 134": CustomConfig(func=make_rf_dimmer, channels=(1,)),
    "HBW-LC-RGBWW-IN6-DR": (
        CustomConfig(
            func=make_rf_dimmer,
            channels=(7, 8),
            extended=ExtendedConfig(
                additional_entities={
                    (
                        1,
                        2,
                        3,
                        4,
                        5,
                        6,
                    ): (
                        HmEvent.PRESS_LONG,
                        HmEvent.PRESS_SHORT,
                        "SENSOR",
                    )
                },
            ),
        ),
        CustomConfig(
            func=make_rf_dimmer_color,
            channels=(9, 10, 11),
            extended=ExtendedConfig(fixed_channels={15: {FIELD_COLOR: "COLOR"}}),
        ),
        CustomConfig(
            func=make_rf_dimmer_color,
            channels=(12, 13, 14),
            extended=ExtendedConfig(fixed_channels={16: {FIELD_COLOR: "COLOR"}}),
        ),
    ),
    "HM-DW-WM": CustomConfig(func=make_rf_dimmer, channels=(1, 2, 3, 4)),
    "HM-LC-AO-SM": CustomConfig(func=make_rf_dimmer_with_virt_channel, channels=(1,)),
    "HM-LC-DW-WM": CustomConfig(func=make_rf_dimmer_color_temp, channels=(1, 3, 5)),
    "HM-LC-Dim1L-CV": CustomConfig(func=make_rf_dimmer_with_virt_channel, channels=(1,)),
    "HM-LC-Dim1L-CV-2": CustomConfig(func=make_rf_dimmer_with_virt_channel, channels=(1,)),
    "HM-LC-Dim1L-Pl": CustomConfig(func=make_rf_dimmer_with_virt_channel, channels=(1,)),
    "HM-LC-Dim1L-Pl-2": CustomConfig(func=make_rf_dimmer, channels=(1,)),
    "HM-LC-Dim1L-Pl-3": CustomConfig(func=make_rf_dimmer_with_virt_channel, channels=(1,)),
    "HM-LC-Dim1PWM-CV": CustomConfig(func=make_rf_dimmer_with_virt_channel, channels=(1,)),
    "HM-LC-Dim1PWM-CV-2": CustomConfig(func=make_rf_dimmer_with_virt_channel, channels=(1,)),
    "HM-LC-Dim1T-CV": CustomConfig(func=make_rf_dimmer_with_virt_channel, channels=(1,)),
    "HM-LC-Dim1T-CV-2": CustomConfig(func=make_rf_dimmer_with_virt_channel, channels=(1,)),
    "HM-LC-Dim1T-DR": CustomConfig(func=make_rf_dimmer, channels=(1, 2, 3)),
    "HM-LC-Dim1T-FM": CustomConfig(func=make_rf_dimmer_with_virt_channel, channels=(1,)),
    "HM-LC-Dim1T-FM-2": CustomConfig(func=make_rf_dimmer_with_virt_channel, channels=(1,)),
    "HM-LC-Dim1T-FM-LF": CustomConfig(func=make_rf_dimmer, channels=(1,)),
    "HM-LC-Dim1T-Pl": CustomConfig(func=make_rf_dimmer_with_virt_channel, channels=(1,)),
    "HM-LC-Dim1T-Pl-2": CustomConfig(func=make_rf_dimmer, channels=(1,)),
    "HM-LC-Dim1T-Pl-3": CustomConfig(func=make_rf_dimmer_with_virt_channel, channels=(1,)),
    "HM-LC-Dim1TPBU-FM": CustomConfig(func=make_rf_dimmer_with_virt_channel, channels=(1,)),
    "HM-LC-Dim1TPBU-FM-2": CustomConfig(func=make_rf_dimmer_with_virt_channel, channels=(1,)),
    "HM-LC-Dim2L-CV": CustomConfig(func=make_rf_dimmer, channels=(1, 2)),
    "HM-LC-Dim2L-SM": CustomConfig(func=make_rf_dimmer, channels=(1, 2)),
    "HM-LC-Dim2L-SM-2": CustomConfig(func=make_rf_dimmer, channels=(1, 2, 3, 4, 5, 6)),
    "HM-LC-Dim2T-SM": CustomConfig(func=make_rf_dimmer, channels=(1, 2)),
    "HM-LC-Dim2T-SM-2": CustomConfig(func=make_rf_dimmer, channels=(1, 2, 3, 4, 5, 6)),
    "HM-LC-RGBW-WM": CustomConfig(func=make_rf_dimmer_color_effect, channels=(1,)),
    "HMW-LC-Dim1L-DR": CustomConfig(func=make_rf_dimmer, channels=(3,)),
    "HSS-DX": CustomConfig(func=make_rf_dimmer, channels=(1,)),
    "HmIP-BDT": CustomConfig(func=make_ip_dimmer, channels=(3,)),
    "HmIP-BSL": CustomConfig(func=make_ip_fixed_color_light, channels=(7, 11)),
    "HmIP-DRDI3": CustomConfig(
        func=make_ip_dimmer,
        channels=(4, 8, 12),
        extended=ExtendedConfig(
            additional_entities={
                0: ("ACTUAL_TEMPERATURE",),
            }
        ),
    ),
    "HmIP-FDT": CustomConfig(func=make_ip_dimmer, channels=(1,)),
    "HmIP-PDT": CustomConfig(func=make_ip_dimmer, channels=(2,)),
    "HmIP-RGBW": CustomConfig(func=make_ip_rgbw_light, channels=(0,)),
    "HmIP-SCTH230": CustomConfig(
        func=make_ip_dimmer,
        channels=(11,),
        extended=ExtendedConfig(
            additional_entities={
                1: ("CONCENTRATION",),
                4: (
                    "HUMIDITY",
                    "ACTUAL_TEMPERATURE",
                ),
            }
        ),
    ),
    "HmIPW-DRD3": CustomConfig(
        func=make_ip_dimmer,
        channels=(1, 5, 9),
        extended=ExtendedConfig(
            additional_entities={
                0: ("ACTUAL_TEMPERATURE",),
            }
        ),
    ),
    "HmIPW-WRC6": CustomConfig(
        func=make_ip_simple_fixed_color_light_wired, channels=(7, 8, 9, 10, 11, 12, 13)
    ),
    "OLIGO.smart.iq.HM": CustomConfig(func=make_rf_dimmer, channels=(1, 2, 3, 4, 5, 6)),
}
hmed.ALL_DEVICES.append(DEVICES)
