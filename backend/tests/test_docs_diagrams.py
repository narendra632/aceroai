"""The Mermaid diagrams in `docs/` are checked structurally, not trusted.

Written because an audit found four defects in eleven diagrams, and the nastiest one was
invisible: `REQUEST-ANATOMY.md` declared the node id `U2` twice with different labels, so
Mermaid silently kept one and dropped the other. Nothing errored. The diagram just quietly
said something else than it appeared to.

That is the failure mode worth automating away — a diagram that renders *wrong* rather than
not at all. These checks are structural (ids, edges, brackets, fences) and make no claim
about whether a diagram describes the code correctly; only a reader can judge that.

Deliberately no `mermaid-cli`: it pulls Puppeteer and a headless Chromium into CI to catch
strictly less than this does.
"""

import re
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[2] / "docs"

#: `ID["label"]`, `ID([label])`, `ID{label}`, `ID[(label)]`, `ID{{label}}`.
#: The id is what matters; the bracket style only decides the shape drawn.
_NODE = re.compile(
    r"(?<![\w-])([A-Za-z][\w]*)\s*(\[\(|\[|\(\(|\(\[|\(|\{\{|\{)(.+?)(\)\]|\)\)|\]\)|\]|\)|\}\}|\})"
)
#: A --> B, A -.-> B, A ==> B, with an optional |label| between.
_EDGE = re.compile(
    r"([A-Za-z][\w]*)\s*(?:-{2,3}>|-\.->|={2,3}>|---|-\.-)\s*(?:\|[^|]*\|\s*)?([A-Za-z][\w]*)"
)

_FENCE = re.compile(r"^```mermaid\n(.*?)^```", re.M | re.S)

_KEYWORDS = {
    "subgraph",
    "end",
    "flowchart",
    "graph",
    "sequenceDiagram",
    "erDiagram",
    "participant",
    "autonumber",
    "alt",
    "else",
    "opt",
    "loop",
    "Note",
    "note",
    "style",
    "classDef",
    "class",
    "click",
    "linkStyle",
    "direction",
    "over",
    "as",
    "TB",
    "TD",
    "LR",
    "RL",
    "BT",
}


