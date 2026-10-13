"""Binary file storage in MongoDB GridFS. Swap for S3-compatible storage later behind the same API.

Contents are encrypted at rest when FILE_ENCRYPTION_KEY is set (app/core/crypto.py).
"""

from bson import ObjectId
from gridfs import AsyncGridFSBucket
from gridfs.errors import NoFile

from app.core import crypto
from app.core.guest import guest_files
from app.db.mongo import get_db

# "files": project uploads. "eval": copies users chose to add to the evaluation set, kept
# separately so deleting a project doesn't remove them.
Bucket = str


def _bucket(name: Bucket = "files") -> AsyncGridFSBucket:
    return AsyncGridFSBucket(get_db(), bucket_name=name)


async def put(
    data: bytes, filename: str, content_type: str, *, bucket: Bucket = "files", **metadata
) -> ObjectId:
    sandbox = guest_files()
    if sandbox is not None:  # guest: kept in memory and handed back to the browser
        file_id = ObjectId()
        sandbox[file_id] = data
        return file_id
    return await _bucket(bucket).upload_from_stream(
        filename,
        crypto.encrypt(data),
        metadata={"content_type": content_type, "encrypted": crypto.enabled(), **metadata},
    )


async def get(file_id: ObjectId, *, bucket: Bucket = "files") -> bytes:
    sandbox = guest_files()
    if sandbox is not None:
        if file_id not in sandbox:
            raise FileNotFoundError("The browser didn't send this file.")
        return sandbox[file_id]
    stream = await _bucket(bucket).open_download_stream(file_id)
    return crypto.decrypt(await stream.read())


async def delete(*file_ids: ObjectId | None, bucket: Bucket = "files") -> None:
    sandbox = guest_files()
    if sandbox is not None:
        for file_id in file_ids:
            sandbox.pop(file_id, None)
        return
    store = _bucket(bucket)
    for file_id in file_ids:
        if file_id is None:
            continue
        try:
            await store.delete(file_id)
        except NoFile:
            pass
