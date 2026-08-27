"""Ingesta del Centro de Ayuda: HTML -> articulo -> chunks (scripts/helpcenter_fetch.py).

Criterios:
  AC-I1  del HTML sale el titulo, la respuesta rapida y un par pregunta/respuesta por <h2>
  AC-I2  la navegacion y las llamadas a la accion no se indexan
  AC-I3  un chunk por pregunta, con el titulo del articulo como contexto y su fuente
  AC-I4  los ids son ESTABLES: agregar una pregunta no renombra las demas

Todo corre sobre HTML de prueba: la ingesta no debe necesitar red para poder testearse.
"""

from scripts.helpcenter_fetch import (
    article_markdown,
    build_chunks,
    clear_previous_articles,
    html_to_text,
    parse_article,
    slugify,
)

URL = "https://ayuda.vmc.test/categorias/billetera/la-comision"

HTML = """
<html><head><script>ignorame()</script></head><body>
  <header><h1>La Comisión, ¿Por qué, cuánto y cómo se paga?</h1></header>
  <nav>Centro de Ayuda</nav>
  <main>
    <p>Respuesta rápida</p>
    <p>La comisión se calcula sobre el <strong>bid</strong> del ganador, con un mínimo de
       50 SubasCoins.</p>
    <h2>¿Dónde veo el porcentaje?</h2>
    <p>En el detalle de cada publicación. Más info <a href="/terminos">aquí</a>.</p>
    <h2>¿Mi bid incluye la comisión?</h2>
    <p>No. Se suma aparte de tu bid.</p>
    <h2>¿Tienes otras consultas?</h2>
    <p>Habla con nosotros</p>
  </main>
  <footer>Volver al inicio</footer>
</body></html>
"""


# ───────────────────────── AC-I1: estructura del articulo ─────────────────────────


def test_del_html_sale_titulo_intro_y_preguntas():
    article = parse_article(HTML, URL)

    assert article.title == "La Comisión, ¿Por qué, cuánto y cómo se paga?"
    assert article.url == URL
    assert "mínimo de 50 SubasCoins" in article.intro
    assert article.intro.startswith("La comisión"), "la etiqueta 'Respuesta rápida' no es contenido"
    assert [q for q, _ in article.qas] == [
        "¿Dónde veo el porcentaje?",
        "¿Mi bid incluye la comisión?",
    ]
    assert article.qas[1][1] == "No. Se suma aparte de tu bid."


def test_sin_titulo_no_hay_articulo():
    assert parse_article("<html><body><p>suelto</p></body></html>", URL) is None


# ───────────────────────── AC-I2: lo que no se indexa ─────────────────────────


def test_la_navegacion_y_el_cta_no_entran():
    article = parse_article(HTML, URL)

    todo = article.intro + " ".join(q + a for q, a in article.qas)
    for ruido in ("¿Tienes otras consultas?", "Habla con nosotros", "Volver al inicio"):
        assert ruido not in todo, "el CTA se repite en cada articulo y competiria con el contenido"
    assert "ignorame" not in todo, "el <script> no es contenido"


def test_el_enlace_vago_conserva_su_destino():
    # "aquí" sin la URL no dice nada; con un ancla descriptiva la URL solo mete ruido.
    assert "https://x.test/terminos" in html_to_text(
        '<p>Míralo <a href="https://x.test/terminos">aquí</a>.</p>'
    )
    assert "https://x.test/terminos" not in html_to_text(
        '<p>Revisa los <a href="https://x.test/terminos">términos y condiciones</a>.</p>'
    )


def test_se_normaliza_el_espaciado_que_deja_el_html():
    # <strong> a mitad de frase deja espacios sueltos antes de la puntuacion.
    assert html_to_text("<p>El fee es de 3.9 % <strong>por</strong> uso .</p>") == (
        "El fee es de 3.9% por uso."
    )


# ───────────────────────── AC-I3 / AC-I4: chunks e ids ─────────────────────────


