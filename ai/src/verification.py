"""
Post-generation verification: checks that every citation in a draft
response actually corresponds to a real, retrieved policy document.
This is a rule-based safety net on top of prompt-level grounding
instructions — catching the rare case where the model cites a source
that wasn't actually provided to it.
"""
import re


def extract_citations(draft_text: str) -> list[str]:
    """
    Finds every [Source: filename] citation in the draft text.
    Returns a list of the filenames referenced (may contain duplicates).
    """
    # Matches "[Source: something.txt]" and captures "something.txt"
    pattern = r"\[Source:\s*([^\]]+)\]"
    matches = re.findall(pattern, draft_text)
    return [m.strip() for m in matches]


def verify_citations(draft_text: str, retrieved_sources: list[str]) -> dict:
    """
    Compares citations found in the draft against the actual retrieved
    source filenames. Returns a report dict:
      - cited: all citations found in the draft
      - valid: citations that match a real retrieved source
      - invalid: citations that DON'T match any retrieved source (a red flag)
      - fully_grounded: True only if every citation is valid
    """
    cited = extract_citations(draft_text)
    retrieved_set = set(retrieved_sources)

    valid = [c for c in cited if c in retrieved_set]
    invalid = [c for c in cited if c not in retrieved_set]

    return {
        "cited": cited,
        "valid": valid,
        "invalid": invalid,
        "fully_grounded": len(invalid) == 0,
    }


if __name__ == "__main__":
    # Quick manual test
    test_draft = (
        "Your order is delayed [Source: logistics_delivery.txt]. "
        "We also checked our internal notes [Source: made_up_file.txt]. "
        "No further citation needed here."
    )
    test_sources = ["logistics_delivery.txt", "logistics_delivery.txt"]

    result = verify_citations(test_draft, test_sources)
    import json
    print(json.dumps(result, indent=2))