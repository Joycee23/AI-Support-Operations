"""Untrusted document parsing in a disposable process with hard resource limits."""
import sys
from pathlib import Path

MAX_TEXT_CHARS = 100000


def extract_bounded(path: Path) -> str:
    if path.suffix.lower() == '.pdf':
        from pypdf import PdfReader
        reader = PdfReader(path, strict=True)
        if reader.is_encrypted or len(reader.pages) > 100:
            raise ValueError('PDF encrypted or too many pages')
        pieces, size = [], 0
        for page in reader.pages:
            value = page.extract_text() or ''
            size += len(value) + 1
            if size > MAX_TEXT_CHARS:
                raise ValueError('Too much extracted text')
            pieces.append(value)
        return '\n'.join(pieces)
    value = path.read_text(encoding='utf-8-sig')
    if len(value) > MAX_TEXT_CHARS or '\x00' in value:
        raise ValueError('Invalid text document')
    return value


if __name__ == '__main__':
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
    if sys.platform.startswith('linux'):
        resource.setrlimit(resource.RLIMIT_AS, (384 * 1024 * 1024, 384 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
    try:
        sys.stdout.write(extract_bounded(Path(sys.argv[1])))
    except Exception:
        # No file paths or document contents in output/logs.
        sys.exit(2)
