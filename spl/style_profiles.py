"""Style profiles for concept-book content generation.

Each profile defines HOW verified content is written — tone, depth, audience,
structure — without changing WHAT is true.  The symbolic check
(graph_lib.verify_content) is style-agnostic; only the prose adapts.

A profile is resolved to a style_guide string by style_instruction(), which is
called via SOLVE in the SPL workflow and injected into every GENERATE prompt.

Identical copy of cookbook/73_intro_geometry/style_profiles.py's seven
profiles — the superset that adds ``middle_school``/``high_school`` to the
five recipe 71 originals. Recipe 74 compiles ONE source against whichever
@domain_yaml is resolved at runtime, so its style menu can't be tailored to
one domain's "natural" audience the way 71/73 each were; carrying the full
seven forward means every domain this recipe might load (linalg, geometry, or
a future one) gets the complete range a learner could plausibly want, rather
than a domain-specific subset baked in at compile time.
"""

from __future__ import annotations

STYLE_PROFILES: dict[str, dict[str, str]] = {
    "feynman": {
        "label": "Feynman explains",
        "tone": "intuitive and story-driven; ask 'why does this feel right?' before formalising",
        "depth": "concept-first — build intuition, Introducing a concept using the Feynman technique by focusing on conceptual understanding, no math initially, definitely no formulae or formal proofs",
        "audience": "beginner or elementary through middle-school students (grades 1–5)",
        "length": "100–200 words per section",
        "structure": "Motivating story → Intuition → Minimal formalisation → 'Now you try'",
    },
    "core": {
        "label": "Core (middle school through high school)",
        "tone": "encouraging and exploratory; the student is starting to take the topic "
                "seriously, not just hearing about it for the first time",
        "depth": "go past the intro-level analogy into the concept's actual structure — "
                 "introduce light formal notation only where the student is ready for it; "
                 "no proofs. Close with one short, approachable practice problem (homework "
                 "style) the student can actually attempt with what was just taught",
        "audience": "middle-school to high-school student (grades 6–12) beginning to "
                    "explore the topic beyond a first-pass intuition",
        "length": "200–300 words per section",
        "structure": "Recap the intuition briefly → Explore the idea's structure → "
                     "Simple rule or pattern → Short practice problem (homework-style)",
    },
    "middle_school": {
        "label": "Middle school (grades 6–8)",
        "tone": "warm and encouraging; define every new term in plain words the moment it appears",
        "depth": "one idea at a time, concrete before abstract; heavy scaffolding, no formal proofs",
        "audience": "11-14 year old comfortable with arithmetic and pre-algebra, no calculus",
        "length": "150–250 words per section",
        "structure": "Everyday example → Picture this (visual description) → Simple rule → Try it yourself",
    },
    "high_school": {
        "label": "High school (grades 9–12)",
        "tone": "clear and motivating; build toward formal reasoning without losing the reader along the way",
        "depth": "definition, worked example, and a short 'why it's true' justification — first steps toward proof",
        "audience": "14-18 year old with an algebra 1 background, preparing for standardized tests (SAT/ACT)",
        "length": "250–350 words per section",
        "structure": "Real-world hook → Definition → Worked example → Why it's true → Practice problem",
    },
    "college": {
        "label": "College course text (AP through undergraduate)",
        "tone": "clear, precise, and applied — not artificially formal",
        "depth": "go beyond conceptual understanding toward applying the concept to solve "
                 "problems — the emphasis is problem-solving practice, not just definition. "
                 "Introduce a formal theorem, proof, or heavy mathematical notation ONLY if "
                 "the concept is intrinsically a mathematical/theoretical result that cannot "
                 "be correctly understood without it (e.g. a limit, a matrix decomposition, "
                 "a probability law). For concepts that are fundamentally practical — tools, "
                 "protocols, systems, processes, software, ethical/legal frameworks — explain "
                 "in plain, precise prose and demonstrate with code or a concrete scenario "
                 "instead of inventing notation, algebraic formalism, or a 'theorem' the "
                 "concept doesn't actually have",
        "audience": "high-school AP student through undergraduate, with general "
                    "quantitative literacy; not assumed to want or need notation for its "
                    "own sake",
        "length": "300–400 words per section",
        "structure": "Definition → Worked example → Problem-solving application (add a "
                     "formal theorem/proof step only when the concept genuinely requires "
                     "one)",
    },
    "research": {
        "label": "Research / project-driven (math, physics, engineering)",
        "tone": "dense and formal; theorem-proof style; citation-ready",
        "depth": "frame the concept as an open research question, not a settled fact to "
                 "recite. Full proof or derivation, connection to standard references and "
                 "current literature, remarks on generality and open problems. Point toward "
                 "a concrete project: what a graduate student would derive, replicate, or "
                 "extend, and what a short experiment or investigation of it would involve",
        "audience": "graduate student engaged in project-driven study — reads literature, "
                    "runs experiments or derivations, writes up findings — not a passive "
                    "reader of a settled reference entry",
        "length": "350–600 words per section",
        "structure": "Definition → Theorem/Proof → Literature context (what's known, what's "
                     "open) → Suggested investigation or experiment → Report-writing note "
                     "(what a write-up of this investigation should establish)",
    },
    "research_applied": {
        "label": "Research / project-driven (applied, non-mathematical domain)",
        "tone": "dense, formal, and citation-ready — but never inventing mathematical or "
                "proof notation for a concept that is not itself a mathematical result",
        "depth": "frame the concept as an open question worth investigating, not a settled "
                 "fact to recite. Precise technical definition, mechanism, and connection to "
                 "current literature and practice, at graduate/professional rigor; formal "
                 "theorem/proof notation ONLY if the concept genuinely is a mathematical or "
                 "statistical result (e.g. a convergence guarantee, a complexity bound) — for "
                 "concepts that are systems, protocols, regulations, biological mechanisms, "
                 "or chemical processes, give the equivalent rigor in precise prose and, "
                 "where relevant, code, not invented formalism. Point toward a concrete "
                 "project: what a graduate student would investigate, measure, or build, and "
                 "what an experiment or case study of it would involve",
        "audience": "graduate student or professional in a technology, life-science, or "
                    "applied field engaged in project-driven study — reads literature, build project, "
                    "runs experiments or case studies, writes up findings — not a passive reader "
                    "of a settled reference entry",
        "length": "350–600 words per section",
        "structure": "Definition → Mechanism/process → Literature context (what's known, "
                     "what's open) → Suggested investigation or experiment → Report-writing "
                     "note (what a write-up of this investigation should establish)",
    },
    "textbook": {
        "label": "University textbook",
        "tone": "precise and formal",
        "depth": "full definition, proof sketch, concrete worked example",
        "audience": "first-year university student with calculus background",
        "length": "200–400 words per section",
        "structure": "Definition → Worked example → Key theorem → Lab cell (SymPy)",
    },
    "flashcard": {
        "label": "Anki flashcard set",
        "tone": "terse, precise, exam-ready",
        "depth": "one fact per card; no proofs, just the statement and one example",
        "audience": "student reviewing the night before an exam",
        "length": "50–100 words per section (one Q&A pair per key fact)",
        "structure": "Q: [precise question]  A: [minimal complete answer]  Example: [one line]",
    },
    "instructor": {
        "label": "Instructor teaching notes",
        "tone": "pedagogical; explicitly name common misconceptions and how to counter them",
        "depth": "concept summary + typical student errors + suggested in-class exercise",
        "audience": "instructor preparing a lecture or recitation",
        "length": "300–500 words per section",
        "structure": "Concept summary → Common mistakes → Teaching tip → Suggested exercise",
    },
}


