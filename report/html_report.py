from pathlib import Path
import json
import shutil


class HTMLReport:

    def __init__(self):
        self.project_root = Path(__file__).resolve().parent.parent
        self.template_dir = self.project_root / "reports"

    def generate(self, report, destination: Path):

        destination.mkdir(parents=True, exist_ok=True)

        data = {
            "total_files": report.total_files,
            "total_size": report.total_size,
            "duplicates": report.duplicate_count,
            "categories": dict(report.category_counter),
            "files": []
        }

        for f in report.files:

            data["files"].append({

                "name": f.filename,
                "category": f.category,
                "mime": f.mime,
                "size": f.size,
                "sha256": f.sha256,
                "output": str(f.output_path.resolve()) if f.output_path else "",
                "source_path": str((f.source_path or f.path).resolve()),
                "source_directory": f.source_directory or f.path.parent.name

            })

        template_path = self.template_dir / "template.html"

        if not template_path.exists():
            raise FileNotFoundError(template_path)

        html = template_path.read_text(encoding="utf-8")

        html = html.replace(
            "__CARVEX_DATA__",
            json.dumps(data, ensure_ascii=False)
        )

        (destination / "index.html").write_text(
            html,
            encoding="utf-8"
        )

        shutil.copy2(
            self.template_dir / "style.css",
            destination / "style.css"
        )

        shutil.copy2(
            self.template_dir / "app.js",
            destination / "app.js"
        )

        print(f"Rapport HTML généré : {destination / 'index.html'}")
