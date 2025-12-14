from __future__ import annotations

import boto3

from plain.runtime import settings


_client = None

DEFAULT_PRESIGNED_URL_EXPIRATION = 3600  # 1 hour


def get_client():
    """Get or create the S3 client singleton."""
    global _client
    if _client is None:
        kwargs = {
            "aws_access_key_id": settings.S3_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.S3_SECRET_ACCESS_KEY,
            "region_name": settings.S3_REGION,
        }
        if settings.S3_ENDPOINT_URL:
            kwargs["endpoint_url"] = settings.S3_ENDPOINT_URL
        _client = boto3.client("s3", **kwargs)
    return _client


def generate_presigned_upload_url(
    bucket: str,
    key: str,
    content_type: str,
    *,
    acl: str = "",
    expires_in: int = DEFAULT_PRESIGNED_URL_EXPIRATION,
) -> dict:
    """
    Generate a presigned URL for uploading a file directly to S3.

    Returns a dict with 'url' and 'fields' for form-based uploads.
    """
    client = get_client()

    conditions: list = [
        {"Content-Type": content_type},
    ]
    fields = {
        "Content-Type": content_type,
    }

    if acl:
        conditions.append({"acl": acl})
        fields["acl"] = acl

    response = client.generate_presigned_post(
        Bucket=bucket,
        Key=key,
        Fields=fields,
        Conditions=conditions,
        ExpiresIn=expires_in,
    )
    return response


def generate_presigned_download_url(
    bucket: str,
    key: str,
    *,
    expires_in: int = DEFAULT_PRESIGNED_URL_EXPIRATION,
    filename: str | None = None,
) -> str:
    """Generate a presigned URL for downloading a file from S3."""
    client = get_client()

    params = {
        "Bucket": bucket,
        "Key": key,
    }

    if filename:
        params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'

    return client.generate_presigned_url(
        "get_object",
        Params=params,
        ExpiresIn=expires_in,
    )


def delete_object(bucket: str, key: str) -> None:
    """Delete an object from S3."""
    client = get_client()
    client.delete_object(Bucket=bucket, Key=key)


def head_object(bucket: str, key: str) -> dict | None:
    """
    Get object metadata from S3.

    Returns None if the object doesn't exist.
    """
    client = get_client()
    try:
        return client.head_object(Bucket=bucket, Key=key)
    except client.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "404":
            return None
        raise
