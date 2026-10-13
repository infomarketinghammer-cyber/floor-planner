"""Binary file storage in MongoDB GridFS. Swap for S3-compatible storage later behind the same API.

Contents are encrypted at rest when FILE_ENCRYPTION_KEY is set (app/core/crypto.py).
"""

from bson import ObjectId
from gridfs import AsyncGridFSBucket
from gridfs.errors import NoFile

from app.core import crypto
from app.db.mongo import get_db

# "files": project uploads. "eval": copies users chose to add to the evaluation set, kept
# separately so deleting a project doesn't remove them.
Bucket = str


def _bucket(name: Bucket = "files") -> AsyncGridFSBucket:
    return AsyncGridFSBucket(get_db(), bucket_name=name)


async def put(
    data: bytes, filename: str, content_type: str, *, bucket: Bucket = "files", **metadata
) -> ObjectId:
    return await _bucket(bucket).upload_from_stream(
        filename,
        crypto.encrypt(data),
        metadata={"content_type": content_type, "encrypted": crypto.enabled(), **metadata},
    )


async def get(file_id: ObjectId, *, bucket: Bucket = "files") -> bytes:
    stream = await _bucket(bucket).open_download_stream(file_id)
    return crypto.decrypt(await stream.read())


async def delete(*file_ids: ObjectId | None, bucket: Bucket = "files") -> None:
    store = _bucket(bucket)
    for file_id in file_ids:
        if file_id is None:
            continue
        try:
            await store.delete(file_id)
        except NoFile:
            pass
