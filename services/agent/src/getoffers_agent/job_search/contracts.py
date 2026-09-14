"""Whole-job facts, index identities and server-bound search contracts."""

import re
import unicodedata
from datetime import UTC, datetime
from typing import Literal

from pydantic import AwareDatetime, Field, HttpUrl, field_validator, model_validator

from getoffers_agent.domain.contracts import Contract, digest

NORMALIZER_VERSION = "job-normalizer-v1"
TOKENIZER_VERSION = "unicode-words-cjk-bigrams-v1"


def text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


def tokens(value: str) -> list[str]:
    value = unicodedata.normalize("NFKC", value).casefold()
    result = re.findall(r"[a-z0-9]+(?:[+#.][a-z0-9+#]+)*", value)
    for span in re.findall(r"[\u3400-\u9fff]+", value):
        result.extend(span if len(span) == 1 else [span[i : i + 2] for i in range(len(span) - 1)])
    return result


class JobInput(Contract):
    source_id: str = Field(min_length=1, max_length=200)
    source_job_id: str = Field(min_length=1, max_length=300)
    source_url: HttpUrl
    company: str = Field(min_length=1, max_length=300)
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=100000)
    responsibilities: tuple[str, ...] = ()
    requirements: tuple[str, ...] = ()
    cities: tuple[str, ...] = ()
    recruitment_type: str = "unknown"
    company_type: str = "unknown"
    observed_at: AwareDatetime
    expires_at: AwareDatetime | None = None
    visibility: Literal["shared", "private"] = "shared"
    tenant_id: str | None = None
    source_quality: float = Field(default=0.5, ge=0, le=1, allow_inf_nan=False)
    source_artifact_hash: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def ownership(self):
        if (self.visibility == "private") != (self.tenant_id is not None):
            raise ValueError("private jobs require an owner; shared jobs have no tenant")
        if not text(self.company) or not text(self.title):
            raise ValueError("empty normalized job")
        return self


class JobVersion(JobInput):
    job_id: str
    version_id: str
    content_hash: str
    duplicate_key: str
    completeness: Literal["full", "summary"]
    normalizer_version: str = NORMALIZER_VERSION

    @property
    def full_text(self) -> str:
        # Structured duties must remain searchable even if description is only an overview.
        content = list(dict.fromkeys([*self.responsibilities, *self.requirements]))
        if self.description and not all(section in self.description for section in content):
            content.append(self.description)
        elif self.description:
            content = [self.description]
        return "\n".join(
            [
                self.company,
                self.title,
                *content,
                *self.cities,
                self.recruitment_type,
                self.company_type,
            ]
        )


def normalize(source: JobInput) -> JobVersion:
    values = source.model_dump(mode="json")
    values["observed_at"] = source.observed_at.astimezone(UTC).isoformat()
    values["expires_at"] = (
        source.expires_at.astimezone(UTC).isoformat() if source.expires_at else None
    )
    for name in ("company", "title", "description", "recruitment_type", "company_type"):
        values[name] = text(values[name])
    for name in ("responsibilities", "requirements", "cities"):
        cleaned = list(dict.fromkeys(text(item) for item in values[name] if text(item)))
        values[name] = sorted(cleaned) if name == "cities" else cleaned
    identity = {k: values[k] for k in ("source_id", "source_job_id", "visibility", "tenant_id")}
    content = {k: v for k, v in values.items() if k not in {"observed_at", "source_artifact_hash"}}
    content["normalizer_version"] = NORMALIZER_VERSION
    content_hash = digest(content)
    duplicate_key = digest(
        {
            k: values[k]
            for k in (
                "company",
                "title",
                "cities",
                "responsibilities",
                "requirements",
                "recruitment_type",
            )
        }
    )
    return JobVersion(
        **values,
        job_id=digest(identity),
        version_id=digest({"job": digest(identity), "content": content_hash}),
        content_hash=content_hash,
        duplicate_key=duplicate_key,
        completeness="full" if values["responsibilities"] and values["requirements"] else "summary",
    )


class SnapshotEntry(Contract):
    version_id: str
    last_seen_at: AwareDatetime


class CorpusSnapshot(Contract):
    snapshot_id: str
    entries: tuple[SnapshotEntry, ...]
    source_kind: Literal["synthetic", "public-official", "imported"]


