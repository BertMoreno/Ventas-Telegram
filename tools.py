"""
Herramientas del asistente de management:
- search_documents: busca en libros/PDFs indexados
- get_sales_summary: lee datos de ventas del equipo
  → Si GOOGLE_SCRIPT_URL está en .env, lee en tiempo real desde Google Drive.
  → Si no, lee los archivos locales de sales_data/.
- get_report_notes: recupera historial de un colaborador
- save_report_note: guarda nota sobre un colaborador
"""

import json
import os
from pathlib import Path
from datetime import datetime

import pandas as pd

MEMORY_DIR = Path("memory")
MEMORY_DIR.mkdir(exist_ok=True)

# Orden de prioridad para fuentes locales de ventas:
# 1) SALES_DATA_DIRS en .env (separado por comas)
# 2) carpetas por defecto: sales_data/, sales/, data/
DEFAULT_SALES_DATA_DIRS = [Path("sales_data"), Path("sales"), Path("data")]


def _sales_data_dirs() -> list[Path]:
    raw = os.getenv("SALES_DATA_DIRS", "").strip()
    if raw:
        dirs: list[Path] = []
        for item in raw.split(","):
            item = item.strip()
            if item:
                dirs.append(Path(item))
        if dirs:
            return dirs
    return DEFAULT_SALES_DATA_DIRS


# ---------------------------------------------------------------------------
# Knowledge base search
# ---------------------------------------------------------------------------

def search_documents(query: str, n_results: int = 3) -> str:
    """Search indexed PDFs/docs for content relevant to the query."""
    try:
        import chromadb
        import chromadb.utils.embedding_functions as embedding_functions
    except ImportError:
        return "⚠️ Dependencias no instaladas. Ejecuta: pip install -r requirements.txt"

    db_path = Path("vectordb")
    if not db_path.exists() or not any(db_path.iterdir()):
        return (
            "⚠️ La base de conocimiento está vacía.\n"
            "Añade PDFs a la carpeta 'docs/' y ejecuta: python ingest.py"
        )

    try:
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            return "⚠️ Error: Añade GOOGLE_API_KEY en tu archivo .env o Railway"

        # ChromaDB's GoogleGeminiEmbeddingFunction expects GEMINI_API_KEY by default
        os.environ["GEMINI_API_KEY"] = api_key

        embedding_fn = embedding_functions.GoogleGeminiEmbeddingFunction(
            model_name="models/gemini-embedding-001"
        )
        client = chromadb.PersistentClient(path=str(db_path))
        collection = client.get_collection("management_docs", embedding_function=embedding_fn)

        if collection.count() == 0:
            return "⚠️ No hay documentos indexados. Ejecuta: python ingest.py"

        results = collection.query(
            query_texts=[query],
            n_results=min(n_results, collection.count()),
        )

        if not results["documents"][0]:
            return "No se encontró información relevante en la base de conocimiento."

        parts = []
        for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
            source = meta.get("source", "Documento desconocido")
            parts.append(f"**Fuente: {source}**\n{doc}")

        return "\n\n---\n\n".join(parts)

    except Exception as e:
        return f"Error buscando en la base de conocimiento: {e}"


# ---------------------------------------------------------------------------
# Sales data
# ---------------------------------------------------------------------------

PERSON_KEYWORDS = ["visitador", "nombre", "name", "vendedor", "comercial", "rep", "persona"]
_EXCEL_EPOCH_DT = __import__("datetime").datetime(1899, 12, 30)
EXCEL_EPOCH = pd.Timestamp("1899-12-30")


def _fix_excel_date_as_number(combined: pd.DataFrame) -> pd.DataFrame:
    """
    Pandas a veces lee columnas numéricas de Excel (importes, etc.) como datetime
    cuando la celda tiene formato de fecha aplicado accidentalmente.
    Hay dos casos:
      1) dtype datetime64[ns] — columnas detectadas por pandas como fechas
      2) dtype object con valores datetime.datetime — Excel las leyó como objetos Python
    Si la mediana del año < 1950, son claramente importes mal formateados como fecha.
    Los convertimos al número de serie de Excel (días desde 1899-12-30).
    """
    import datetime as _dt

    # Caso 1: dtype datetime64[ns]
    for col in combined.select_dtypes(include=["datetime64[ns]"]).columns:
        sample = combined[col].dropna()
        if len(sample) > 0 and sample.dt.year.median() < 1950:
            combined[col] = (combined[col] - EXCEL_EPOCH).dt.days

    # Caso 2: dtype object cuyos valores son datetime.datetime de Python
    for col in combined.select_dtypes(include=["object"]).columns:
        sample = combined[col].dropna()
        if len(sample) == 0:
            continue
        first = sample.iloc[0]
        if not isinstance(first, (_dt.datetime, _dt.date)):
            continue
        # Comprobar que el año mediano es < 1950 (descarta columnas de fecha reales)
        years = sample.apply(lambda x: x.year if isinstance(x, (_dt.datetime, _dt.date)) else None).dropna()
        if years.median() >= 1950:
            continue
        # Convertir a número de días (serial Excel)
        def _to_days(x):
            if isinstance(x, _dt.datetime):
                return (x - _EXCEL_EPOCH_DT).total_seconds() / 86400
            if isinstance(x, _dt.date):
                return (_dt.datetime.combine(x, _dt.time()) - _EXCEL_EPOCH_DT).days
            return None
        combined[col] = sample.map(_to_days).reindex(combined.index)

    return combined


