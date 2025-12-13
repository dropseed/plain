from __future__ import annotations

from typing import TYPE_CHECKING

import boto3

from plain.runtime import settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


_client: S3Client | None = None


def get_client() -> S3Client:
    """Get or create the S3 client singleton."""
    global _client
    if _client is None:
        kwargs = {
            "aws_access_key_id": settings.S3_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.S3_SECRET_ACCESS_KEY,
        }
        if settings.S3_REGION:
            kwargs["region_name"] = settings.S3_REGION
        if settings.S3_ENDPOINT_URL:
            kwargs["endpoint_url"] = settings.S3_ENDPOINT_URL
        _client = boto3.client("s3", **kwargs)
    return _client


def generate_presigned_upload_url(
    key: str,
    content_type: str,
    *,
    expires_in: int | None = None,
) -> dict:
    """
    Generate a presigned URL for uploading a file directly to S3.

    Returns a dict with 'url' and 'fields' for form-based uploads,
    or just 'url' for PUT-based uploads.
    """
    if expires_in is None:
        expires_in = settings.S3_PRESIGNED_URL_EXPIRATION

    client = get_client()

    # Use presigned POST for browser uploads (more flexible)
    conditions = [
        {"Content-Type": content_type},
    ]
    fields = {
        "Content-Type": content_type,
    }

    if settings.S3_DEFAULT_ACL:
        conditions.append({"acl": settings.S3_DEFAULT_ACL})
        fields["acl"] = settings.S3_DEFAULT_ACL

    response = client.generate_presigned_post(
        Bucket=settings.S3_BUCKET,
        Key=key,
        Fields=fields,
        Conditions=conditions,
        ExpiresIn=expires_in,
    )
    return response


def generate_presigned_download_url(
    key: str,
    *,
    expires_in: int | None = None,
    filename: str | None = None,
) -> str:
    """Generate a presigned URL for downloading a file from S3."""
    if expires_in is None:
        expires_in = settings.S3_PRESIGNED_URL_EXPIRATION

    client = get_client()

    params = {
        "Bucket": settings.S3_BUCKET,
        "Key": key,
    }

    if filename:
        params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'

    return client.generate_presigned_url(
        "get_object",
        Params=params,
        ExpiresIn=expires_in,
    )


def delete_object(key: str) -> None:
    """Delete an object from S3."""
    client = get_client()
    client.delete_object(Bucket=settings.S3_BUCKET, Key=key)


def head_object(key: str) -> dict | None:
    """
    Get object metadata from S3.

    Returns None if the object doesn't exist.
    """
    client = get_client()
    try:
        return client.head_object(Bucket=settings.S3_BUCKET, Key=key)
    except client.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "404":
            return None
        raise
