import mimetypes
import os
import re
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponse
from django.utils._os import safe_join
from django.utils.http import http_date

RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")

class _LimitedReader:
    def __init__(self, fileobj, length):
        self.fileobj = fileobj
        self.remaining = length
    def read(self, size=-1):
        if self.remaining <= 0:
            return b""
        if size < 0 or size > self.remaining:
            size = self.remaining
        data = self.fileobj.read(size)
        self.remaining -= len(data)
        return data
    def close(self):
        self.fileobj.close()

@login_required
def serve_media(request, path):
    
    try:
        full_path = safe_join(settings.MEDIA_ROOT, path)
    except ValueError:
        raise Http404("Invalid path")
    
    if not os.path.isfile(full_path):
        raise Http404("File does not exist")
    
    file_size = os.path.getsize(full_path)
    content_type, _ = mimetypes.guess_type(full_path)
    content_type = content_type or "application/octet-stream"
    range_match = RANGE_RE.match(request.META.get("HTTP_RANGE", ""))

    if range_match:
        start_str, end_str = range_match.groups()
        start = int(start_str) if start_str else 0
        end = int(end_str) if end_str else file_size - 1
        end = min(end, file_size - 1)
        
        if start > end or start >= file_size:
            response = HttpResponse(status=416)
            response["Content-Range"] = f"bytes */{file_size}"
            return response

        length = end - start + 1
        fh = open(full_path, "rb")
        fh.seek(start)
        response = FileResponse(_LimitedReader(fh, length), content_type=content_type, status=206)
        response["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        response["Content-Length"] = str(length)
    
    else:
        response = FileResponse(open(full_path, "rb"), content_type=content_type)
        response["Content-Length"] = str(file_size)

    response["Accept-Ranges"] = "bytes"
    response["Last-Modified"] = http_date(os.path.getmtime(full_path))
    return response
