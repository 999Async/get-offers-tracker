# Parse documents through a Canonical Document interface

PDF and DOCX initially use a Docling Adapter, while Markdown and text use deterministic adapters, but every parser returns the same product-owned Canonical Document. Knowledge ingestion, Evidence Unit construction, citations, and evaluation do not depend on Docling or another parser's internal object model.
