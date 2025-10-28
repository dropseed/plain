# plain-assets: Automatic WebP Conversion

**Status:** Core feature, optional based on `cwebp` availability

## Overview

Automatically convert PNG/JPEG images to WebP during `plain build` to reduce file sizes by ~25-35%.

**Enabled when:** User has `cwebp` binary installed (from libwebp package)

**Disabled when:** `cwebp` not found (silent skip, no errors)

## Installation (Optional)

```bash
# macOS
brew install webp

# Ubuntu/Debian
sudo apt install webp

# Alpine (Docker)
apk add libwebp-tools
```

## Key Design Decisions

- **Optional core feature**: Built into plain-assets, no separate package
    - If `cwebp` available → WebP variants generated
    - If not → Original behavior (no WebP)
    - Zero Python dependencies

- **Dual format strategy**: Generate both original and WebP versions
    - `hero.jpg` → `hero.abc123.jpg` + `hero.abc123.webp`
    - Both fingerprinted and added to manifest
    - No template changes required (backward compatible)

- **Header-based serving**: Use `Accept: image/webp` header
    - Browser requests `hero.jpg` with `Accept: image/webp`
    - Server transparently serves `hero.webp` if available
    - Cleaner than `<picture>` elements
    - Works with existing `{% asset %}` tags

- **Browser support**: 96%+ in 2025
    - Supported: Chrome 32+, Firefox 65+, Safari 14+, Edge 18+
    - Fallback via dual format for old browsers

## Configuration (Optional)

Probably don't need settings - sensible defaults work for everyone. But if needed:

```python
# settings.py
ASSETS_WEBP_QUALITY = 85  # Default: 85 (0-100)
ASSETS_WEBP_ONLY_IF_SMALLER = True  # Default: True (skip if WebP is larger)
```

## Build Integration

```python
# In plain/plain/assets/compile.py

def has_webp_support():
    """Check if cwebp binary is available."""
    return shutil.which("cwebp") is not None

def compile_assets():
    webp_enabled = has_webp_support()

    for asset in assets:
        # Copy original
        copy_file(asset)
        fingerprint_file(asset)

        # Generate WebP if enabled and applicable
        if webp_enabled and is_image(asset):
            webp_path = convert_to_webp(asset, quality=85)
            if webp_path:
                fingerprint_file(webp_path)
```

## Serving Logic

```python
# In plain/plain/assets/views.py

def get(self, request, path):
    # Try to serve WebP variant if browser supports it
    if path.endswith(('.jpg', '.jpeg', '.png')):
        if 'image/webp' in request.headers.get('Accept', ''):
            webp_path = get_webp_variant(path)
            if webp_path and webp_path in manifest:
                path = webp_path

    return serve_file(path)
```

## User Experience

**Developer installs cwebp:**

```bash
brew install webp
plain build
# → Images automatically get WebP variants
# → Browsers automatically get smaller files
```

**Developer doesn't install cwebp:**

```bash
plain build
# → Works exactly as before
# → No WebP variants generated
# → No errors or warnings
```

**Optional: Check if WebP is working**

```bash
plain build --verbose
# → "WebP: Converted 12 images (saved 2.3MB)"
# OR
# → "WebP: cwebp not found (install with 'brew install webp')"
```

## Questions to Resolve

1. **Verbosity**: Should we show a one-time hint if `cwebp` not found?
2. **AVIF support**: Also support AVIF via `avifenc` (same pattern)?
3. **Manifest format**: How to represent variants in fingerprint manifest?
