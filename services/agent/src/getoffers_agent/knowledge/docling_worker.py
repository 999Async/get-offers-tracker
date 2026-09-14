"""Isolated optional Docling adapter. No OCR, plugins, enrichment, or remote services."""

import hashlib
import importlib.metadata
import os
import resource
import socket
import sys
from pathlib import Path

from getoffers_agent.knowledge.contracts import (
    CanonicalDocument,
    DocumentNode,
    KnowledgeConfig,
    SourceLocator,
)


def main():
    source, output = Path(sys.argv[1]), Path(sys.argv[2])
    config = KnowledgeConfig.model_validate_json(sys.argv[3])
    resource.setrlimit(
        resource.RLIMIT_CPU, (config.parse_timeout_seconds, config.parse_timeout_seconds + 1)
    )
    resource.setrlimit(resource.RLIMIT_FSIZE, (32 * 1024 * 1024, 32 * 1024 * 1024))

    def deny_network(*args, **kwargs):
        raise PermissionError("parser_network_disabled")

    socket.socket.connect = deny_network
    socket.create_connection = deny_network
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import LayoutObjectDetectionOptions, PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    layout = LayoutObjectDetectionOptions()
    layout = layout.model_copy(
        update={
            "model_spec": layout.model_spec.model_copy(
                update={"revision": config.pdf_layout_revision}
            )
        }
    )
    artifacts = None
    if source.suffix == ".pdf":
        snapshot = Path(os.environ["HF_HUB_CACHE"]) / (
            "models--docling-project--docling-layout-heron/snapshots/" + config.pdf_layout_revision
        )
        if not (snapshot / "model.safetensors").is_file():
            raise ValueError("pdf_layout_model_missing")
        artifacts = source.parent / "models"
        artifacts.mkdir()
        (artifacts / "docling-project--docling-layout-heron").symlink_to(
            snapshot, target_is_directory=True
        )
    options = PdfPipelineOptions(
        do_ocr=False,
        do_table_structure=False,
        enable_remote_services=False,
        allow_external_plugins=False,
        layout_options=layout,
        artifacts_path=artifacts,
    )
    converter = DocumentConverter(
        allowed_formats=[InputFormat.PDF, InputFormat.DOCX],
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)},
    )
    result = converter.convert(
        source, max_num_pages=config.max_pages, max_file_size=config.max_bytes
    )
    doc = result.document
    nodes, headings = [], []
    for item, level in doc.iterate_items():
        label = str(getattr(getattr(item, "label", ""), "value", "")).lower()
        table = "table" in label
        content = item.export_to_markdown(doc=doc) if table else getattr(item, "text", "")
        if not content.strip():
            continue
        kind = (
            "table"
            if table
            else "heading"
            if "heading" in label or "title" in label or "section_header" in label
            else "list_item"
            if "list" in label
            else "paragraph"
        )
        if kind == "heading":
            level = getattr(item, "level", level)
            headings = [h for h in headings if h[0] < level]
        key = f"node-{len(nodes)}"
        prov = item.prov[0] if getattr(item, "prov", None) else None
        bbox = (prov.bbox.l, prov.bbox.t, prov.bbox.r, prov.bbox.b) if prov else None
        nodes.append(
            DocumentNode(
                node_id=key,
                kind=kind,
                text=content,
                order=len(nodes),
                path=tuple(h[2] for h in headings),
                parent_id=headings[-1][1] if headings else None,
                locator=SourceLocator(
                    node_id=key,
                    start=0,
                    end=len(content),
                    page=prov.page_no if prov else None,
                    bbox=bbox,
                    source_ref=item.self_ref,
                ),
                table_cells=tuple(tuple(cell.text for cell in row) for row in item.data.grid)
                if table
                else (),
            )
        )
        if kind == "heading":
            headings.append((level, key, content))
        if len(nodes) > config.max_nodes:
            raise ValueError("node_limit")
    canonical = CanonicalDocument(
        parser_identity="docling-"
        + importlib.metadata.version("docling")
        + ("/layout-" + config.pdf_layout_revision if source.suffix == ".pdf" else ""),
        source_hash=hashlib.sha256(source.read_bytes()).hexdigest(),
        format=source.suffix[1:],
        nodes=tuple(nodes),
    )
    output.write_text(canonical.model_dump_json())


if __name__ == "__main__":
    main()
