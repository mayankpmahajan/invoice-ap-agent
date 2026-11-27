from pathlib import Path

from app.main import dist_file


def _dist(tmp_path: Path) -> Path:
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("ui")
    (root / "assets" / "app.js").write_text("js")
    (tmp_path / ".env").write_text("SECRET=1")
    return root


def test_serves_files_inside_the_ui_folder(tmp_path):
    root = _dist(tmp_path)
    assert dist_file(root, "assets/app.js") == (root / "assets" / "app.js").resolve()
    assert dist_file(root, "runs/abc") == (root / "index.html").resolve()  # client-side route


def test_never_serves_files_outside_the_ui_folder(tmp_path):
    root = _dist(tmp_path)
    for path in ("../.env", "assets/../../.env", "/etc/hosts", str(tmp_path / ".env")):
        assert dist_file(root, path) == (root / "index.html").resolve(), path
