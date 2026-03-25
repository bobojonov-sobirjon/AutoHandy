"""Attach uploaded images to a master (multipart field `images`, repeated)."""

from .models import MasterImage


def save_master_images_from_request(master, request) -> int:
    """Create MasterImage rows from request.FILES.getlist('images'). Returns count added."""
    files = request.FILES.getlist('images')
    n = 0
    for f in files:
        if f:
            MasterImage.objects.create(master=master, image=f)
            n += 1
    return n
