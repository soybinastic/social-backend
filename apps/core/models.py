from django.db import models


class TimeStampedModel(models.Model):
    """Adds creation/update bookkeeping to any concrete model."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
