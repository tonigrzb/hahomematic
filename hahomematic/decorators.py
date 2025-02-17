"""Decorators used within hahomematic."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from functools import wraps
from inspect import getfullargspec
import logging
from typing import Any, ParamSpec, TypeVar, cast

from hahomematic import client as hmcl
from hahomematic.const import HmSystemEvent
from hahomematic.exceptions import HaHomematicException
from hahomematic.platforms import entity as hme
from hahomematic.support import reduce_args

_LOGGER = logging.getLogger(__name__)

_CallableT = TypeVar("_CallableT", bound=Callable[..., Any])

_P = ParamSpec("_P")
_R = TypeVar("_R")


def callback_system_event(system_event: HmSystemEvent) -> Callable:
    """Check if callback_system is set and call it AFTER original function."""

    def decorator_callback_system_event(
        func: Callable[_P, _R | Awaitable[_R]]
    ) -> Callable[_P, _R | Awaitable[_R]]:
        """Decorate callback system events."""

        @wraps(func)
        async def async_wrapper_callback_system_event(*args: _P.args, **kwargs: _P.kwargs) -> _R:
            """Wrap async callback system events."""
            return_value = cast(_R, await func(*args, **kwargs))  # type: ignore[misc]
            _exec_callback_system_event(*args, **kwargs)
            return return_value

        @wraps(func)
        def wrapper_callback_system_event(*args: _P.args, **kwargs: _P.kwargs) -> _R:
            """Wrap callback system events."""
            return_value = cast(_R, func(*args, **kwargs))
            _exec_callback_system_event(*args, **kwargs)
            return return_value

        def _exec_callback_system_event(*args: Any, **kwargs: Any) -> None:
            """Execute the callback for a system event."""
            if len(args) > 1:
                _LOGGER.warning(
                    "EXEC_CALLBACK_SYSTEM_EVENT failed: *args not supported for callback_system_event"
                )
            try:
                args = args[1:]
                interface_id: str = args[0] if len(args) > 1 else str(kwargs["interface_id"])
                if client := hmcl.get_client(interface_id=interface_id):
                    client.last_updated = datetime.now()
                    client.central.fire_system_event_callback(system_event=system_event, **kwargs)
            except Exception as err:  # pragma: no cover
                _LOGGER.warning(
                    "EXEC_CALLBACK_SYSTEM_EVENT failed: Unable to reduce kwargs for callback_system_event"
                )
                raise HaHomematicException(
                    f"args-exception callback_system_event [{reduce_args(args=err.args)}]"
                ) from err

        if asyncio.iscoroutinefunction(func):
            return async_wrapper_callback_system_event
        return wrapper_callback_system_event

    return decorator_callback_system_event


def callback_event(func: Callable[_P, _R]) -> Callable[_P, _R]:
    """Check if callback_event is set and call it AFTER original function."""

    @wraps(func)
    def wrapper_callback_event(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        """Wrap callback events."""
        return_value = func(*args, **kwargs)
        _exec_callback_entity_event(*args, **kwargs)
        return return_value

    def _exec_callback_entity_event(*args: Any, **kwargs: Any) -> None:
        """Execute the callback for an entity event."""
        try:
            args = args[1:]
            interface_id: str = args[0] if len(args) > 1 else str(kwargs["interface_id"])
            if client := hmcl.get_client(interface_id=interface_id):
                client.last_updated = datetime.now()
                client.central.fire_entity_event_callback(*args, **kwargs)
        except Exception as err:  # pragma: no cover
            _LOGGER.warning(
                "EXEC_CALLBACK_ENTITY_EVENT failed: Unable to reduce kwargs for callback_event"
            )
            raise HaHomematicException(
                f"args-exception callback_event [{reduce_args(args=err.args)}]"
            ) from err

    return wrapper_callback_event


def bind_collector(func: _CallableT) -> _CallableT:
    """Decorate function to automatically add collector if not set."""
    argument_name = "collector"
    argument_index = getfullargspec(func).args.index(argument_name)

    @wraps(func)
    async def wrapper_collector(*args: Any, **kwargs: Any) -> Any:
        """Wrap method to add collector."""
        try:
            collector_exists = args[argument_index] is not None
        except IndexError:
            collector_exists = kwargs.get(argument_name) is not None

        if collector_exists:
            return_value = await func(*args, **kwargs)
        else:
            collector = hme.CallParameterCollector(client=args[0].device.client)
            kwargs[argument_name] = collector
            return_value = await func(*args, **kwargs)
            await collector.send_data()
        return return_value

    return wrapper_collector  # type: ignore[return-value]
