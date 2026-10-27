from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')

class Finding(StrictModel):
    value: str
    origin: Literal['explicit','inferred']
    excerpt: str

class Requirement(StrictModel):
    key: str
    label: str
    category: Literal['skill','experience','qualification','responsibility','behaviour','eligibility']
    importance: Literal['required','preferred','unspecified']
    origin: Literal['explicit','inferred']
    excerpt: str

class RoleProfile(StrictModel):
    title: Finding
    seniority: Finding
    responsibilities: list[Finding]
    required_skills: list[Finding]
    preferred_skills: list[Finding]
    technical_competencies: list[Finding]
    behavioural_competencies: list[Finding]
    experience_expectations: list[Finding]
    keywords: list[Finding]
    concepts: list[Finding]
    qualifications: list[Finding]
    other_requirements: list[Finding]
    requirements: list[Requirement]

class CandidateProfile(StrictModel):
    skills: list[Finding]
    experience: list[Finding]
    projects: list[Finding]
    achievements: list[Finding]
    education: list[Finding]
    certifications: list[Finding]
    claims_to_probe: list[Finding]

class Match(StrictModel):
    requirement_key: str
    status: Literal['strong','partial','not_evidenced']
    resume_excerpts: list[str]
    reason: str
    preparation_note: str
    probe_target: str

class MatchOutput(StrictModel):
    matches: list[Match]

class DocumentsInput(StrictModel):
    jd_text: str = Field(min_length=20,max_length=10000)
    resume_text: str = Field(min_length=20,max_length=14000)
    jd_filename: str = Field(default='',max_length=200)
    resume_filename: str = Field(default='',max_length=200)