class HardConstraints(Contract):
    cities: tuple[str, ...] = ()
    excluded_cities: tuple[str, ...] = ()
    recruitment_types: tuple[str, ...] = ()
    excluded_companies: tuple[str, ...] = ()
    excluded_terms: tuple[str, ...] = ()
    max_age_days: int = Field(default=90, ge=1, le=3650)

    @field_validator(
        "cities", "excluded_cities", "recruitment_types", "excluded_companies", "excluded_terms"
    )
    @classmethod
    def normalize_filters(cls, values):
        return tuple(dict.fromkeys(text(value) for value in values if text(value)))


class SoftPreferences(Contract):
    company_types: tuple[str, ...] = ()
    cities: tuple[str, ...] = ()
    negative_duties: tuple[str, ...] = ()
    max_per_company: int = Field(default=3, ge=1, le=100)

    @field_validator("company_types", "cities", "negative_duties")
    @classmethod
    def normalize_preferences(cls, values):
        return tuple(dict.fromkeys(text(value) for value in values if text(value)))


class SearchRequest(Contract):
    query: str = Field(min_length=1, max_length=2000)
    hard_constraints: HardConstraints = Field(default_factory=HardConstraints)
    soft_preferences: SoftPreferences = Field(default_factory=SoftPreferences)
    top_k: int = Field(default=10, ge=1, le=100)
    candidate_profile_version: Literal["none"] = "none"

    @model_validator(mode="after")
    def searchable_query(self):
        if not tokens(self.query):
            raise ValueError("query contains no searchable tokens")
        return self


class SearchConfig(Contract):
    version: str = "job-search-v1"
    mode: Literal["lexical", "dense", "hybrid", "hybrid-rerank"] = "lexical"
    candidate_limit: int = Field(default=100, ge=1, le=1000)
    rrf_k: int = Field(default=60, ge=1)
    bm25_k1: float = Field(default=1.2, gt=0, allow_inf_nan=False)
    bm25_b: float = Field(default=0.75, ge=0, le=1)
    tokenizer_version: Literal["unicode-words-cjk-bigrams-v1"] = TOKENIZER_VERSION
    freshness_weight: float = Field(default=0.03, ge=0, le=1)
    preference_weight: float = Field(default=0.05, ge=0, le=1)
    duty_penalty: float = Field(default=0.15, ge=0, le=1)
    section_match_weight: float = Field(default=0.05, ge=0, le=1)
    source_quality_weight: float = Field(default=0.02, ge=0, le=1)

    @property
    def config_hash(self) -> str:
        return digest(self.model_dump(mode="json"))


class JobEvidence(Contract):
    evidence_id: str
    job_version_id: str
    source_url: str
    source_artifact_hash: str
    field: Literal["title", "responsibilities", "requirements"]
    item_index: int
    quote: str
    match_type: Literal["lexical", "context"] = "lexical"


class RankedJob(Contract):
    job: JobVersion
    rank: int
    score: float
    score_components: dict[str, float]
    evidence: tuple[JobEvidence, ...]


class SearchResult(Contract):
    jobs: tuple[RankedJob, ...]
    corpus_version: str
    index_version: str
    search_config_hash: str
    candidate_profile_version: str
    as_of: AwareDatetime
    stage_duration_ms: dict[str, float]
    candidates_retrieved: int
    rejected_by_fact_check: int
    effective_hard_constraints: HardConstraints
    city_constraint_matches: tuple[str, ...]
    constraint_parser_version: str


def eligible(
    job: JobVersion, last_seen: datetime, tenant: str, constraints: HardConstraints, as_of: datetime
) -> bool:
    if job.visibility == "private" and job.tenant_id != tenant:
        return False
    if job.completeness != "full" or last_seen > as_of:
        return False
    if (as_of - last_seen).total_seconds() > constraints.max_age_days * 86400:
        return False
    if job.expires_at and job.expires_at <= as_of:
        return False
    if constraints.cities and not set(map(text, constraints.cities)).intersection(job.cities):
        return False
    if set(constraints.excluded_cities).intersection(job.cities):
        return False
    if constraints.recruitment_types and job.recruitment_type not in constraints.recruitment_types:
        return False
    if job.company.casefold() in {text(c).casefold() for c in constraints.excluded_companies}:
        return False
    return not any(
        text(term).casefold() in job.full_text.casefold()
        for term in constraints.excluded_terms
        if text(term)
    )


def now() -> datetime:
    return datetime.now(UTC)
