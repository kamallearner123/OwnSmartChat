from django.db import models

MAX_MESSAGES = 10000


class Message(models.Model):
    role = models.CharField(max_length=16)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    @classmethod
    def add(cls, role, content):
        cls.objects.create(role=role, content=content)
        # Keep only the newest MAX_MESSAGES rows
        cutoff = cls.objects.order_by("-id").values_list("id", flat=True)[MAX_MESSAGES:MAX_MESSAGES + 1]
        if cutoff:
            cls.objects.filter(id__lte=cutoff[0]).delete()
