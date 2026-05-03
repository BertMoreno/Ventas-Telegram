"""
Asistente de Management — punto de entrada principal.
Soporta Anthropic, OpenAI o Gemini según .env.

Uso:
    python agent.py

Requisitos previos:
    1. pip install -r requirements.txt
    2. Configura .env (elige proveedor):
       - LLM_PROVIDER=anthropic|openai|gemini
       - ANTHROPIC_API_KEY=...   (si anthropic)
       - OPENAI_API_KEY=...      (si openai)
       - GEMINI_API_KEY=...      (si gemini)
    3. (Opcional) Copia PDFs a docs/ y ejecuta: python ingest.py
    4. (Opcional) Copia datos de ventas (CSV/Excel) a sales_data/, sales/ o data/
"""

import os
import sys

from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

load_dotenv()

from tools import get_report_notes, get_sales_summary, save_report_note, search_documents

console = Console()
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic").strip().lower()


def _build_client():
    if LLM_PROVIDER == "anthropic":
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            print("\n[ERROR] Falta ANTHROPIC_API_KEY en .env\n")
            sys.exit(1)
        import anthropic

        return anthropic.Anthropic(api_key=api_key)

    if LLM_PROVIDER == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            print("\n[ERROR] Falta OPENAI_API_KEY en .env\n")
            sys.exit(1)
        try:
            from openai import OpenAI
        except ImportError:
            print("\n[ERROR] Falta dependencia openai. Instala con: pip install openai\n")
            sys.exit(1)
        return OpenAI(api_key=api_key)

    if LLM_PROVIDER == "gemini":
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            print("\n[ERROR] Falta GOOGLE_API_KEY en .env\n")
            sys.exit(1)
        try:
            import google.generativeai as genai
        except ImportError:
            print(
                "\n[ERROR] Falta dependencia google-generativeai. "
                "Instala con: pip install google-generativeai\n"
            )
            sys.exit(1)
        genai.configure(api_key=api_key)
        return genai.GenerativeModel(os.getenv("GEMINI_MODEL", "gemini-3-flash-preview"))

    print("\n[ERROR] LLM_PROVIDER no válido. Usa: anthropic | openai | gemini\n")
    sys.exit(1)


client = _build_client()

# ── System prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """---
name: Director Comercial
description: Agente especializado en la dirección comercial, liderazgo de equipos de ventas y gestión personalizada de talento basada en perfiles conductuales.
---

IMPORTANTE: Usa siempre EMOJIS en tus respuestas para que sean dinámicas y fáciles de leer en Telegram (ej: 🚀, 📊, ✅, 👥, 📈, 🤝). Mantén un tono profesional pero cercano.

# Skill: Director Comercial

Este agente personifica a un Director Comercial de alto rendimiento, enfocado en el cumplimiento de metas de ingresos, beneficios y cuota de mercado a través de una gestión estructurada y el desarrollo del talento humano.

## Cuándo usar este agente
- **Planificación Estratégica**: Para establecer KPIs, targets de ventas y asignación de territorios.
- **Gestión de Equipos**: Para estructurar reuniones One-on-One, Sales Meetings y planes de coaching.
- **Análisis de Desempeño**: Para evaluar resultados frente a objetivos, uso de CRM y calidad de las actividades comerciales.
- **Preparación de Ventas**: Para guiar a los representantes en la preparación de visitas SMART y manejo de objeciones complejas.

## Funciones y Responsabilidades Clave

### 1. Gestión por KPIs y Objetivos
- **Establecimiento de Metas**: Definir objetivos claros de ingresos y rentabilidad, desglosados por cliente y familia de productos.
- **Monitoreo de Desempeño**: Seguimiento riguroso de indicadores clave a través de herramientas de BI y CRM.
- **Reporting**: Informar periódicamente a la dirección sobre las tendencias de mercado y el desempeño del equipo.

### 2. Excelencia en el Ciclo de Negocio (Business Cycle)
- **Análisis de Situación**: Evaluar periódicamente el estado del mercado y la competencia.
- **Planificación de Recursos**: Coordinar ventas, marketing y formación para maximizar el impacto comercial.
- **Fase de Ejecución y Catch-up**: Implementar planes de acción y realizar ajustes ("catch-up") si los resultados se desvían del presupuesto anual.

### 3. Metodología de Liderazgo y Coaching
- **One-on-One Semanales**: Reuniones de ~15 minutos con estructura 20/80 (20% revisión de resultados pasados, 80% enfoque en la semana actual y futura).
- **Gestión 3Q**: Evaluar y mejorar la **Cantidad**, **Calidad** y **Calificación** de las actividades del equipo.
- **Desarrollo de Talento**: Identificación de fortalezas, áreas de mejora y ejecución de planes de "coach up or out".

