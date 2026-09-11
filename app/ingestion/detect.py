from __future__ import annotations

from pathlib import Path


STRUCTURED = {"json", "xml", "csv"}
TEXTUAL = {"txt", "pdf", "eml"}

CLI_ALIASES = {
    "invoice1.txt": "invoice_1001.txt",
    "invoice1": "invoice_1001.txt",
    "invoice2.txt": "invoice_1002.txt",
    "invoice2": "invoice_1002.txt",
}


def detect_format(path: Path, text: str | None = None) -> str:
    suffix = path.suffix.lower().lstrip(".")
    sample = (text or "")[:400]
    if suffix == "pdf":
        return "pdf"
    if suffix == "json" or sample.lstrip().startswith("{"):
        return "json"
    if suffix == "xml" or sample.lstrip().startswith("<?xml") or sample.lstrip().startswith("<invoice"):
        return "xml"
    if suffix == "csv":
        return "csv"
    if "From:" in sample and "Subject:" in sample:
        return "email"
    return "txt"


def resolve_invoice_path(raw: str, invoices_dir: Path) -> Path:
    """Accept the brief's invoice1.txt alias and real filenames."""
    path = Path(raw).expanduser()
    if path.exists():
        return path.resolve()

    name = Path(raw).name
    alias = CLI_ALIASES.get(name) or CLI_ALIASES.get(path.stem)
    if alias:
        candidate = invoices_dir / alias
        if candidate.exists():
            return candidate.resolve()

    candidate = invoices_dir / name
    if candidate.exists():
        return candidate.resolve()

    # invoice1001.txt / invoice-1001.json style slips
    collapsed = name.replace("-", "_")
    for child in invoices_dir.iterdir():
        if child.name.lower() == name.lower() or child.name.lower() == collapsed.lower():
            return child.resolve()

    raise FileNotFoundError(
        f"Invoice not found: {raw}. Looked in {invoices_dir}. "
        "Hint: sample files are named invoice_1001.txt, not invoice1.txt."
    )


def collect_invoice_paths(raw: str, invoices_dir: Path) -> list[Path]:
    path = Path(raw).expanduser()
    if path.is_dir():
        files = [
            p
            for p in sorted(path.iterdir())
            if p.is_file() and p.suffix.lower() in {".txt", ".json", ".csv", ".xml", ".pdf"}
        ]
        if not files:
            raise FileNotFoundError(f"No invoice files in {path}")
        return files
    return [resolve_invoice_path(raw, invoices_dir)]