def _get_sales_from_drive(filter_person: str = None, period: str = "all") -> str | None:
    """
    Lee datos de ventas en tiempo real desde Google Drive via Apps Script.
    Devuelve None si GOOGLE_SCRIPT_URL no está configurada.
    """
    script_url = os.getenv("GOOGLE_SCRIPT_URL", "").strip()
    if not script_url:
        return None

    try:
        import urllib.request
        import urllib.parse

        params: dict = {}
        if filter_person:
            params["visitador"] = filter_person
        if period and period != "all":
            params["sheet"] = period

        url = script_url
        if params:
            url = f"{script_url}?{urllib.parse.urlencode(params)}"

        req = urllib.request.Request(url, headers={"User-Agent": "AgentePrueba/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))

        if not payload.get("ok"):
            return f"⚠️ Error del Apps Script: {payload.get('error', 'desconocido')}"

        records = payload.get("records", [])
        if not records:
            msg = f"No se encontraron datos"
            if filter_person:
                msg += f" para '{filter_person}'"
            return msg + "."

        df = pd.DataFrame(records)

        # Asegurar tipos numéricos
        for col in ["num_audifonos", "total_sin_iva", "año", "mes"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        lines = [
            f"**Datos de ventas (Google Drive — tiempo real)**",
            f"Registros: {len(df)}",
            f"Columnas: {', '.join(df.columns.tolist())}\n",
        ]

        # Estadísticas numéricas clave
        for col in ["num_audifonos", "total_sin_iva"]:
            if col in df.columns:
                col_data = df[col].dropna()
                if len(col_data) > 0:
                    lines.append(
                        f"- {col}: Total={col_data.sum():,.2f} | "
                        f"Media={col_data.mean():,.2f} | "
                        f"Min={col_data.min():,.2f} | Max={col_data.max():,.2f}"
                    )

        # Resumen por visitador (solo cuando no se filtra por persona)
        if "nombre_visitador" in df.columns and not filter_person:
            lines.append("\n**Resumen por visitador:**")
            agg_cols = {c: "sum" for c in ["num_audifonos", "total_sin_iva"] if c in df.columns}
            agg_cols["nombre_visitador"] = "count"
            grp = (
                df.groupby("nombre_visitador")
                .agg(
                    ventas=("nombre_visitador", "count"),
                    **{c: (c, "sum") for c in ["num_audifonos", "total_sin_iva"] if c in df.columns},
                )
                .sort_values("ventas", ascending=False)
            )
            lines.append(grp.to_string())

        lines.append(f"\n**Primeros 10 registros:**")
        lines.append(df.head(10).to_string(index=False))

        return "\n".join(lines)

    except Exception as e:
        return f"⚠️ Error leyendo desde Google Drive: {e}"


def get_sales_summary(filter_person: str = None, period: str = "all") -> str:
    """
    Obtiene resumen de ventas.
    Prioridad: Google Drive (Apps Script) → archivos locales en sales_data/.
    """
    # 1. Intentar Drive primero
    drive_result = _get_sales_from_drive(filter_person=filter_person, period=period)
    if drive_result is not None:
        return drive_result

    # 2. Fallback: archivos locales
    data_files: list[Path] = []
    searched_dirs = []
    for data_dir in _sales_data_dirs():
        searched_dirs.append(str(data_dir))
        if not data_dir.exists():
            continue
        data_files.extend(list(data_dir.glob("*.csv")))
        data_files.extend(list(data_dir.glob("*.xlsx")))
        data_files.extend(list(data_dir.glob("*.xls")))

    if not data_files:
        return (
            "⚠️ No hay archivos de ventas.\n"
            "Configura GOOGLE_SCRIPT_URL en .env o añade archivos CSV/Excel en: "
            f"{', '.join(searched_dirs)}.\n"
            "Tip: también puedes definir SALES_DATA_DIRS=carpeta1,carpeta2 en .env."
        )

    try:
        dfs = []
        for f in data_files:
            if f.suffix == ".csv":
                df = pd.read_csv(f)
            else:
                # Si period no es 'all', intentamos leer esa hoja específica
                sheet_to_read = period if period != "all" else 0
                try:
                    df = pd.read_excel(f, sheet_name=sheet_to_read)
                except Exception:
                    # Si falla (ej: la hoja no existe en este archivo), saltamos o leemos la primera
                    continue
            df["_archivo"] = f.name
            dfs.append(df)

        combined = pd.concat(dfs, ignore_index=True)

        # Corregir columnas numéricas mal leídas como fechas (ej: IMPORTE SIN IVA)
        combined = _fix_excel_date_as_number(combined)

        # Identificar columna de persona (vendedor/visitador)
        CODE_INDICATORS = ["código", "cód", "cod ", "cod_", " cod"]
        person_cols = [
            c for c in combined.columns
            if any(kw in c.lower() for kw in PERSON_KEYWORDS)
            and not any(ci in c.lower() for ci in CODE_INDICATORS)
        ]
        if not person_cols:
            person_cols = [
                c for c in combined.columns
                if any(kw in c.lower() for kw in PERSON_KEYWORDS)
            ]
        person_col = person_cols[0] if person_cols else None

        # Filtrar por persona
        if filter_person:
            if not person_cols:
                return f"No se encontró columna de vendedor/visitador para filtrar por '{filter_person}'."
            mask = pd.Series(False, index=combined.index)
            for col in person_cols:
                mask |= (
                    combined[col]
                    .astype(str)
                    .str.lower()
                    .str.contains(filter_person.lower(), na=False)
                )
            combined = combined[mask]
            if combined.empty:
                return f"No se encontraron datos para '{filter_person}'."

        file_names = ", ".join(f.name for f in data_files)
        lines = [
            f"**Datos de ventas** ({file_names})",
            f"Registros totales: {len(combined)}",
            f"Columnas: {', '.join(combined.columns.tolist())}\n",
        ]

        skip_stats_keywords = ["código", "cod", "cód", "año", "mes", "_archivo"]
        numeric_cols = combined.select_dtypes(include="number").columns.tolist()
        stat_cols = [
            c for c in numeric_cols
            if not any(kw in c.lower() for kw in skip_stats_keywords)
        ]
        if stat_cols:
            lines.append("**Estadísticas numéricas:**")
            for col in stat_cols[:8]:
                col_data = combined[col].dropna()
                if len(col_data) > 0:
                    lines.append(
                        f"- {col}: Total={col_data.sum():,.2f} | "
                        f"Media={col_data.mean():,.2f} | "
                        f"Min={col_data.min():,.2f} | Max={col_data.max():,.2f}"
                    )

        name_cols = [c for c in combined.columns if "visitador" in c.lower() and "cód" not in c.lower() and "código" not in c.lower()]
        group_col = name_cols[0] if name_cols else person_col
        if group_col and not filter_person:
            lines.append(f"\n**Resumen por {group_col}:**")
            agg: dict = {"Ventas": (group_col, "count")}
            for col in stat_cols[:4]:
                agg[col] = (col, "sum")
            grp = combined.groupby(group_col)
            summary_df = grp.agg(**{k: v for k, v in agg.items()})
            summary_df = summary_df.sort_values("Ventas", ascending=False)
            lines.append(summary_df.to_string())

        lines.append(f"\n**Primeros 10 registros:**")
        lines.append(combined.head(10).to_string(index=False))

        return "\n".join(lines)

    except Exception as e:
        return f"Error leyendo datos de ventas: {e}"


# ---------------------------------------------------------------------------
# Direct report memory
# ---------------------------------------------------------------------------

def _notes_file(person_name: str) -> Path:
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in person_name).strip()
    return MEMORY_DIR / f"{safe.lower().replace(' ', '_')}.json"


def get_report_notes(person_name: str) -> str:
    """Return all saved notes about a direct report."""
    path = _notes_file(person_name)

    if not path.exists():
        return f"No hay notas previas sobre {person_name}. Es la primera vez que mencionas a esta persona."

    data = json.loads(path.read_text(encoding="utf-8"))
    notes = data.get("notes", [])

    if not notes:
        return f"No hay notas guardadas sobre {person_name}."

    labels = {
        "performance": "📊 Rendimiento",
        "personal":    "👤 Contexto personal",
        "agreement":   "🤝 Acuerdos",
        "concern":     "⚠️ Preocupaciones",
        "strength":    "💪 Fortalezas",
        "general":     "📝 General",
    }

    by_cat: dict[str, list] = {}
    for note in notes:
        by_cat.setdefault(note.get("category", "general"), []).append(note)

    lines = [f"**Historial de {person_name}:**\n"]
    for cat, cat_notes in by_cat.items():
        lines.append(f"\n**{labels.get(cat, cat)}:**")
        for n in cat_notes[-5:]:
            lines.append(f"- [{n.get('date', '?')}] {n.get('text', '')}")

    return "\n".join(lines)


def save_report_note(person_name: str, note: str, category: str = "general") -> str:
    """Persist a note about a direct report."""
    path = _notes_file(person_name)

    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = {"person": person_name, "notes": []}

    data["notes"].append({
        "date":     datetime.now().strftime("%Y-%m-%d"),
        "category": category,
        "text":     note,
    })

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"✅ Nota guardada sobre {person_name}."