def get_style_profile(style: str) -> dict[str, str]:
    """Return the profile dict for the named style.

    Raises ValueError for unknown style names.
    """
    profile = STYLE_PROFILES.get(style)
    if profile is None:
        available = ", ".join(f"'{s}'" for s in STYLE_PROFILES)
        raise ValueError(f"Unknown style: {style!r}. Available: {available}")
    return profile


def style_instruction(style: str) -> str:
    """Return a prose instruction block for injecting into LLM prompts.

    Called via SOLVE @style_guide TEXT := style_instruction(@style) in the
    SPL workflow.  The returned string is passed as {style_guide} into every
    GENERATE prompt template so the LLM writes in the chosen style.
    """
    p = get_style_profile(style)
    return (
        f"STYLE GUIDE — {p['label']}\n"
        f"Tone      : {p['tone']}\n"
        f"Depth     : {p['depth']}\n"
        f"Audience  : {p['audience']}\n"
        f"Length    : {p['length']}\n"
        f"Structure : {p['structure']}"
    )


def available_styles() -> list[str]:
    """Return the list of supported style names."""
    return list(STYLE_PROFILES.keys())


# ---------------------------------------------------------------------------
# Quick smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    for name in STYLE_PROFILES:
        print(f"\n{'='*60}")
        print(style_instruction(name))
