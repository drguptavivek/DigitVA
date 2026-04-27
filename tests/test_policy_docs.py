from pathlib import Path

REQUIRED_FRONT_MATTER = {"title", "doc_type", "status", "owner", "last_updated"}


def _front_matter_keys(path: Path) -> set[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "---"
    end = lines.index("---", 1)
    return {
        line.split(":", 1)[0].strip()
        for line in lines[1:end]
        if ":" in line
    }


def test_who_2022_icd_policy_doc_has_front_matter_and_readme_link():
    doc_path = Path("docs/policy/who-2022-icd10-coding-allowability.md")
    readme_path = Path("docs/policy/README.md")

    assert REQUIRED_FRONT_MATTER.issubset(_front_matter_keys(doc_path))
    assert "who-2022-icd10-coding-allowability.md" in readme_path.read_text(
        encoding="utf-8"
    )
