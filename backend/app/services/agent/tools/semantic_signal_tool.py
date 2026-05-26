import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SemanticSignalInput:
    query: str
    keywords: list[str] = field(default_factory=list)
    evidence_id: str = ""


@dataclass(frozen=True)
class SemanticSignalOutput:
    anchors: list[str]
    domains: list[str]


class SemanticSignalTool:
    """Agent tool for extracting semantic anchors and domains from a user turn."""

    name = "semantic_signal_extractor"

    def run(self, tool_input: SemanticSignalInput) -> SemanticSignalOutput:
        from app.services.agent.planning.semantic_signals import (
            anchor_domains,
            extract_semantic_anchors,
        )

        anchors = extract_semantic_anchors(tool_input.query, tool_input.keywords)
        domains = anchor_domains(anchors)
        logger.info(
            "agent.tool name=semantic_signal_extractor status=succeeded anchors=%s domains=%s keyword_count=%s evidence_id=%s",
            anchors,
            domains,
            len(tool_input.keywords),
            tool_input.evidence_id,
        )
        return SemanticSignalOutput(anchors=anchors, domains=domains)
