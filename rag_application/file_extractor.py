import io
from pypdf import PdfReader
import docx

# Well-known config/build files that have NO extension at all —
# file_path.split(".")[-1] would otherwise treat the whole filename
# (e.g. "dockerfile") as the "extension" and miss these.
KNOWN_EXTENSIONLESS_TEXT_FILES = {
    "dockerfile", "makefile", "jenkinsfile", "procfile",
    "dockerignore", "gitignore", "env", "editorconfig",
}

# Plain-text-ish extensions we know how to read as-is.
TEXT_EXTENSIONS = {
    'txt', 'md', 'csv', 'json', 'py', 'log',
    'yaml', 'yml', 'toml', 'ini', 'cfg', 'conf',
    'sh', 'bash', 'env', 'js', 'ts', 'sql', 'xml', 'ipynb',
}

def extract_text(file_path: str, file_bytes: bytes):
    filename = file_path.strip().lower()
    # e.g. "Dockerfile" -> "dockerfile", ".gitignore" -> "gitignore"
    base_name = filename.lstrip(".").rsplit("/", 1)[-1]
    has_extension = "." in filename.lstrip(".")
    file_extention = filename.split(".")[-1] if has_extension else ""

    if base_name in KNOWN_EXTENSIONLESS_TEXT_FILES or file_extention in TEXT_EXTENSIONS:
        return file_bytes.decode('utf-8', errors='ignore')
    elif file_extention == 'pdf':
        pdf_stream = io.BytesIO(file_bytes)
        reader = PdfReader(pdf_stream)
        extracted_pages = []
        
        for page_num, page in enumerate(reader.pages):
            text = page.extract_text()
            if text:
                extracted_pages.append(text)
                
        return "\n\n".join(extracted_pages)
    elif file_extention == 'docx':
        docx_stream = io.BytesIO(file_bytes)
        doc = docx.Document(docx_stream)
        
        # Read all text from paragraphs and tables
        full_text = [p.text for p in doc.paragraphs if p.text.strip()]
        
        
        for table in doc.tables:
            for row in table.rows:
                row_text = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if row_text:
                    full_text.append(" | ".join(row_text))
                    
        return "\n".join(full_text)
    else:
        # Last resort: many config/build files (e.g. .tf, .cfg, unusual
        # extensions) are still plain text. Try decoding before giving up,
        # so a file only fails if it's genuinely binary/unreadable.
        try:
            return file_bytes.decode('utf-8')
        except UnicodeDecodeError:
            raise ValueError(f"Unsupported file format: .{file_extention or base_name}")