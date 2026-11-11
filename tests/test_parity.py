"""``AsyncBeli`` must offer everything ``Beli`` does, with the same signatures.

``_async.py`` wraps each public method of the sync client by hand. This fails
if a method is added or changed on one side and not the other.
"""

from __future__ import annotations

import inspect

import pytest

from beli import AsyncBeli, Beli, _async
from beli import _resources as sync

PAIRS = [(Beli, AsyncBeli)] + [
    (getattr(sync, name), getattr(_async, f"Async{name}"))
    for name in ("Rankings", "Scores", "Notes", "Photos", "Bookmarks", "Guides", "Users", "Places")
]

NOT_AWAITED = {"from_session", "tokens"}
"""Public names that are the same kind of thing on both clients."""


def public(cls: type) -> dict[str, object]:
    return {name: value for name, value in vars(cls).items() if not name.startswith("_")}


def signature(function: object) -> str:
    function = getattr(function, "__func__", function)  # unwrap classmethods
    return str(inspect.signature(function)).replace("AsyncBeli", "Beli")  # type: ignore[arg-type]


@pytest.mark.parametrize(("blocking", "awaited"), PAIRS, ids=lambda cls: cls.__name__)
def test_async_wrapper_matches(blocking: type, awaited: type) -> None:
    ours, theirs = public(blocking), public(awaited)
    assert sorted(ours) == sorted(theirs)
    for name, method in ours.items():
        wrapper = theirs[name]
        if name == "user_id":
            # A property on Beli, an awaited method on AsyncBeli.
            assert isinstance(method, property) and inspect.iscoroutinefunction(wrapper)
        elif isinstance(method, property):
            assert isinstance(wrapper, property), name
        else:
            assert signature(wrapper) == signature(method), name
            assert inspect.iscoroutinefunction(wrapper) == (name not in NOT_AWAITED), name


def test_every_resource_is_wrapped() -> None:
    blocking, awaited = Beli("a@example.com", "pw"), AsyncBeli("a@example.com", "pw")
    resources = {n for n, v in vars(blocking).items() if isinstance(v, sync.Resource)}
    assert resources == {n for n in vars(awaited) if not n.startswith("_")}
    assert len(resources) == len(PAIRS) - 1
