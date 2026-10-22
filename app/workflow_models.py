"""Human-authored research records. Unknown facts are explicit, never imputed."""
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Record(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class Period(Record):
    period_from: date
    period_to: date

    @model_validator(mode='after')
    def ordered(self):
        if self.period_to < self.period_from:
            raise ValueError('period_to precedes period_from')
        return self


class Case(Period):
    title: str = Field(min_length=3, max_length=300)
    scope: str = Field(min_length=10, max_length=5000)
    jurisdictions: list[str] = Field(min_length=1, max_length=20)
    classification: Literal['PUBLIC_SOURCE_ONLY'] = 'PUBLIC_SOURCE_ONLY'


class Claim(Period):
    exact_text: str = Field(min_length=10, max_length=5000)
    jurisdictions: list[str] = Field(min_length=1, max_length=20)
    scope_note: str = Field(min_length=10, max_length=5000)
    claim_type: Literal['documentary', 'financial', 'corporate']
    status: Literal['UNASSESSED'] = 'UNASSESSED'
    supersedes_id: UUID | None = None


class CaseRevision(Case):
    rationale: str = Field(min_length=20, max_length=5000)


class Hypothesis(Record):
    claim_id: UUID
    statement: str = Field(min_length=10, max_length=5000)
    expected_observations: str = Field(min_length=10, max_length=5000)
    falsifiers: str = Field(min_length=10, max_length=5000)


class Source(Record):
    title: str = Field(min_length=3, max_length=500)
    publisher: str = Field(min_length=2, max_length=500)
    author: str | None = Field(default=None, max_length=500)
    url: str = Field(pattern=r'^https://[^\s]+$', max_length=2000)
    published_at: date | None = None
    language: str = Field(pattern=r'^[a-z]{2,3}$')
    primacy: Literal['primary', 'secondary', 'derivative']
    independence_group: str = Field(min_length=2, max_length=200)
    provenance_basis: str = Field(min_length=20, max_length=5000)


class EvidenceItem(Record):
    claim_id: UUID
    document_id: UUID
    page: int = Field(ge=1, le=500)
    quote: str = Field(min_length=1, max_length=10000)
    direction: Literal['supports', 'weakens', 'contextual']
    limitations: list[str] = Field(min_length=1, max_length=30)
    translation: str | None = Field(default=None, max_length=10000)
    translation_language: str | None = Field(default=None, max_length=3)
    authenticity_status: Literal['integrity_checked'] = 'integrity_checked'


class Entity(Record):
    entity_type: Literal['Person', 'Organization', 'State', 'PublicBody', 'LegalEntity', 'Event', 'PolicyDecision']
    canonical_name: str = Field(min_length=1, max_length=500)
    aliases: list[str] = Field(default_factory=list, max_length=50)
    jurisdiction: str = Field(min_length=2, max_length=200)
    external_ids: dict[str, str] = Field(default_factory=dict, max_length=20)
    identity_confidence: Literal['unverified', 'documented', 'independently_reviewed']
    identity_basis: str = Field(min_length=20, max_length=5000)


class Relationship(Period):
    subject_id: UUID
    object_id: UUID
    evidence_id: UUID
    predicate: Literal['funded', 'paid', 'received', 'owns', 'beneficially_owns', 'appointed', 'advised',
                       'met_with', 'contracted_with', 'lobbied', 'decided', 'implemented', 'cites',
                       'derived_from', 'supersedes', 'responds_to']
    limitations: str = Field(min_length=10, max_length=5000)
    status: Literal['PROPOSED'] = 'PROPOSED'


class EntityResolution(Record):
    subject_id: UUID
    object_id: UUID
    evidence_id: UUID
    action: Literal['MERGE_ALIAS', 'UNDO_MERGE']
    rationale: str = Field(min_length=20, max_length=5000)
    reverses_id: UUID | None = None


class Withdrawal(Record):
    rationale: str = Field(min_length=20, max_length=5000)


class Member(Record):
    subject: str = Field(min_length=1, max_length=255)
    role: Literal['analyst', 'reader', 'reviewer', 'counsel', 'editor', 'panel', 'respondent']


class Assignment(Record):
    claim_id: UUID
    reviewer_sub: str = Field(min_length=1, max_length=255)


class MemberRevocation(Record):
    member_id: UUID
    rationale: str = Field(min_length=20, max_length=5000)


class Assessment(Record):
    claim_id: UUID
    status: Literal['SUPPORTED', 'CONTRADICTED', 'MIXED', 'INSUFFICIENT_EVIDENCE', 'WITHDRAWN_CORRECTED']
    conflict_declaration: Literal['NO_CONFLICT']
    independence_rationale: str = Field(min_length=20, max_length=5000)
    rationale: str = Field(min_length=20, max_length=5000)
    quotations_checked: Literal[True]
    provenance_checked: Literal[True]
    contradicting_material_considered: str = Field(min_length=20, max_length=5000)
    limitations: str = Field(min_length=20, max_length=5000)
    low_confidence_pages_visually_checked: bool = False


class LegalGate(Record):
    decision: Literal['APPROVE', 'VETO']
    rationale: str = Field(min_length=20, max_length=5000)
    legal_basis: str = Field(min_length=20, max_length=5000)
    privacy_assessment: str = Field(min_length=20, max_length=5000)
    copyright_basis: str = Field(min_length=20, max_length=5000)
    public_content_approved: bool
    personal_data_minimised: bool
    retention_policy: str = Field(min_length=20, max_length=5000)


class PanelGate(Record):
    decision: Literal['APPROVE', 'VETO']
    rationale: str = Field(min_length=20, max_length=5000)
    conflict_declaration: Literal['NO_CONFLICT']
    claim_statuses: dict[UUID, Literal['SUPPORTED', 'CONTRADICTED', 'MIXED', 'INSUFFICIENT_EVIDENCE']] = Field(default_factory=dict)


class ReplyGate(Record):
    disposition: Literal['NO_AFFECTED_PARTY', 'REQUEST_RECORDED']
    rationale: str = Field(min_length=20, max_length=5000)
    request_evidence_id: UUID | None = None
    deadline: datetime | None = None

    @model_validator(mode='after')
    def request_details(self):
        if self.disposition == 'REQUEST_RECORDED':
            if not self.request_evidence_id or not self.deadline or not self.deadline.tzinfo:
                raise ValueError('A documented outreach attempt and timezone-aware deadline are required')
        return self


class Response(Record):
    text: str = Field(min_length=20, max_length=10000)
    evidence_refs: list[UUID] = Field(min_length=1, max_length=30)


class Publication(Record):
    methodology_version: str = Field(min_length=3, max_length=100)
    methodology: str = Field(min_length=50, max_length=10000)
    kind: Literal['PUBLISHED', 'CORRECTED', 'WITHDRAWN'] = 'PUBLISHED'
    reason: str = Field(min_length=20, max_length=5000)
    supersedes_id: UUID | None = None
