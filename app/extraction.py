"""Bounded file parsing in a disposable child process. Content is never instructions."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import socket
import struct
import subprocess  # nosec B404
import sys
import tempfile
from html.parser import HTMLParser
from zipfile import ZipFile, BadZipFile

from defusedxml import ElementTree

MAX_FILE = 8388608
MAX_TEXT = 4_000_000
MAX_PAGES = 200
MAX_EXPANDED = 32_000_000


def archive_members(raw):
    archive = ZipFile(io.BytesIO(raw))
    members = archive.infolist()
    if len(members) > 100:
        raise ValueError('ARCHIVE_ENTRY_LIMIT')
    total = 0
    for item in members:
        path = PurePosixPath(item.filename.replace('\\', '/'))
        if path.is_absolute() or '..' in path.parts or ':' in item.filename or item.flag_bits & 1:
            raise ValueError('UNSAFE_ARCHIVE_PATH_OR_ENCRYPTION')
        if (item.external_attr >> 16) & 0o170000 == 0o120000:
            raise ValueError('ARCHIVE_LINK_FORBIDDEN')
        total += item.file_size
        if total > MAX_EXPANDED or item.file_size / max(item.compress_size, 1) > 200:
            raise ValueError('ARCHIVE_EXPANSION_LIMIT')
    return archive, [item for item in members if not item.is_dir()]


class HTMLText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style', 'template'}:
            self.hidden += 1
        if tag in {'p', 'br', 'div', 'tr', 'li'}:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in {'script', 'style', 'template'} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def command(name):
    path = os.getenv('IGES_' + name.upper()) or shutil.which(name)
    if not path or not Path(path).is_file():
        raise ValueError(name.upper() + '_NOT_CONFIGURED')
    return str(Path(path).resolve())


def run(args, timeout=60):
    result = subprocess.run(args, capture_output=True, timeout=timeout, check=True,  # noqa: S603  # nosec B603
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if len(result.stdout) > MAX_TEXT * 2:
        raise ValueError('EXTRACTOR_OUTPUT_LIMIT')
    return result


def ocr(path):
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = 20_000_000
    with Image.open(path) as image:
        if image.width * image.height > 20_000_000:
            raise ValueError('IMAGE_PIXEL_LIMIT')
    result = run([command('tesseract'), str(path), 'stdout', '-l', os.getenv('IGES_OCR_LANGUAGES', 'eng'), 'tsv'])
    words = list(csv.DictReader(io.StringIO(result.stdout.decode('utf-8')), delimiter='\t'))
    confident = [(w['text'], float(w['conf'])) for w in words if w.get('text', '').strip() and float(w['conf']) >= 0]
    text = ' '.join(w[0] for w in confident)
    confidence = sum(w[1] * len(w[0]) for w in confident) / max(sum(len(w[0]) for w in confident), 1) / 100
    return {'text': text, 'confidence': round(confidence, 4), 'method': 'tesseract-tsv'}


def extract(raw, depth=0, budget=None):
    if budget is None:
        budget = {'expanded': 0, 'text': 0, 'pages': 0}
    if not raw or len(raw) > MAX_FILE or depth > 2:
        raise ValueError('FILE_OR_ARCHIVE_DEPTH_LIMIT')
    pages = []
    if raw.startswith(b'%PDF-'):
        from pypdf import PdfReader
        pdf = PdfReader(io.BytesIO(raw), strict=True)
        if pdf.is_encrypted or len(pdf.pages) > MAX_PAGES:
            raise ValueError('ENCRYPTED_OR_OVERSIZE_PDF')
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'input.pdf'
            source.write_bytes(raw)
            for number, page in enumerate(pdf.pages, 1):
                content = page.extract_text() or ''
                if content.strip():
                    pages.append({'text': content, 'confidence': None, 'method': 'pdf-text'})
                else:
                    target = Path(directory) / f'page-{number}'
                    run([command('pdftoppm'), '-f', str(number), '-l', str(number), '-singlefile',
                         '-scale-to', '3000', '-png', str(source), str(target)])
                    pages.append(ocr(target.with_suffix('.png')))
        mime = 'application/pdf'
    elif raw.startswith(b'PK\x03\x04'):
        archive, members = archive_members(raw)
        budget['expanded'] += sum(member.file_size for member in members)
        if budget['expanded'] > MAX_EXPANDED:
            raise ValueError('AGGREGATE_ARCHIVE_EXPANSION_LIMIT')
        with archive:
            names = {x.filename for x in members}
            if 'word/document.xml' in names and '[Content_Types].xml' in names:
                if any('vbaProject' in x or 'embeddings/' in x for x in names):
                    raise ValueError('ACTIVE_DOCX_CONTENT_FORBIDDEN')
                root = ElementTree.fromstring(archive.read('word/document.xml'))
                ns = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
                content = '\n'.join(''.join(t.text or '' for t in p.iter(ns + 't')) for p in root.iter(ns + 'p'))
                pages = [{'text': content, 'confidence': None, 'method': 'docx-logical-page'}]
                mime = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            else:
                for member in members:
                    nested = extract(archive.read(member), depth + 1, budget)
                    for page in nested['pages']:
                        page['member'] = member.filename + ('!/' + page['member'] if page.get('member') else '')
                        pages.append(page)
                mime = 'application/zip'
    elif raw.startswith((b'\x89PNG\r\n\x1a\n', b'\xff\xd8\xff', b'II*\0', b'MM\0*')):
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = 20_000_000
        with tempfile.TemporaryDirectory() as directory:
            with Image.open(io.BytesIO(raw)) as source:
                if getattr(source, 'n_frames', 1) > MAX_PAGES:
                    raise ValueError('IMAGE_FRAME_LIMIT')
                for index in range(getattr(source, 'n_frames', 1)):
                    source.seek(index)
                    if source.width * source.height > 20_000_000:
                        raise ValueError('IMAGE_PIXEL_LIMIT')
                    path = Path(directory) / f'frame-{index + 1}.png'
                    source.convert('RGB').save(path)
                    pages.append(ocr(path))
        mime = 'image/ocr-source'
    else:
        content = raw.decode('utf-8-sig')
        if '\x00' in content or any(ord(c) < 9 for c in content):
            raise ValueError('UNSUPPORTED_BINARY_TYPE')
        stripped = content.lstrip()
        if stripped.startswith(('{', '[')):
            # Validate but retain the exact lexical representation for quotations and numeric precision.
            json.loads(content)
            mime = 'application/json'
        elif stripped.lower().startswith(('<!doctype html', '<html', '<head', '<body')):
            parser = HTMLText()
            parser.feed(content)
            content = ''.join(parser.parts)
            mime = 'text/html'
        else:
            mime = 'text/csv' if ',' in content.split('\n', 1)[0] else 'text/plain'
        pages = [{'text': content, 'confidence': None, 'method': 'utf8-logical-page'}]
    if mime != 'application/zip':
        budget['text'] += sum(len(p['text']) for p in pages)
        budget['pages'] += len(pages)
    if not pages or budget['pages'] > MAX_PAGES or budget['text'] > MAX_TEXT:
        raise ValueError('EXTRACTED_TEXT_OR_PAGE_LIMIT')
    return {'mime': mime, 'pages': pages}


def antivirus(path):
    if os.getenv('IGES_CLAMD_HOST'):
        host = os.environ['IGES_CLAMD_HOST']
        port = int(os.getenv('IGES_CLAMD_PORT', '3310'))
        with socket.create_connection((host, port), timeout=90) as connection:
            connection.sendall(b'zVERSION\0')
            version = connection.recv(2048).decode('utf-8').strip('\0\n')
        with socket.create_connection((host, port), timeout=90) as connection:
            connection.sendall(b'zINSTREAM\0')
            raw = path.read_bytes()
            for offset in range(0, len(raw), 65536):
                block = raw[offset:offset + 65536]
                connection.sendall(struct.pack('!I', len(block)) + block)
            connection.sendall(struct.pack('!I', 0))
            result = connection.recv(2048).decode('utf-8').strip('\0\n')
        if result.endswith('FOUND'):
            raise ValueError('MALWARE_OR_SCAN_LIMIT')
        if result != 'stream: OK' or not version.startswith('ClamAV '):
            raise ValueError('ANTIVIRUS_UNAVAILABLE')
        return {'engine': version, 'status': 'CLEAN', 'sha256': hashlib.sha256(raw).hexdigest()}
    scanner = command('clamscan')
    version = run([scanner, '--version'], timeout=10).stdout.decode().strip()
    result = subprocess.run([scanner, '--no-summary', '--max-filesize=8M', '--max-scansize=32M',  # noqa: S603  # nosec B603
                             '--max-recursion=3', '--alert-exceeds-max=yes', str(path)],
                            capture_output=True, timeout=90, check=False,  # noqa: S603
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if result.returncode == 1:
        raise ValueError('MALWARE_OR_SCAN_LIMIT')
    if result.returncode != 0:
        raise ValueError('ANTIVIRUS_UNAVAILABLE')
    return {'engine': version, 'status': 'CLEAN', 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def main():
    if os.name != 'nt':
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (1_500_000_000, 1_500_000_000))
        resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
        resource.setrlimit(resource.RLIMIT_FSIZE, (40_000_000, 40_000_000))
    path = Path(sys.argv[1])
    raw = path.read_bytes()
    receipt = antivirus(path)
    parsed = extract(raw)
    print(json.dumps({**parsed, 'scanner': receipt}, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError, BadZipFile, RecursionError) as error:
        print(json.dumps({'error': type(error).__name__, 'code': str(error)[:100]}))
        sys.exit(1)
