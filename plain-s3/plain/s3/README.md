# plain.s3

**S3-compatible file storage for Plain models.**

Store files in S3, Cloudflare R2, DigitalOcean Spaces, MinIO, or any S3-compatible storage.

- [Overview](#overview)
- [Uploading files](#uploading-files)
- [Presigned uploads](#presigned-uploads)
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
    file: S3File | None = S3FileField()  # Uses S3_BUCKET setting
```

Override the bucket or add path prefixes per-field:

```python
@models.register_model
class User(models.Model):
    name: str = types.CharField(max_length=100)

    # Public avatars with custom path prefix
    avatar: S3File | None = S3FileField(
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

doc.file.filename              # "report.pdf"
doc.file.content_type          # "application/pdf"
doc.file.byte_size             # 1048576
doc.file.size_display          # "1.0 MB"
doc.file.presigned_download_url()  # Presigned S3 URL
```

## Uploading files

### Using a form

Use `S3FileField` in your form to handle file uploads:

```python
# app/documents/forms.py
from plain import forms
from plain.s3.forms import S3FileField


class DocumentForm(forms.Form):
    title = forms.CharField()
    file = S3FileField()  # Uses S3_BUCKET setting
```

```python
# app/documents/views.py
from plain.views import FormView

from .forms import DocumentForm
from .models import Document


class DocumentCreateView(FormView):
    form_class = DocumentForm
    template_name = "documents/create.html"

    def form_valid(self, form):
        doc = Document.query.create(
            title=form.cleaned_data["title"],
            file=form.cleaned_data["file"],  # S3File instance
        )
        return redirect("documents:detail", doc.id)
```

### Direct upload in a view

Upload files directly using the model field's `upload` method:

```python
from plain.views import View

from .models import Document


class DocumentUploadView(View):
    def post(self):
        uploaded_file = self.request.files["file"]

        # Get the field and use its configuration
        file_field = Document._meta.get_field("file")
        s3_file = file_field.upload(uploaded_file)

        doc = Document.query.create(
            title=self.request.POST["title"],
            file=s3_file,
        )
        return {"id": doc.id}
```

Or upload directly via `S3File.upload()`:

```python
from plain.s3.models import S3File


s3_file = S3File.upload(file=uploaded_file)
```

## Presigned uploads

For large files, upload directly from the browser to S3 to avoid server load.

**1. Create a view that returns presigned upload data:**

```python
# app/documents/views.py
import json

from plain.views import View
from plain.s3.models import S3File

from .models import Document


class PresignUploadView(View):
    def post(self):
        data = json.loads(self.request.body)

        file_field = Document._meta.get_field("file")
        return file_field.create_presigned_upload(
            filename=data["filename"],
            byte_size=data["byte_size"],
        )
        # Returns: {
        #     "key": "abc123.pdf",
        #     "upload_url": "https://bucket.s3...",
        # }


class DocumentCreateView(View):
    def post(self):
        data = json.loads(self.request.body)
        file = S3File.query.get(key=data["key"])
        doc = Document.query.create(
            title=data["title"],
            file=file,
        )
        return {"id": str(doc.id)}
```

**2. Upload from the browser:**

```javascript
// Get presigned URL
const presign = await fetch('/documents/presign/', {
  method: 'POST',
  body: JSON.stringify({
    filename: file.name,
    byte_size: file.size,
  }),
}).then(r => r.json());

// Upload directly to S3
await fetch(presign.upload_url, {
  method: 'PUT',
  body: file,
  headers: { 'Content-Type': file.type },
});

// Now attach to your record
await fetch('/documents/', {
  method: 'POST',
  body: JSON.stringify({
    title: 'My Document',
    key: presign.key,
  }),
});
```

## Downloading files

Generate presigned download URLs:

```python
# Default expiration (1 hour), triggers download
url = doc.file.presigned_download_url()

# Custom expiration (5 minutes)
url = doc.file.presigned_download_url(expires_in=300)

# Display in browser instead of downloading (for images, PDFs, etc.)
url = doc.file.presigned_download_url(inline=True)
```

## Settings

Configure your S3 connection in settings:

```python
S3_ACCESS_KEY_ID = "..."
S3_SECRET_ACCESS_KEY = "..."
S3_BUCKET = "my-bucket"
S3_REGION = "us-east-1"
S3_ENDPOINT_URL = ""  # For R2, MinIO, DigitalOcean Spaces, etc.
```

### Cloudflare R2

```python
S3_ACCESS_KEY_ID = "..."
S3_SECRET_ACCESS_KEY = "..."
S3_BUCKET = "my-bucket"
S3_REGION = "auto"
S3_ENDPOINT_URL = "https://ACCOUNT_ID.r2.cloudflarestorage.com"
```

### DigitalOcean Spaces

```python
S3_ACCESS_KEY_ID = "..."
S3_SECRET_ACCESS_KEY = "..."
S3_BUCKET = "my-bucket"
S3_REGION = "nyc3"  # Your Spaces region
S3_ENDPOINT_URL = "https://nyc3.digitaloceanspaces.com"
```

## Installation

1. Add `plain.s3` to your `INSTALLED_PACKAGES`:

```python
INSTALLED_PACKAGES = [
    # ...
    "plain.s3",
]
```

2. Configure your S3 settings (see Settings above).

3. Run migrations:

```bash
plain migrate
```

4. Add `S3FileField` to your models.