def test_un_chunk_por_pregunta_con_titulo_y_fuente():
    chunks = build_chunks([parse_article(HTML, URL)])

    assert len(chunks) == 3, "la respuesta rapida tambien es un chunk"
    pregunta = chunks[1]
    assert pregunta["text"].startswith("La Comisión"), (
        "el titulo da contexto al embedding: 'porcentaje' solo es ambiguo"
    )
    assert "¿Dónde veo el porcentaje?" in pregunta["text"]
    assert pregunta["source_url"] == URL
    assert pregunta["topic"] == "La Comisión, ¿Por qué, cuánto y cómo se paga?"


def test_marca_los_chunks_con_datos_numericos():
    chunks = build_chunks([parse_article(HTML, URL)])

    assert chunks[0]["has_numeric_data"] is True  # "50 SubasCoins"
    assert chunks[2]["has_numeric_data"] is False  # "No. Se suma aparte de tu bid."


def test_los_ids_no_dependen_de_la_posicion():
    """Con ids posicionales, agregar una pregunta al principio corre todos los demas y el
    upsert sobrescribe cada vector con el texto de otro, sin que nada falle."""
    original = build_chunks([parse_article(HTML, URL)])
    con_pregunta_nueva = HTML.replace(
        "<h2>¿Dónde veo el porcentaje?</h2>",
        "<h2>¿Cuándo se cobra?</h2><p>Al ser habilitado.</p><h2>¿Dónde veo el porcentaje?</h2>",
    )
    despues = build_chunks([parse_article(con_pregunta_nueva, URL)])

    ids_originales = {c["id"]: c["text"] for c in original}
    ids_despues = {c["id"]: c["text"] for c in despues}
    assert set(ids_originales) < set(ids_despues), "los ids viejos siguen existiendo"
    for chunk_id, texto in ids_originales.items():
        assert ids_despues[chunk_id] == texto, f"{chunk_id} cambio de contenido"


def test_no_se_repiten_ids_dentro_de_un_articulo():
    duplicado = HTML.replace(
        "<h2>¿Mi bid incluye la comisión?</h2>", "<h2>¿Dónde veo el porcentaje?</h2>"
    )
    chunks = build_chunks([parse_article(duplicado, URL)])

    assert len({c["id"] for c in chunks}) == len(chunks)


def test_dos_preguntas_largas_con_el_mismo_principio_no_colisionan():
    """El id lleva slug truncado: sin la huella del texto completo, estas dos preguntas darian
    el mismo id y la segunda se perderia del indice sin que nada fallara."""
    largas = HTML.replace(
        "<h2>¿Dónde veo el porcentaje?</h2>",
        "<h2>¿Cómo solicito la devolución de mi saldo en dólares americanos?</h2>"
        "<p>Desde tu Zona de Usuario.</p>"
        "<h2>¿Cómo solicito la devolución de mi saldo en soles peruanos?</h2>",
    )
    chunks = build_chunks([parse_article(largas, URL)])

    ids = [c["id"] for c in chunks]
    assert len(set(ids)) == len(ids)
    # Las dos preguntas comparten los primeros 40 caracteres del slug: sin la huella, la
    # segunda no llegaria al indice.
    textos = " ".join(c["text"] for c in chunks)
    assert "dólares americanos?" in textos
    assert "soles peruanos?" in textos


def test_el_markdown_es_revisable_por_una_persona():
    article = parse_article(HTML, URL)
    article.category = "La billetera"

    markdown = article_markdown(article)

    assert markdown.startswith("# La Comisión")
    assert "- **Fuente:** " + URL in markdown
    assert "## ¿Mi bid incluye la comisión?" in markdown


def test_el_slug_sirve_como_nombre_de_archivo():
    assert slugify("La Comisión, ¿Por qué, cuánto y cómo se paga?") == (
        "la-comision-por-que-cuanto-y-como-se-paga"
    )


def test_la_descarga_no_borra_el_readme_de_la_carpeta(tmp_path):
    """El fetch limpia los articulos de la corrida anterior; el README de `data/helpcenter/`
    vive en la misma carpeta y es documentacion versionada, no contenido descargado."""
    (tmp_path / "README.md").write_text("documentacion", encoding="utf-8")
    (tmp_path / "un-articulo-viejo.md").write_text("contenido", encoding="utf-8")

    clear_previous_articles(tmp_path)

    assert (tmp_path / "README.md").read_text(encoding="utf-8") == "documentacion"
    assert not (tmp_path / "un-articulo-viejo.md").exists()