### 4. Protocolo de Visita de Ventas de Alto Impacto
- **Preparación SMART**: Definir objetivos específicos y agenda previa a la visita.
- **Descubrimiento de Necesidades**: Indagar tanto en necesidades factuales como emocionales del cliente.
- **Presentación de Valor**: Enlazar beneficios con necesidades; utilizar la técnica de "Sándwich" para la presentación de precios (Beneficio-Precio-Beneficio).
- **Manejo de Objeciones (Técnica AQST)**:
  - **A**ceptación/Reconocimiento.
  - **Q**uestion (Pregunta aclaratoria).
  - **S**olución basada en datos.
  - **T**ransición al siguiente paso.
- **Cierre y Seguimiento**: Confirmación de acuerdos por escrito (24h) y actualización de CRM (48h).

## Acceso a Datos y Reportes

Este agente tiene la capacidad de consultar datos en tiempo real para fundamentar sus decisiones:

- **Consulta de Ventas**: Puede leer el libro `ventas2026` (Excel o Drive). 
  - **Hoja de Ventas**: `ventas2026`. Úsala para analizar el rendimiento actual del año.
  - **Hoja de Objetivos**: `Objetivos26`. Úsala para comparar el rendimiento real frente a las metas establecidas.
  - **Filtros**: Puede filtrar por nombre de visitador/comercial para dar feedback específico.
- **Herramientas**:
  - `get_sales_summary(period='ventas2026')`: Para obtener el resumen del año actual.
  - `get_sales_summary(period='Objetivos26')`: Para consultar las metas del equipo.
  - `get_report_notes(nombre)`: Para recordar acuerdos previos con un colaborador.
  - `save_report_note(nombre, nota)`: Para registrar feedback después de una visita o reunión.

## Gestión del Equipo Comercial

Este agente tiene conocimiento de los perfiles específicos del equipo para personalizar el liderazgo y el coaching:

### Miembros del Equipo y Perfiles (THT)
1. **Carmen Blázquez**:
   - **Perfil**: Liderazgo por inspiración y alta capacidad comunicativa.
   - **Fortalezas**: Optimismo (82), motivación de equipos y adaptabilidad.
   - **Enfoque de Dirección**: Apoyarse en su entusiasmo para lanzar nuevos proyectos o motivar al grupo. Reforzar la focalización y persistencia en tareas administrativas.

2. **Luis Alberto Rodríguez**:
   - **Perfil**: Comunicador nato y persuasivo con orientación extrema a las personas.
   - **Fortalezas**: Expresividad (96), delegación e inspiración (92).
   - **Enfoque de Dirección**: Ideal para relaciones con clientes clave y mentoría. Asegurar que el enfoque en resultados no se diluya por el exceso de empatía o socialización.

3. **Ramón Ferrando**:
   - **Perfil**: Alto impacto comunicativo y orientación dual (resultados e inspiración).
   - **Fortalezas**: Máxima expresividad (98), liderazgo inspiracional (91) y resiliencia.
   - **Enfoque de Dirección**: Excelente para entornos dinámicos y retos de alto impacto. Vigilar la focalización (18) y ayudarle a estructurar procesos repetitivos.

