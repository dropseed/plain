# The email backend to use. For possible shortcuts see plain.mail.
# The default is to use the SMTP backend.
# Third-party backends can be specified by providing a Python path
# to a module that defines an EmailBackend class.
EMAIL_BACKEND: str

EMAIL_DEFAULT_FROM: str

EMAIL_DEFAULT_REPLY_TO: list[str] = None

# Host for sending email.
EMAIL_HOST: str = "localhost"

# Port for sending email.
EMAIL_PORT: int = 25

# Whether to send SMTP 'Date' header in the local time zone or in UTC.
EMAIL_USE_LOCALTIME: bool = False

# Optional SMTP authentication information for EMAIL_HOST.
EMAIL_HOST_USER: str = ""
EMAIL_HOST_PASSWORD: str = ""
EMAIL_USE_TLS: bool = False
EMAIL_USE_SSL: bool = False
EMAIL_SSL_CERTFILE: str = None
EMAIL_SSL_KEYFILE: str = None
EMAIL_TIMEOUT: int = None
