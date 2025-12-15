SECRET_KEY = "test"
URLS_ROUTER = "app.urls.AppRouter"
INSTALLED_PACKAGES = [
    "plain.models",
    "plain.s3",
]

# S3 settings (will be mocked in tests)
S3_ACCESS_KEY_ID = "test-key"
S3_SECRET_ACCESS_KEY = "test-secret"
S3_REGION = "us-east-1"
S3_BUCKET = "test-bucket"
S3_ENDPOINT_URL = ""
