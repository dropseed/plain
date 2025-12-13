# plain.s3

**S3-compatible file storage for Plain models.**

Store files in S3, Cloudflare R2, MinIO, or any S3-compatible storage service. Designed for direct browser uploads using presigned URLs.

- [Overview](#overview)
- [Direct uploads](#direct-uploads)
- [Downloading files](#downloading-files)
- [Settings](#settings)
- [Installation](#installation)

## Overview

Add file uploads to your models with `S3FileField`:

```python
from plain import models
from plain.models import types
from plain.s3.fields import S3FileField
from plain.s3.models import S3File


@models.register_model
class Document(models.Model):
    title: str = types.CharField(max_length=200)
    file: S3File | None = S3FileField()
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

**1. Create a presigned upload from your backend:**

```python
from plain.api import api
from plain.s3.models import S3File


@api.route("/uploads/presign", method="POST")
def create_presign(request):
    data = S3File.create_presigned_upload(
        filename=request.data["filename"],
        content_type=request.data["content_type"],
        byte_size=request.data["byte_size"],
    )
    return data
    # Returns: {
    #     "file_id": "uuid...",
    #     "upload_url": "https://bucket.s3...",
    #     "upload_fields": {"key": "...", "policy": "...", ...},
    # }
```

**2. Upload from the browser:**

```javascript
// Get presigned URL
const presign = await fetch('/uploads/presign', {
  method: 'POST',
  body: JSON.stringify({
    filename: file.name,
    content_type: file.type,
    byte_size: file.size,
  }),
}).then(r => r.json());

// Upload directly to S3
const formData = new FormData();
Object.entries(presign.upload_fields).forEach(([k, v]) => formData.append(k, v));
formData.append('file', file);

await fetch(presign.upload_url, { method: 'POST', body: formData });

// Now attach to your record
await fetch('/documents', {
  method: 'POST',
  body: JSON.stringify({
    title: 'My Document',
    file_id: presign.file_id,
  }),
});
```

**3. Link the file to your record:**

```python
@api.route("/documents", method="POST")
def create_document(request):
    file = S3File.query.get(uuid=request.data["file_id"])
    doc = Document.query.create(
        title=request.data["title"],
        file=file,
    )
    return {"id": str(doc.id)}
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

Configure your S3 connection in settings:

```python
# Required
S3_BUCKET = "my-bucket"
S3_ACCESS_KEY_ID = "..."
S3_SECRET_ACCESS_KEY = "..."

# Optional
S3_REGION = "us-east-1"
S3_ENDPOINT_URL = "https://..."  # For R2, MinIO, etc.
S3_DEFAULT_ACL = "private"  # or "public-read"
S3_PRESIGNED_URL_EXPIRATION = 3600  # seconds
S3_UPLOAD_KEY_PREFIX = "uploads/"
```

**Cloudflare R2 example:**

```python
S3_BUCKET = "my-bucket"
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

2. Configure your S3 settings (see above).

3. Run migrations:

```bash
plain migrate
```

4. Add `S3FileField` to your models where needed.
