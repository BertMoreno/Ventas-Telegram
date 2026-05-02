"""
Script de ingesta de documentos.
Indexa todos los PDFs y TXTs de la carpeta 'docs/' en la base de conocimiento.

Uso:
    python ingest.py

Después de añadir nuevos documentos vuelve a ejecutarlo para re-indexar.
"""

from pathlib import Path

from rich.console import Console
from rich.progress import track

console = Console()


def split_into_chunks(text: str, chunk_size: int = 800, overlap: int = 150) -> list[str]:
    """Split text into overlapping word-level chunks."""
    words = text.split()
    chunks = []
    start = 0
    while start < len(words):
        chunk = " ".join(words[start: start + chunk_size])
        if len(chunk.strip()) > 80:
            chunks.append(chunk)
        start += chunk_size - overlap
    return chunks


def extract_pdf(path: Path) -> str:
    try:
        import pdfplumber
        pages = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    pages.append(text)
        return "\n".join(pages)
    except ImportError:
        pass

    # Fallback: PyPDF2
    try:
        import PyPDF2
        pages = []
        with open(path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    pages.append(text)
        return "\n".join(pages)
    except ImportError:
        raise ImportError(
            "Instala pdfplumber para leer PDFs: pip install pdfplumber"
        )


def ingest():
    docs_dir = Path("docs")
    docs_dir.mkdir(exist_ok=True)

    all_files = list(docs_dir.glob("**/*.pdf")) + list(docs_dir.glob("**/*.txt"))

    if not all_files:
        console.print(
            "[yellow]No hay documentos en la carpeta 'docs/'.[/yellow]\n"
            "Copia tus PDFs o archivos de texto ahí y vuelve a ejecutar este script."
        )
        return

    console.print(f"[cyan]Documentos encontrados: {len(all_files)}[/cyan]")

    try:
        import chromadb
        from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
    except ImportError:
        console.print("[red]Error: ejecuta primero → pip install -r requirements.txt[/red]")
        return

    console.print("[dim]Cargando modelo de embeddings (primera vez tarda ~1 min)...[/dim]")
    embedding_fn = SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")

    db_client = chromadb.PersistentClient(path="vectordb")

    # Re-create collection for clean indexing
    try:
        db_client.delete_collection("management_docs")
    except Exception:
        pass

    collection = db_client.create_collection(
        name="management_docs",
        embedding_function=embedding_fn,
        metadata={"hnsw:space": "cosine"},
    )

    all_chunks: list[str] = []
    all_meta: list[dict] = []
    all_ids: list[str] = []

    for file_path in track(all_files, description="Procesando..."):
        try:
            if file_path.suffix.lower() == ".pdf":
                text = extract_pdf(file_path)
            else:
                text = file_path.read_text(encoding="utf-8", errors="ignore")

            chunks = split_into_chunks(text)
            for i, chunk in enumerate(chunks):
                all_chunks.append(chunk)
                all_meta.append({"source": file_path.name, "chunk": i})
                all_ids.append(f"{file_path.stem}_{i}")

        except Exception as e:
            console.print(f"[red]Error con {file_path.name}: {e}[/red]")

    if not all_chunks:
        console.print("[yellow]No se pudo extraer texto de los documentos.[/yellow]")
        return

    # Insert in batches
    batch = 100
    for i in range(0, len(all_chunks), batch):
        collection.add(
            documents=all_chunks[i: i + batch],
            metadatas=all_meta[i: i + batch],
            ids=all_ids[i: i + batch],
        )

    console.print(
        f"[green]✅ Listo: {len(all_chunks)} fragmentos indexados "
        f"de {len(all_files)} documentos.[/green]"
    )


if __name__ == "__main__":
    ingest()
