"""Binary file storage in MongoDB GridFS. Swap for S3-compatible storage later behind the same API."""

from bson import ObjectId
from gridfs import AsyncGridFSBucket
from gridfs.errors import NoFile

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
        filename, data, metadata={"content_type": content_type, **metadata}
    )


async def get(file_id: ObjectId, *, bucket: Bucket = "files") -> bytes:
    stream = await _bucket(bucket).open_download_stream(file_id)
    return await stream.read()


async def delete(*file_ids: ObjectId | None, bucket: Bucket = "files") -> None:
    store = _bucket(bucket)
    for file_id in file_ids:
        if file_id is None:
            continue
        try:
            await store.delete(file_id)
        except NoFile:
            pass