def _blocks() -> list[tuple[Path, int, str]]:
    out = []
    for path in sorted(DOCS.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        for match in _FENCE.finditer(text):
            line = text[: match.start()].count("\n") + 1
            out.append((path, line, match.group(1)))
    return out


ALL = _blocks()


def test_the_docs_actually_contain_diagrams():
    """A guard on the guard: if the extraction regex ever stops matching, every test
    below would pass vacuously and report a clean bill of health on nothing."""
    assert len(ALL) >= 11, f"expected at least 11 mermaid blocks, found {len(ALL)}"


@pytest.mark.parametrize("path,line,body", ALL, ids=[f"{p.name}:{n}" for p, n, _ in ALL])
def test_every_fence_is_closed_and_declares_a_type(path, line, body):
    first = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")
    assert first.split()[0] in {
        "flowchart",
        "graph",
        "sequenceDiagram",
        "erDiagram",
        "stateDiagram",
        "stateDiagram-v2",
        "classDiagram",
        "gantt",
        "pie",
    }, f"{path.name}:{line} — first line is {first!r}, not a diagram type"


@pytest.mark.parametrize("path,line,body", ALL, ids=[f"{p.name}:{n}" for p, n, _ in ALL])
def test_no_node_id_is_declared_twice_with_different_labels(path, line, body):
    """THE bug this file exists for.

    Mermaid takes the first label it sees for an id and ignores later ones. Two nodes that
    are conceptually different but share an id therefore merge into one, silently, and the
    diagram draws an edge to the wrong box.
    """
    labels: dict[str, str] = {}
    for node_id, _open, label, _close in _NODE.findall(body):
        if node_id in _KEYWORDS:
            continue
        label = label.strip()
        if node_id in labels and labels[node_id] != label:
            pytest.fail(
                f"{path.name}:{line} — node id {node_id!r} is declared twice with different "
                f"labels:\n  {labels[node_id]!r}\n  {label!r}\n"
                "Mermaid keeps one and drops the other. Give the second node its own id."
            )
        labels.setdefault(node_id, label)


@pytest.mark.parametrize(
    "path,line,body",
    [b for b in ALL if b[2].lstrip().startswith(("flowchart", "graph"))],
    ids=[f"{p.name}:{n}" for p, n, b in ALL if b.lstrip().startswith(("flowchart", "graph"))],
)
def test_every_edge_connects_declared_nodes(path, line, body):
    """An edge to an id that was never declared is legal Mermaid — it invents a bare,
    unlabelled box. That is almost always a typo, and it renders as a mystery.

    ⚠ The labels must be stripped BEFORE looking for edges. `A["real"] --> TYPO` has a `]`
    where the edge pattern expects an id, so matching the raw text finds no edges at all
    and this test passes without checking anything. It did exactly that until a
    deliberately broken diagram was fed to it.
    """
    declared = {n for n, *_ in _NODE.findall(body) if n not in _KEYWORDS}
    body = _NODE.sub(r"\1", body)  # A["real"] --> B   becomes   A --> B
    # `A --> B & C` fans out; the ampersand form declares nothing new by itself.
    declared |= {
        part.strip()
        for match in re.finditer(r"&\s*([A-Za-z][\w]*)", body)
        for part in [match.group(1)]
    }
    declared |= set(re.findall(r"subgraph\s+([A-Za-z][\w]*)", body))
    for left, right in _EDGE.findall(body):
        for node_id in (left, right):
            if node_id in _KEYWORDS:
                continue
            assert node_id in declared, (
                f"{path.name}:{line} — edge references {node_id!r}, which is never declared. "
                "Mermaid will draw an empty box rather than fail."
            )


#: Crow's-foot cardinality in an erDiagram — `||--o{`, `}o--||`, `}|..|{`. The braces and
#: pipes here are *notation*, not brackets, so they must come out before counting or every
#: ER diagram looks unbalanced. (Caught by this test failing on a correct diagram.)
_CARDINALITY = re.compile(r"[|}o]{1,2}(?:--|\.\.)[|{o]{1,2}")


@pytest.mark.parametrize("path,line,body", ALL, ids=[f"{p.name}:{n}" for p, n, _ in ALL])
def test_brackets_and_quotes_balance(path, line, body):
    countable = _CARDINALITY.sub("", body)
    for open_ch, close_ch in (("[", "]"), ("(", ")"), ("{", "}")):
        assert countable.count(open_ch) == countable.count(close_ch), (
            f"{path.name}:{line} — unbalanced {open_ch}{close_ch}: "
            f"{countable.count(open_ch)} vs {countable.count(close_ch)}"
        )
    assert body.count('"') % 2 == 0, f"{path.name}:{line} — odd number of double quotes"


@pytest.mark.parametrize(
    "path,line,body",
    [b for b in ALL if b[2].lstrip().startswith("sequenceDiagram")],
    ids=[f"{p.name}:{n}" for p, n, b in ALL if b.lstrip().startswith("sequenceDiagram")],
)
def test_sequence_messages_use_declared_participants(path, line, body):
    declared = set(re.findall(r"participant\s+([A-Za-z][\w]*)", body))
    assert declared, f"{path.name}:{line} — sequenceDiagram declares no participants"
    for left, right in re.findall(
        r"^\s*([A-Za-z][\w]*)\s*-(?:->>|->|-x|-\)|>>)\s*([A-Za-z][\w]*)\s*:", body, re.M
    ):
        for who in (left, right):
            assert who in declared, (
                f"{path.name}:{line} — message involves {who!r}, "
                f"which is not a declared participant"
            )


def test_architecture_sections_are_lettered_in_order():
    """Found by the audit: the sections ran (a) (b) (c) (e) (d) (e) — two (e)s, out of
    order — because a new section was inserted without re-lettering the ones after it."""
    text = (DOCS / "ARCHITECTURE.md").read_text(encoding="utf-8")
    letters = re.findall(r"^### \(([a-z])\)", text, re.M)
    expected = [chr(ord("a") + i) for i in range(len(letters))]
    assert letters == expected, f"walkthrough sections run {letters}, expected {expected}"
