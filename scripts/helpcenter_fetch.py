"""Descarga el Centro de Ayuda de VMC y lo convierte en chunks listos para Pinecone.

    python -m scripts.helpcenter_fetch                 # todo el centro de ayuda
    python -m scripts.helpcenter_fetch --limit 3       # prueba rapida
    python -m scripts.helpcenter_fetch --url https://otro-sitio

Escribe dos cosas en `data/helpcenter/`:

    *.md          un archivo por articulo, para que una persona pueda revisar QUE se indexo
    chunks.json   lo que se sube a Pinecone (`python -m scripts.helpcenter_upload`)

Por que un chunk por pregunta y no por tamaño: el Centro de Ayuda ya esta escrito como pares
pregunta/respuesta, asi que la unidad semantica existe en la fuente. Trocear por numero de
tokens partiria respuestas a la mitad y mezclaria dos temas en un chunk — el problema que el
chunking semantico trata de evitar. El titulo del articulo se antepone a cada chunk para que
el embedding tenga contexto ("Comision" solo, sin el articulo, es ambiguo).

No usa credenciales ni servicios de pago: es HTTP contra el sitio publico.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import unicodedata
import urllib.request
from dataclasses import dataclass, field
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT / "data" / "helpcenter"
CHUNKS_PATH = DOCS_DIR / "chunks.json"

DEFAULT_BASE_URL = "https://centro-de-ayuda-vmc.vercel.app"

# La home trae el indice de articulos en un <script id="search-data"> (JSON server-rendered):
# se lee de ahi en vez de rastrear enlaces, que es mas fragil y descarga paginas de mas.
_SEARCH_DATA = re.compile(r'<script[^>]*id="search-data"[^>]*>(.*?)</script>', re.DOTALL | re.I)
_MAIN = re.compile(r"<main[^>]*>(.*?)</main>", re.DOTALL | re.I)
_DROP = re.compile(r"<(script|style|svg|nav|footer)[^>]*>.*?</\1>", re.DOTALL | re.I)
_ANCHOR = re.compile(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', re.DOTALL | re.I)
_HAS_DIGIT = re.compile(r"\d")

# Bloques de navegacion y llamadas a la accion que se repiten en cada pagina. Indexarlos
# ensuciaria los resultados: "Habla con nosotros" aparece en los 21 articulos y competiria
# con el contenido real en cualquier busqueda.
_NOISE = (
    "¿Tienes otras consultas?",
    "Habla con nosotros",
    "Artículos de esta categoría",
    "Volver al inicio",
    "Centro de Ayuda",
    # Widget de valoracion al pie de cada articulo: su "respuesta" son tres caritas, que como
    # chunk no aporta nada y ademas se repite identico en todos los articulos.
    "¿Ha quedado contestada tu pregunta",
)

# Anclas sin significado propio: "haz clic aquí" no dice a donde lleva, asi que solo en esos
# casos conservamos la URL. Con un ancla descriptiva la URL es ruido para el embedding.
_VAGUE_ANCHOR = re.compile(
    r"^(¡?\s*(ingresa|click|clic|haz clic|entra|dale)?\s*(aqui|aquí|acá|aca|here)\s*!?"
    r"|ver m[áa]s|m[áa]s informaci[óo]n|link|enlace)$",
    re.I,
)

_NBSP = " "
_ZWSP = "​"


@dataclass
class Article:
    title: str
    url: str
    category: str = ""
    intro: str = ""
    qas: list[tuple[str, str]] = field(default_factory=list)


# ─────────────────────────────── Limpieza de texto ───────────────────────────────


def slugify(value: str, *, max_chars: int = 60) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", normalized).strip("-").lower()
    return (normalized or "sin-titulo")[:max_chars]


def tidy(text: str) -> str:
    """Normaliza el espaciado que deja el HTML al quitarle las etiquetas.

    El sitio abre y cierra <strong> a mitad de frase, asi que al plancharlo quedan espacios
    sueltos antes de la puntuacion ("Subascoin ." o "5.90 %"). Eso no cambia el significado
    para una persona, pero si el embedding y las citas textuales.
    """
    text = text.replace(_NBSP, " ").replace(_ZWSP, "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"(\d)\s+%", r"\1%", text)
    text = re.sub(r"\s+([,.;:!?%\)\]])", r"\1", text)
    text = re.sub(r"([\(\[¿¡“«])\s+", r"\1", text)
    text = re.sub(r"\s+([”»])", r"\1", text)
    text = re.sub(r"(US\$)(\d)", r"\1 \2", text)
    text = re.sub(r"\s+:\s*(https?://)", r": \1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _inline_links(fragment: str, base_url: str) -> str:
    def replace(match: re.Match[str]) -> str:
        href = (match.group(1) or "").strip()
        label = re.sub(r"<[^>]+>", " ", match.group(2))
        label = re.sub(r"\s+", " ", unescape(label)).strip()
        if not href or href.startswith(("#", "javascript:")):
            return f" {label} "
        if href.startswith("/"):
            href = f"{base_url}{href}"
        if label and _VAGUE_ANCHOR.match(label):
            return f" {label}: {href} "
        return f" {label} "

    return _ANCHOR.sub(replace, fragment)


def html_to_text(fragment: str, base_url: str = DEFAULT_BASE_URL) -> str:
    """HTML a texto plano conservando los saltos que separan ideas.

    Primero se aplasta TODO el espacio en blanco del HTML fuente: en HTML no significa nada
    (el navegador lo colapsa), pero si se conserva, el sangrado del sitio parte frases a la
    mitad dentro de un mismo parrafo y ese salto termina dentro del chunk. Los unicos saltos
    que sobreviven son los que introducimos abajo desde <br> y las etiquetas de bloque, que
    si separan ideas (pasos, listas).
    """
    text = _DROP.sub(" ", fragment)
    text = re.sub(r"\s+", " ", text)
    text = _inline_links(text, base_url)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</(p|div|li|h[1-6])>", "\n", text, flags=re.I)
    text = re.sub(r"<li[^>]*>", "\n- ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return tidy(unescape(text))


def _strip_noise(text: str) -> str:
    for noise in _NOISE:
        position = text.find(noise)
        if position > 0:
            text = text[:position]
        else:
            text = text.replace(noise, " ")
    return tidy(text)


# ─────────────────────────────── Parseo de un articulo ───────────────────────────────


def parse_article(html: str, url: str, *, base_url: str = DEFAULT_BASE_URL) -> Article | None:
    """Extrae titulo, respuesta rapida y pares pregunta/respuesta. None si no hay contenido."""
    clean = _DROP.sub(" ", html)
    heading = re.search(r"<h1[^>]*>(.*?)</h1>", clean, re.DOTALL | re.I)
    title = html_to_text(heading.group(1), base_url) if heading else ""
    if not title:
        return None

    main = _MAIN.search(html)
    body = _DROP.sub(" ", main.group(1) if main else html)

    # Cada <h2> abre una pregunta; lo anterior al primero es la "Respuesta rapida" del articulo.
    blocks = re.split(r"<h2[^>]*>", body, flags=re.I)

    intro = html_to_text(blocks[0], base_url).replace(title, " ", 1)
    intro = re.sub(r"^\s*Respuesta r[áa]pida\s*", "", intro).strip()
    # El sitio cierra con una tarjeta del asistente ("Subastín ...") que no es contenido.
    intro = re.sub(r"S?\s*Subast[íi]n.*$", "", intro, flags=re.DOTALL).strip()
    intro = _strip_noise(intro)

    article = Article(title=title, url=url, intro=intro)
    for block in blocks[1:]:
        head, _, rest = block.partition("</h2>")
        question = html_to_text(head, base_url)
        if not question or any(noise in question for noise in _NOISE):
            continue
        answer = _strip_noise(html_to_text(rest, base_url))
        if answer:
            article.qas.append((question, answer))
    return article


def article_markdown(article: Article) -> str:
    """El articulo como markdown legible. Es la copia que revisa una persona, no la que se sube."""
    lines = [f"# {article.title}", ""]
    if article.category:
        lines.append(f"- **Categoria:** {article.category}")
    lines += [f"- **Fuente:** {article.url}", f"- **Preguntas:** {len(article.qas)}", ""]
    if article.intro:
        lines += ["## Respuesta rapida", "", article.intro, ""]
    for question, answer in article.qas:
        lines += [f"## {question}", "", answer, ""]
    return "\n".join(lines)


def _question_suffix(question: str) -> str:
    """Parte del id que identifica a la pregunta: slug legible + huella del texto completo.

    El slug solo no basta. Truncado a unas decenas de caracteres, dos preguntas largas que
    empiezan igual ("¿Cómo solicito la devolución de mi saldo en US$ dólares...?" y "¿Cómo
    solicito la devolución de mi saldo en soles?") producen el MISMO id, y la deduplicacion
    descartaria la segunda en silencio: contenido que desaparece del indice sin ningun error.
    La huella del texto completo lo hace imposible, y sigue siendo estable entre corridas
    porque depende solo del texto.
    """
    huella = hashlib.sha1(question.encode("utf-8")).hexdigest()[:6]  # noqa: S324 — no es cripto
    return f"{slugify(question, max_chars=40)}-{huella}"


def build_chunks(articles: list[Article]) -> list[dict]:
    """Un chunk por pregunta (mas uno por respuesta rapida), con id ESTABLE.

    El id se deriva del slug del articulo y de la pregunta, no de la posicion. Con ids
    posicionales (`hc1`, `hc2`...) basta con que el sitio agregue una pregunta al principio
    para que todos los siguientes se corran: el upsert sobrescribiria cada vector con el texto
    de otro y el indice quedaria mezclado sin que nada falle.
    """
    chunks: list[dict] = []
    seen: set[str] = set()

    for article in articles:
        article_slug = slugify(article.title)
        pieces: list[tuple[str, str, str]] = []
        if article.intro:
            pieces.append(("resumen", article.title, article.intro))
        for question, answer in article.qas:
            pieces.append((_question_suffix(question), question, answer))

        for suffix, heading, body in pieces:
            chunk_id = f"hc-{article_slug}-{suffix}"
            if chunk_id in seen:
                continue
            seen.add(chunk_id)
            chunks.append(
                {
                    "id": chunk_id,
                    "text": f"{article.title}\n{heading}\n{body}"
                    if heading != article.title
                    else f"{article.title}\n{body}",
                    "topic": article.title,
                    "source_url": article.url,
                    "has_numeric_data": bool(_HAS_DIGIT.search(body)),
                }
            )
    return chunks


# ─────────────────────────────── Descarga ───────────────────────────────


def clear_previous_articles(directory: Path) -> None:
    """Borra los articulos de la corrida anterior, para que uno retirado del sitio no quede.

    Respeta `README.md`: es documentacion del repo que vive en la misma carpeta, no contenido
    descargado. Borrar todos los `*.md` a ciegas se lo llevaba por delante.
    """
    for stale in directory.glob("*.md"):
        if stale.name.lower() != "readme.md":
            stale.unlink()


def fetch_html(url: str, *, timeout: int = 60) -> str:
    request = urllib.request.Request(  # noqa: S310 — URL fija del Centro de Ayuda, no de usuario
        url, headers={"User-Agent": "Subastin ingest (contacto: soporte VMC)"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return response.read().decode("utf-8", errors="replace")


def article_paths(home_html: str) -> dict[str, str]:
    """Rutas de articulo -> categoria, leidas del indice de busqueda de la home."""
    match = _SEARCH_DATA.search(home_html)
    if not match:
        raise SystemExit('No se encontro <script id="search-data"> en la home del Centro de Ayuda.')
    paths: dict[str, str] = {}
    for entry in json.loads(match.group(1).strip()):
        path = (entry.get("u") or "").strip()
        # /categorias/<categoria>/<articulo> tiene 3 barras; las de categoria, 2.
        if path.count("/") >= 3 and path not in paths:
            paths[path] = (entry.get("c") or "").strip()
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Descarga el Centro de Ayuda y genera chunks")
    parser.add_argument("--url", default=DEFAULT_BASE_URL, help="Base del Centro de Ayuda")
    parser.add_argument("--limit", type=int, default=0, help="Solo los primeros N articulos")
    parser.add_argument("--pausa", type=float, default=0.3, help="Segundos entre descargas")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    print(f"Indice de articulos: {base_url}")
    paths = article_paths(fetch_html(base_url))
    if args.limit:
        paths = dict(sorted(paths.items())[: args.limit])
    print(f"Articulos a descargar: {len(paths)}\n")

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    clear_previous_articles(DOCS_DIR)

    articles: list[Article] = []
    for position, (path, category) in enumerate(sorted(paths.items()), 1):
        url = f"{base_url}{path}"
        try:
            html = fetch_html(url)
        except Exception as error:  # noqa: BLE001 — un articulo caido no aborta la ingesta
            print(f"[{position:2d}/{len(paths)}] ERROR {path}: {error}")
            continue
        article = parse_article(html, url, base_url=base_url)
        if article is None:
            print(f"[{position:2d}/{len(paths)}] SIN CONTENIDO {path}")
            continue
        article.category = category
        (DOCS_DIR / f"{slugify(article.title)}.md").write_text(
            article_markdown(article), encoding="utf-8"
        )
        articles.append(article)
        print(f"[{position:2d}/{len(paths)}] {len(article.qas):2d} preguntas · {article.title}")
        time.sleep(args.pausa)  # cortesia con el servidor de VMC

    if not articles:
        sys.exit("No se pudo descargar ningun articulo.")

    chunks = build_chunks(articles)
    CHUNKS_PATH.write_text(
        json.dumps({"source": base_url, "chunks": chunks}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nArticulos: {len(articles)} | Chunks: {len(chunks)}")
    print(f"Markdown para revisar: {DOCS_DIR}")
    print(f"Chunks:                {CHUNKS_PATH}")
    print("\nSiguiente paso: python -m scripts.helpcenter_upload")


if __name__ == "__main__":
    main()
