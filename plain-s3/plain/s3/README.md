# plain.s3

**S3-compatible file storage for Plain models.**

Store files in S3, Cloudflare R2, MinIO, or any S3-compatible storage service. Designed for direct browser uploads using presigned URLs.

- [Overview](#overview)
- [Direct uploads](#direct-uploads)
- [Downloading files](#downloading-files)
- [Settings](#settings)
- [Installation](#installation)

## Overview

Add file uploads to your models with `S3FileField`. Each field specifies which bucket to use:

```python
from plain import models
from plain.models import types
from plain.s3.fields import S3FileField
from plain.s3.models import S3File


@models.register_model
class Document(models.Model):
    title: str = types.CharField(max_length=200)
    file: S3File | None = S3FileField(bucket="my-bucket")
```

Configure per-field storage options:

```python
@models.register_model
class User(models.Model):
    name: str = types.CharField(max_length=100)

    # Public avatars with custom path prefix
    avatar: S3File | None = S3FileField(
        bucket="public-assets",
        key_prefix="avatars/",
        acl="public-read",
    )

    # Private documents in a different bucket
    id_document: S3File | None = S3FileField(
        bucket="private-docs",
        key_prefix="id-verification/",
    )
```

Access file properties and generate download URLs:

```python
doc = Document.query.get(id=some_id)

doc.file.filename       # "report.pdf"
doc.file.content_type   # "application/pdf"
doc.file.byte_size      # 1048576
doc.file.size_display   # "1.0 MB"
doc.file.download_url() # presigned S3 URL
```

## Direct uploads

For large files, upload directly from the browser to S3 to avoid tying up your server.

**1. Create a presigned upload view:**

```python
# app/api/views.py
from plain.api.views import APIView
from plain.s3.models import S3File

from app.documents.models import Document


class PresignUploadView(APIView):
    def post(self):
        # Get the field configuration
        file_field = Document._meta.get_field("file")

        # Create presigned upload using field's bucket/prefix/acl
        return file_field.create_presigned_upload(
            filename=self.data["filename"],
            byte_size=self.data["byte_size"],
        )
        # Returns: {
        #     "file_id": "uuid...",
        #     "upload_url": "https://bucket.s3...",
        #     "upload_fields": {"key": "...", "policy": "...", ...},
        # }


class DocumentView(APIView):
    def post(self):
        file = S3File.query.get(uuid=self.data["file_id"])
        doc = Document.query.create(
            title=self.data["title"],
            file=file,
        )
        return {"id": str(doc.id)}
```

```python
# app/api/urls.py
from plain.urls import Router, path

from . import views


class APIRouter(Router):
    namespace = "api"
    urls = [
        path("uploads/presign/", views.PresignUploadView),
        path("documents/", views.DocumentView),
    ]
```

**2. Upload from the browser:**

```javascript
// Get presigned URL
const presign = await fetch('/api/uploads/presign/', {
  method: 'POST',
  body: JSON.stringify({
    filename: file.name,
    byte_size: file.size,
  }),
}).then(r => r.json());

// Upload directly to S3
const formData = new FormData();
Object.entries(presign.upload_fields).forEach(([k, v]) => formData.append(k, v));
formData.append('file', file);

await fetch(presign.upload_url, { method: 'POST', body: formData });

// Now attach to your record
await fetch('/api/documents/', {
  method: 'POST',
  body: JSON.stringify({
    title: 'My Document',
    file_id: presign.file_id,
  }),
});
```

## Downloading files

Generate presigned download URLs:

```python
# Default expiration (1 hour)
url = doc.file.download_url()

# Custom expiration
url = doc.file.download_url(expires_in=300)  # 5 minutes
```

## Settings

Configure your S3 connection credentials in settings. Bucket and path configuration is per-field (see Overview above).

```python
# Required - connection credentials
S3_ACCESS_KEY_ID = "..."
S3_SECRET_ACCESS_KEY = "..."

# Optional
S3_REGION = "us-east-1"
S3_ENDPOINT_URL = "https://..."  # For R2, MinIO, etc.
```

**Cloudflare R2 example:**

```python
S3_ACCESS_KEY_ID = "..."
S3_SECRET_ACCESS_KEY = "..."
S3_ENDPOINT_URL = "https://ACCOUNT_ID.r2.cloudflarestorage.com"
```

## Installation

1. Add `plain.s3` to your `INSTALLED_PACKAGES`:

```python
INSTALLED_PACKAGES = [
    # ...
    "plain.s3",
]
```

2. Configure your S3 connection credentials (see Settings above).

3. Run migrations:

```bash
plain migrate
```

4. Add `S3FileField` to your models, specifying the bucket for each field.
