"""Maintenance tasks.

    python -m app.maintenance encrypt-files   # encrypt files stored before FILE_ENCRYPTION_KEY was set

Each file is rewritten under the same id, so nothing that refers to it changes. Back up the
database first: a file is briefly absent between deleting the plain copy and writing the
encrypted one.
"""

import argparse
import asyncio

from gridfs import AsyncGridFSBucket

from app.core import crypto
from app.db import mongo

BUCKETS = ("files", "eval")


async def encrypt_files() -> tuple[int, int]:
    """Returns (encrypted now, already encrypted)."""
    if not crypto.enabled():
        raise SystemExit("Set FILE_ENCRYPTION_KEY first.")
    crypto.check_key()
    done = skipped = 0
    db = mongo.get_db()
    for name in BUCKETS:
        bucket = AsyncGridFSBucket(db, bucket_name=name)
        async for f in db[f"{name}.files"].find({}):
            stream = await bucket.open_download_stream(f["_id"])
            blob = await stream.read()
            if crypto.is_encrypted(blob):
                skipped += 1
                continue
            metadata = {**(f.get("metadata") or {}), "encrypted": True}
            sealed = crypto.encrypt(blob)
            await bucket.delete(f["_id"])
            await bucket.upload_from_stream_with_id(
                f["_id"], f["filename"], sealed, metadata=metadata
            )
            done += 1
    return done, skipped


async def _main(task: str) -> None:
    await mongo.connect()
    try:
        if task == "encrypt-files":
            done, skipped = await encrypt_files()
            print(f"Encrypted {done} file(s); {skipped} were already encrypted.")
    finally:
        await mongo.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("task", choices=["encrypt-files"])
    asyncio.run(_main(parser.parse_args().task))
