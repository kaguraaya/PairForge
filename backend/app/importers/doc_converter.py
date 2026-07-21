from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


class DocConversionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def convert_doc_to_docx(source: Path, output_dir: Path) -> Path:
    executable = shutil.which("soffice") or shutil.which("libreoffice")
    if not executable:
        raise DocConversionError("LIBREOFFICE_NOT_FOUND", "未检测到 LibreOffice，无法转换 .doc 文件。")
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="double-image-lo-") as profile:
        result = subprocess.run(
            [
                executable,
                "--headless",
                f"-env:UserInstallation=file:///{Path(profile).as_posix()}",
                "--convert-to",
                "docx",
                "--outdir",
                str(output_dir),
                str(source),
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    target = output_dir / f"{source.stem}.docx"
    if result.returncode != 0 or not target.exists() or target.stat().st_size == 0:
        raise DocConversionError(
            "DOC_CONVERSION_FAILED",
            (result.stderr or result.stdout or "DOC 转换失败。").strip(),
        )
    return target

