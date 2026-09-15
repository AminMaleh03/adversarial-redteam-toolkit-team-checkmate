"""Line-ending regression guard for ``analysis/remediation_rules.json``.

``analysis.remediation.load_rules`` hashes the exact bytes it reads off disk and stamps
that hash into every emitted ``remediation_detail.rule_sha256`` (CONTRACTS.md section 6.7).
On a Windows checkout with ``core.autocrlf=true`` and no matching ``.gitattributes`` entry,
the file used to check out as CRLF, so the hash observed at runtime
(``95ee40bce8e1ddb457b06bdd5c66ba02383b94e51a000d97b23301a258e56879``) silently diverged
from the hash of the committed LF bytes -- the exact failure mode ``.gitattributes`` exists
to prevent for every other hash-recorded file in this repository (see its header comment
and the V6 deployment defect it documents).

This is a real regression found during PR #7 integration review, fixed by adding
``analysis/remediation_rules.json -text`` to ``.gitattributes`` (same treatment as
``analysis/case_sets/*.json`` and ``analysis/policies/*.json``) and renormalizing the
working tree. The constant below is typed in independently of whatever bytes happen to be
checked out right now, so this test cannot pass by re-deriving both sides from the same
(possibly wrong) working-tree file -- a CRLF regression on this path would be caught here,
not discovered later as a silently drifting rule_sha256 in a report.
"""

import hashlib
from pathlib import Path

from analysis.remediation import RULES_PATH, load_rules

# The SHA-256 of the committed LF bytes of analysis/remediation_rules.json, exactly as
# ``git show HEAD:analysis/remediation_rules.json | sha256sum`` reports it. Typed in by
# hand -- do not derive this from the working-tree file, or the test stops testing anything.
CANONICAL_LF_SHA256 = "829a3f8942430d885620f2c4736d9ad54332343d4f2aa16415cc33705d26b894"

# The same file with every LF replaced by CRLF hashes to this instead. Listed so a failure
# here is immediately recognisable as "checked out with the wrong line endings" rather than
# a mystery, and so the two constants can never accidentally be typed in as the same value.
CRLF_DRIFT_SHA256 = "95ee40bce8e1ddb457b06bdd5c66ba02383b94e51a000d97b23301a258e56879"


def test_canonical_and_crlf_constants_are_not_equal():
    """Guards against a copy-paste error that would make this file check nothing."""
    assert CANONICAL_LF_SHA256 != CRLF_DRIFT_SHA256


def test_load_rules_hash_matches_the_pinned_canonical_hash():
    """The hash ``load_rules()`` emits at runtime must match the hard-coded expectation.

    If this fails with ``CRLF_DRIFT_SHA256`` instead, the working tree has checked the
    rules file out with CRLF line endings -- check ``.gitattributes`` for a
    ``analysis/remediation_rules.json -text`` (or equivalent) entry and that it actually
    applies: ``git check-attr text eol -- analysis/remediation_rules.json`` should print
    ``text: unset``.
    """
    observed = load_rules()["sha256"]
    assert observed == CANONICAL_LF_SHA256, (
        f"analysis/remediation_rules.json hashed to {observed!r}, not the pinned "
        f"{CANONICAL_LF_SHA256!r}. If it matches {CRLF_DRIFT_SHA256!r}, the file was "
        "checked out with CRLF line endings -- see .gitattributes."
    )


def test_committed_file_has_no_crlf_bytes():
    """Independent, non-tautological confirmation that the on-disk bytes are pure LF.

    This does not import ``analysis.remediation`` at all, so it cannot share a bug with
    ``load_rules`` -- it reads the same path a second, unrelated way.
    """
    raw = Path(RULES_PATH).read_bytes()
    assert b"\r\n" not in raw, (
        "analysis/remediation_rules.json contains CRLF line endings; expected pure LF "
        "as committed. Check .gitattributes and re-checkout the file."
    )
    assert hashlib.sha256(raw).hexdigest() == CANONICAL_LF_SHA256
