from pathlib import Path

import fitz

workspace = Path(r"D:\pythonsrc\scripts")
source = workspace / "output" / "pdf" / "答辩问题参考答案.pdf"
out_dir = workspace / "tmp" / "pdfs" / "qa_pages"
out_dir.mkdir(parents=True, exist_ok=True)

doc = fitz.open(source)
for index, page in enumerate(doc, start=1):
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
    pix.save(out_dir / f"page-{index:02d}.png")
print(f"pages={doc.page_count}")
print(f"title={doc.metadata.get('title')}")
print(f"chars={sum(len(page.get_text()) for page in doc)}")
