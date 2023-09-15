from bolt.db import models


class Dashboard(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    # order
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Needs to be a list becaues dict isn't ordered in the db
    # A list also makes it possible include the same card twice...
    # at different sizes/options, potentially
    cards = models.JSONField(default=list)
