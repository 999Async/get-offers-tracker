"""Local parsing with no link execution, canonical locators, and bounded units."""

import hashlib
import io
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

from markdown_it import MarkdownIt

from getoffers_agent.domain.contracts import digest
from getoffers_agent.knowledge.contracts import (
    CanonicalDocument,
    DocumentNode,
    EvidenceUnit,
    KnowledgeConfig,
    KnowledgeError,
    SourceLocator,
)

MIMES = {
    "txt": "text/plain",
    "md": "text/markdown",
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def validate_upload(filename: str, mime: str, raw: bytes, config: KnowledgeConfig) -> str:
    extension = Path(filename).suffix.lower().removeprefix(".")
    if extension not in MIMES or mime != MIMES[extension]:
        raise KnowledgeError("unsupported_format_or_mime")
    if not raw or len(raw) > config.max_bytes:
        raise KnowledgeError("empty_or_oversized_file")
    if extension == "pdf" and not raw.startswith(b"%PDF-"):
        raise KnowledgeError("invalid_file_signature")
    if extension == "docx":
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                entries = archive.infolist()
                if len(entries) > 2000 or sum(e.file_size for e in entries) > config.max_bytes * 20:
                    raise KnowledgeError("archive_resource_limit")
                if any(e.flag_bits & 1 or "vbaproject" in e.filename.lower() for e in entries):
                    raise KnowledgeError("encrypted_or_macro_document")
                if "word/document.xml" not in archive.namelist():
                    raise KnowledgeError("invalid_file_signature")
        except (zipfile.BadZipFile, RuntimeError) as exc:
            raise KnowledgeError("corrupt_document") from exc
    if extension in {"txt", "md"}:
        try:
            value = raw.decode("utf-8-sig")
        except UnicodeError as exc:
            raise KnowledgeError("utf8_required") from exc
        if "\x00" in value or not value.strip():
            raise KnowledgeError("empty_or_binary_text")
    return extension


def parse_text(raw: bytes, extension: str, config: KnowledgeConfig) -> CanonicalDocument:
    value = raw.decode("utf-8-sig")
    lines = value.splitlines(keepends=True)
    blocks = []
    if extension == "md":
        ast = MarkdownIt("commonmark", {"html": False}).enable("table").parse(value)
        covered_until = 0
        for token in ast:
            if not token.map or token.map[0] < covered_until:
                continue
            if token.type not in {
                "heading_open",
                "paragraph_open",
                "fence",
                "code_block",
                "table_open",
            }:
                continue
            a, b = token.map
            kind = {
                "heading_open": "heading",
                "fence": "code",
                "code_block": "code",
                "table_open": "table",
            }.get(token.type, "paragraph")
            if kind == "paragraph" and re.match(r"\s*(?:[-*+] |\d+\. )", lines[a]):
                kind = "list_item"
            level = int(token.tag[1:]) if kind == "heading" else 0
            blocks.append((a, b, kind, level))
            covered_until = b
    else:
        start = None
        for i, line in enumerate([*lines, ""]):
            if line.strip() and start is None:
                start = i
            if not line.strip() and start is not None:
                content = "".join(lines[start:i])
                kind = (
                    "qa_pair"
                    if re.search(r"(?:^|\n)(?:Q[:：]|问题[:：])", content)
                    else "paragraph"
                )
                blocks.append((start, i, kind, 0))
                start = None
    if extension == "txt":
        grouped = []
        for block in blocks:
            a, b, kind, level = block
            if (
                grouped
                and grouped[-1][2] == "qa_pair"
                and re.match(r"\s*(?:A[:：]|回答[:：]|追问[:：]|反馈[:：])", lines[a])
            ):
                grouped[-1] = (grouped[-1][0], b, "qa_pair", 0)
            else:
                grouped.append(block)
        blocks = grouped
    nodes, headings = [], []
    for a, b, kind, level in blocks:
        content = "".join(lines[a:b]).rstrip("\r\n")
        if not content.strip():
            continue
        if kind == "heading":
            headings = [(lev, key, title) for lev, key, title in headings if lev < level]
        key = f"node-{len(nodes)}"
        cells = ()
        if kind == "table":
            cells = tuple(
                tuple(c.strip() for c in line.strip().strip("|").split("|"))
                for line in content.splitlines()
                if not re.fullmatch(r"[\s|:\-]+", line)
            )
        node = DocumentNode(
            node_id=key,
            kind=kind,
            text=content,
            order=len(nodes),
            path=tuple(h[2] for h in headings),
            parent_id=headings[-1][1] if headings else None,
            locator=SourceLocator(
                node_id=key, start=0, end=len(content), line_start=a + 1, line_end=b
            ),
            table_cells=cells,
        )
        nodes.append(node)
        if kind == "heading":
            headings.append((level, key, content.lstrip("# ")))
    if not nodes:
        raise KnowledgeError("empty_parse")
    if len(nodes) > config.max_nodes:
        raise KnowledgeError("node_limit")
    return CanonicalDocument(
        parser_identity="markdown-it-4/text-v1",
        source_hash=hashlib.sha256(raw).hexdigest(),
        format=extension,
        nodes=tuple(nodes),
    )


class DocumentParser:
    def __init__(self, config: KnowledgeConfig):
        self.config = config

    def parse(self, raw: bytes, extension: str) -> CanonicalDocument:
        if extension in {"md", "txt"}:
            return parse_text(raw, extension, self.config)
        try:
            import psutil
        except ImportError:
            raise KnowledgeError("parser_unavailable_or_document_invalid") from None
        # Child process limits parse time and CPU; uploaded paths/URLs never reach the converter.
        with tempfile.TemporaryDirectory(prefix="getoffers-parse-") as directory:
            source, output = (
                Path(directory) / f"source.{extension}",
                Path(directory) / "canonical.json",
            )
            source.write_bytes(raw)
            environment = {
                **os.environ,
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
                "HF_HUB_CACHE": os.environ.get(
                    "KNOWLEDGE_DOCLING_CACHE", str(Path(".agent-data/docling-models").resolve())
                ),
                "OMP_NUM_THREADS": "2",
                "TOKENIZERS_PARALLELISM": "false",
            }
            began = time.monotonic()
            with subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "getoffers_agent.knowledge.docling_worker",
                    str(source),
                    str(output),
                    self.config.model_dump_json(),
                ],
                env=environment,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            ) as result:
                process = psutil.Process(result.pid)
                try:
                    while result.poll() is None:
                        if time.monotonic() - began > self.config.parse_timeout_seconds:
                            raise KnowledgeError("parse_timeout")
                        try:
                            rss = process.memory_info().rss + sum(
                                child.memory_info().rss
                                for child in process.children(recursive=True)
                            )
                            if rss > self.config.max_parse_rss_mb * 1024 * 1024:
                                raise KnowledgeError("parse_memory_limit")
                        except psutil.NoSuchProcess:
                            pass
                        time.sleep(0.05)
                finally:
                    if result.poll() is None:
                        try:
                            os.killpg(result.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    result.wait()
            if result.returncode != 0 or not output.exists():
                raise KnowledgeError("parser_unavailable_or_document_invalid")
            canonical = CanonicalDocument.model_validate_json(output.read_text())
            if (
                len(canonical.nodes) > self.config.max_nodes
                or canonical.source_hash != hashlib.sha256(raw).hexdigest()
            ):
                raise KnowledgeError("invalid_canonical_document")
            return canonical


def make_units(
    document: CanonicalDocument,
    tenant: str,
    document_id: str,
    version_id: str,
    config: KnowledgeConfig,
) -> tuple[EvidenceUnit, ...]:
    units = []
    for node in document.nodes:
        start = 0
        while start < len(node.text):
            end, size = start, 0
            while (
                end < len(node.text)
                and size + len(node.text[end].encode()) <= config.max_unit_bytes
            ):
                size += len(node.text[end].encode())
                end += 1
            # Prefer sentence/list boundaries without introducing unsupported quote text.
            if end < len(node.text):
                boundary = max(
                    node.text.rfind(c, start + (end - start) // 2, end)
                    for c in ("\n", "。", ". ", ";")
                )
                if boundary > start:
                    end = boundary + 1
            locator = node.locator.model_copy(update={"start": start, "end": end})
            quote = node.text[start:end]
            if quote.strip():
                units.append(
                    EvidenceUnit(
                        evidence_id=digest(
                            [tenant, version_id, node.node_id, start, end, config.identity]
                        ),
                        document_id=document_id,
                        version_id=version_id,
                        tenant_id=tenant,
                        text=quote,
                        path=node.path,
                        parent_node_id=node.parent_id,
                        order=len(units),
                        locator=locator,
                        source_hash=document.source_hash,
                        table_header=node.text.splitlines()[0] if node.kind == "table" else None,
                    )
                )
            start = end
    return tuple(units)