## Guía de Interacción y Expansión
1. **Tono**: Profesional, motivador, analítico y orientado a resultados.
2. **Prioridad**: Enfocarse siempre en cómo la actividad actual contribuye al objetivo final de venta y satisfacción del cliente.
3. **Uso de Datos**: Fomentar siempre la toma de decisiones basada en KPIs y feedback real del campo.
4. **Expansión**: Este archivo puede ampliarse añadiendo nuevos miembros del equipo, guías específicas de productos o cambios en la estrategia comercial.
"""

# ── Definición de herramientas ────────────────────────────────────────────────
TOOLS = [
    {
        "name": "search_knowledge_base",
        "description": (
            "Busca en los libros y fuentes sobre management, liderazgo, negociación "
            "y desarrollo de equipos. Úsalo cuando el manager pregunta sobre técnicas, "
            "frameworks o mejores prácticas de gestión."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "El tema o pregunta a buscar en la base de conocimiento.",
                },
                "n_results": {
                    "type": "integer",
                    "description": "Número de fragmentos a recuperar (por defecto 3).",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_sales_data",
        "description": (
            "Obtiene datos de ventas del equipo. Úsalo cuando el manager pregunta "
            "sobre resultados, rendimiento del equipo o quiere analizar tendencias."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filter_person": {
                    "type": "string",
                    "description": "Nombre de un colaborador para filtrar sus datos (opcional).",
                },
                "period": {
                    "type": "string",
                    "description": "Período: 'all' (por defecto).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_report_notes",
        "description": (
            "Recupera el historial y notas sobre un colaborador directo. "
            "Úsalo SIEMPRE que el manager mencione a alguien de su equipo."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "person_name": {
                    "type": "string",
                    "description": "Nombre del colaborador.",
                }
            },
            "required": ["person_name"],
        },
    },
    {
        "name": "save_report_note",
        "description": (
            "Guarda una nota importante sobre un colaborador: situaciones, acuerdos, "
            "progreso, preocupaciones o fortalezas. Úsalo siempre que haya información "
            "relevante que debas recordar en futuras conversaciones."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "person_name": {
                    "type": "string",
                    "description": "Nombre del colaborador.",
                },
                "note": {
                    "type": "string",
                    "description": "Texto de la nota.",
                },
                "category": {
                    "type": "string",
                    "description": "Categoría de la nota.",
                    "enum": ["performance", "personal", "agreement", "concern", "strength", "general"],
                },
            },
            "required": ["person_name", "note", "category"],
        },
    },
]


# ── Ejecución de herramientas ─────────────────────────────────────────────────
def run_tool(name: str, inputs: dict) -> str:
    try:
        if name == "search_knowledge_base":
            return search_documents(inputs["query"], int(inputs.get("n_results", 3)))
        if name == "get_sales_data":
            return get_sales_summary(
                filter_person=inputs.get("filter_person"),
                period=inputs.get("period", "all"),
            )
        if name == "get_report_notes":
            return get_report_notes(inputs["person_name"])
        if name == "save_report_note":
            return save_report_note(
                person_name=inputs["person_name"],
                note=inputs["note"],
                category=inputs.get("category", "general"),
            )
        return f"Herramienta desconocida: {name}"
    except Exception as e:
        return f"Error en {name}: {e}"


# ── Loop de chat en terminal ──────────────────────────────────────────────────
def chat() -> None:
    console.print(
        Panel.fit(
            "[bold cyan]Asistente de Management[/bold cyan]\n"
            "[dim]Tu coach ejecutivo personal · Escribe [bold]salir[/bold] para terminar[/dim]",
            border_style="cyan",
        )
    )
    console.print()

    messages: list[dict] = []

    while True:
        try:
            user_input = console.input("[bold green]Tú:[/bold green] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Hasta luego.[/dim]")
            break

        if not user_input:
            continue
        if user_input.lower() in ("salir", "exit", "quit", "q"):
            console.print("[dim]Hasta luego.[/dim]")
            break

        if LLM_PROVIDER == "anthropic":
            messages.append({"role": "user", "content": user_input})

            # Loop agéntico con herramientas
            while True:
                response = client.messages.create(
                    model=os.getenv("ANTHROPIC_MODEL", "claude-opus-4-6"),
                    max_tokens=4096,
                    system=SYSTEM_PROMPT,
                    tools=TOOLS,
                    messages=messages,
                )

                if response.stop_reason == "tool_use":
                    messages.append({"role": "assistant", "content": response.content})

                    tool_results = []
                    for block in response.content:
                        if block.type == "tool_use":
                            console.print(f"  [dim]→ {block.name}...[/dim]")
                            result = run_tool(block.name, block.input)
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": result,
                            })

                    messages.append({"role": "user", "content": tool_results})

                else:
                    messages.append({"role": "assistant", "content": response.content})
                    console.print()
                    console.print("[bold blue]Coach:[/bold blue]")
                    for block in response.content:
                        if block.type == "text":
                            console.print(Markdown(block.text))
                    console.print()
                    break
        elif LLM_PROVIDER == "openai":
            messages.append({"role": "user", "content": user_input})
            response = client.chat.completions.create(
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                messages=[{"role": "system", "content": SYSTEM_PROMPT}] + messages,
            )
            text = response.choices[0].message.content or ""
            messages.append({"role": "assistant", "content": text})
            console.print()
            console.print("[bold blue]Coach:[/bold blue]")
            console.print(Markdown(text))
            console.print()
        else:  # gemini
            messages.append({"role": "user", "content": user_input})
            history = []
            for m in messages[:-1]:
                role = "model" if m["role"] == "assistant" else "user"
                history.append({"role": role, "parts": [m["content"]]})
            chat_session = client.start_chat(history=history)
            resp = chat_session.send_message(f"{SYSTEM_PROMPT}\n\nUsuario: {user_input}")
            text = (resp.text or "").strip()
            messages.append({"role": "assistant", "content": text})
            console.print()
            console.print("[bold blue]Coach:[/bold blue]")
            console.print(Markdown(text))
            console.print()


if __name__ == "__main__":
    chat()
