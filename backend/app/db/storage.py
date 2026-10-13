"""Binary file storage in MongoDB GridFS. Swap for S3-compatible storage later behind the same API."""

from bson import ObjectId
from gridfs import AsyncGridFSBucket
from gridfs.errors import NoFile

from app.db.mongo import get_db


def _bucket() -> AsyncGridFSBucket:
    return AsyncGridFSBucket(get_db(), bucket_name="files")


async def put(data: bytes, filename: str, content_type: str, **metadata) -> ObjectId:
    return await _bucket().upload_from_stream(
        filename, data, metadata={"content_type": content_type, **metadata}
    )


async def get(file_id: ObjectId) -> bytes:
    stream = await _bucket().open_download_stream(file_id)
    return await stream.read()


async def delete(*file_ids: ObjectId | None) -> None:
    bucket = _bucket()
    for file_id in file_ids:
        if file_id is None:
            continue
        try:
            await bucket.delete(file_id)
        except NoFile:
            pass
