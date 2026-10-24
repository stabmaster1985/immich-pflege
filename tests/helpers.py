from __future__ import annotations

import uuid
from itertools import count

from immich_pflege.library import ImmichDuplicate, Library
from immich_pflege.models import Asset

_n = count(1)


def asset(owner="frank", name=None, local="2024-07-14T11:00:00.000Z", utc=None, **kw) -> Asset:
    i = next(_n)
    data = dict(
        id=str(uuid.UUID(int=i, version=4)), owner=owner, checksum=kw.pop("checksum", f"cs-{i}"),
        file_name=name or f"IMG_{i:04d}.HEIC", path=kw.pop("path", f"/upload/{owner}/IMG_{i:04d}.HEIC"),
        local_date_time=local, file_created_at=utc or local, library_id=kw.pop("library_id", None),
        type=kw.pop("type", "IMAGE"), width=kw.pop("width", 4032), height=kw.pop("height", 3024),
    )
    data.update(kw)
    return Asset(**data)


def library(*assets: Asset, duplicates: list[ImmichDuplicate] = ()) -> Library:
    return Library(scanned_at="2024-01-01T00:00:00+00:00", duration_s=0, server_version="3.2.4",
                   users={"frank": {"id": "f"}, "julia": {"id": "j"}},
                   assets={a.id: a for a in assets}, immich_duplicates=list(duplicates))
