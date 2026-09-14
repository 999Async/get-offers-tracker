"""Explicit source adapters. Feed summaries never silently become complete job descriptions."""

import hashlib
import html
import json
import re
from datetime import datetime
from html.parser import HTMLParser

from getoffers_agent.job_search.contracts import JobInput, text


class _Paragraphs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.buffer = [], []
        self.suppressed = 0

    def flush(self):
        value = text("".join(self.buffer))
        if value:
            self.parts.append(value)
        self.buffer = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.suppressed += 1
        if tag in {"p", "li", "h1", "h2", "h3", "h4", "br"}:
            self.flush()

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.suppressed = max(0, self.suppressed - 1)
        if tag in {"p", "li", "h1", "h2", "h3", "h4"}:
            self.flush()

    def handle_data(self, data):
        if not self.suppressed:
            self.buffer.append(data)


def parse_job_html(content: str) -> tuple[list[str], list[str], list[str]]:
    parser = _Paragraphs()
    parser.feed(html.unescape(content))
    parser.flush()
    responsibilities, requirements = [], []
    section = None
    for paragraph in parser.parts:
        lower = paragraph.casefold().strip(": ")
        if len(lower) < 120 and re.search(
            r"bonus|benefit|compensation|nice.to.have|preferred", lower
        ):
            section = None
        elif len(lower) < 120 and re.search(
            r"responsibilit|what you.ll do|in this role|职责", lower
        ):
            section = responsibilities
        elif len(lower) < 120 and re.search(
            r"requirements|qualifications|what you.ll bring|must have|任职", lower
        ):
            section = requirements
        elif section is not None:
            # Compensation/legal footer is not a qualification.
            if lower.startswith(("the us base salary", "the pay offered", "figure is an equal")):
                section = None
            else:
                section.append(paragraph)
    return parser.parts, responsibilities, requirements


def from_greenhouse(raw: bytes, board: str, company: str, observed_at: datetime) -> list[JobInput]:
    document = json.loads(raw)
    artifact_hash = hashlib.sha256(raw).hexdigest()
    result = []
    for job in document["jobs"]:
        paragraphs, responsibilities, requirements = parse_job_html(job.get("content", ""))
        result.append(
            JobInput(
                source_id="greenhouse:" + board,
                source_job_id=str(job["id"]),
                source_url=job["absolute_url"],
                company=company,
                title=job["title"],
                description="\n".join(paragraphs),
                responsibilities=tuple(responsibilities),
                requirements=tuple(requirements),
                cities=(job["location"]["name"],),
                observed_at=observed_at,
                source_artifact_hash=artifact_hash,
                source_quality=1,
            )
        )
    return result


def from_legacy_feed(raw: bytes, observed_at: datetime) -> list[JobInput]:
    """Read current /api/jobs export; preserve identity/links without inventing missing JD."""
    document = json.loads(raw)
    artifact_hash = hashlib.sha256(raw).hexdigest()
    return [
        JobInput(
            source_id=job["sourceKey"],
            source_job_id=job["id"],
            source_url=job.get("link") or job["sourceUrl"],
            company=job["company"],
            title=job["position"],
            cities=tuple(job.get("cities", [])),
            observed_at=observed_at,
            recruitment_type=(job.get("recruitmentTypes") or ["unknown"])[0],
            company_type=(job.get("companyTypes") or ["unknown"])[0],
            source_artifact_hash=artifact_hash,
        )
        for job in document["jobs"]
    ]
