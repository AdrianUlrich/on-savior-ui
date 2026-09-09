"""Bridge from a parsed save to bang-bang inputs — not wired up yet.

No save file was available on this machine while this package was built, so
the exact field names on the ship/sensor records are unverified. These
functions stay stubs, raising ``NotImplementedError``, so the rest of the
package (:mod:`.model`, :mod:`.app`) can be written and used today against
manually entered :class:`~on_savior_ui.bangbang.model.ShipData` /
:class:`~on_savior_ui.bangbang.model.TargetData` — only this file needs to
change once a real save is available to inspect.

Per the project's no-cheating principle, only pull values a flight-management
computer could plausibly show: the ship's own wet mass / thrust / delta-v,
and a tracked contact's range, closing rate, cross-track rate, and ETA as
read off sensors — never a target's true state if the game tracks more
precision than the in-fiction instruments would reveal.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .model import ShipData, TargetData

if TYPE_CHECKING:
    from ..saves import Save


def ship_data_from_save(save: "Save") -> ShipData:
    """Read wet mass / thrust / delta-v off the player's ship record.

    TODO: once a save is available, find the fields under
    ``save.ship(<player ship id>)`` — likely mass, engine thrust, and
    propellant mass/Isp — and map them onto :class:`ShipData`.
    """
    raise NotImplementedError(
        "ship_data_from_save: needs a real save to locate the mass/thrust/delta-v "
        "fields on the ship record; build a ShipData by hand for now"
    )


def target_data_from_save(save: "Save", target_ship_id: str) -> TargetData:
    """Read range/closing-rate/cross-rate/ETA for one tracked contact.

    TODO: locate the player ship's sensor/tracking data (likely an AI-ship or
    nav-computer record referencing ``target_ship_id``) and map its range,
    relative velocity components, and any onboard ETA estimate onto
    :class:`TargetData`. Keep only what the flight computer would show — do
    not read the target's true state directly off its own ship record.
    """
    raise NotImplementedError(
        "target_data_from_save: needs a real save to locate the sensor/tracking "
        "fields; build a TargetData by hand for now"
    )
