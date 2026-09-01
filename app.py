"""Sistema de locação de materiais para eventos, sem dependências externas.

Arquitetura: aplicação WSGI pura (biblioteca padrão do Python). Todo o HTML é
gerado no servidor pelas funções abaixo — não há motor de templates nem
arquivos .html separados sendo lidos em tempo de execução.
"""
from __future__ import annotations

import html
import os
import re
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "sistema_eventos.db"
STATIC_DIR = BASE_DIR / "static"

# Número de arquivos de QR a manter por pedido (pode ser configurado via variável de ambiente)
try:
    QR_KEEP_COUNT = max(1, int(os.environ.get("QR_KEEP_COUNT", "3")))
except Exception:
    QR_KEEP_COUNT = 3

STATUS_OPCOES = ("Agendado", "Confirmado", "Em andamento", "Concluído", "Cancelado")

# Catálogo inicial (usado apenas na primeira execução, quando a tabela
# "materiais" ainda está vazia). Pode ser totalmente gerenciado depois
# pelo painel /admin/materiais.
CATALOGO_SEED = [
    # (categoria, nome, descricao, preco_unitario, unidade)
    ("Peças decorativas", "Arranjo floral de mesa", "Arranjo com flores naturais ou artificiais para centro de mesa", 45.00, "un"),
    ("Peças decorativas", "Candelabro decorativo", "Candelabro em metal para composição de mesa", 35.00, "un"),
    ("Peças decorativas", "Painel de fundo floral", "Painel decorativo para ambientação e fotos", 380.00, "un"),
    ("Peças decorativas", "Letras/números decorativos iluminados", "Letras ou números em MDF com luz de LED", 60.00, "un"),
    ("Provençal", "Conjunto provençal (mesa + 2 cadeiras)", "Conjunto estilo provençal em branco envelhecido", 220.00, "conjunto"),
    ("Provençal", "Baú provençal decorativo", "Baú em madeira para composição de décor", 90.00, "un"),
    ("Provençal", "Cadeira provençal branca", "Cadeira avulsa estilo provençal", 35.00, "un"),
    ("Pranchão redondo", "Pranchão redondo 1,50m (até 8 lugares)", "Mesa pranchão redonda em madeira maciça", 180.00, "un"),
    ("Pranchão redondo", "Pranchão redondo 1,80m (até 10 lugares)", "Mesa pranchão redonda em madeira maciça", 220.00, "un"),
    ("Pranchão redondo", "Pé de ferro para pranchão", "Base/pé em ferro para montagem do pranchão", 40.00, "un"),
    ("Toalhas de mesa", "Toalha redonda lisa (branca)", "Toalha em oxford branco para mesa redonda", 25.00, "un"),
    ("Toalhas de mesa", "Toalha redonda amassada (crush)", "Toalha em tecido crush para efeito amassado", 30.00, "un"),
    ("Toalhas de mesa", "Toalha retangular para buffet", "Toalha retangular para mesas de buffet", 32.00, "un"),
    ("Tecido jacar", "Tecido jacar para mesa redonda", "Cobre-mancha em tecido jacar metalizado", 38.00, "un"),
    ("Tecido jacar", "Painel de tecido jacar (fundo de palco)", "Painel decorativo em tecido jacar para fundo", 260.00, "un"),
    ("Tensionamento de malhas", "Capa tensionada lisa para cadeira", "Capa em malha tensionada, cor lisa", 18.00, "un"),
    ("Tensionamento de malhas", "Capa tensionada com aplicação", "Capa tensionada com renda ou aplicação decorativa", 24.00, "un"),
    ("Tensionamento de malhas", "Cinta/laço decorativo para cadeira", "Cinta ou laço para arremate da cadeira", 8.00, "un"),
    ("Receptivos", "Mesa de recepção decorada", "Mesa de entrada com decoração temática", 150.00, "un"),
    ("Receptivos", "Livro/quadro de assinaturas", "Peça para os convidados assinarem no evento", 60.00, "un"),
    ("Receptivos", "Painel de boas-vindas personalizado", "Painel com identidade visual do evento", 200.00, "un"),
    ("Coffee break", "Coffee break simples (por pessoa)", "Café, sucos, mini salgados e doces", 28.00, "pessoa"),
    ("Coffee break", "Coffee break completo (por pessoa)", "Opções quentes e frias, salgados, doces e frutas", 45.00, "pessoa"),
    ("Coffee break", "Estação de café e chá", "Estação com cafés especiais e chás variados", 320.00, "un"),
    ("Buffet", "Buffet finger food (por pessoa)", "Porções individuais para eventos em pé", 55.00, "pessoa"),
    ("Buffet", "Buffet jantar completo (por pessoa)", "Entrada, prato principal e sobremesa", 95.00, "pessoa"),
    ("Buffet", "Estação de sobremesas", "Mesa temática com doces variados", 380.00, "un"),
    ("Mesas", "Mesa redonda padrão (8 lugares)", "Mesa redonda para eventos sociais", 25.00, "un"),
    ("Mesas", "Mesa retangular (6 lugares)", "Mesa retangular para jantares e reuniões", 22.00, "un"),
    ("Mesas", "Mesa bistrô alta", "Mesa alta para coquetéis e recepções em pé", 30.00, "un"),
]


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with closing(get_db()) as db, db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS clientes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                email TEXT NOT NULL,
                telefone TEXT NOT NULL,
                endereco TEXT NOT NULL,
                criado_em TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS materiais (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                categoria TEXT NOT NULL,
                nome TEXT NOT NULL,
                descricao TEXT,
                preco_unitario REAL NOT NULL DEFAULT 0,
                unidade TEXT NOT NULL DEFAULT 'un',
                ativo INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS pedidos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cliente_id INTEGER NOT NULL,
                tipo_evento TEXT NOT NULL,
                data_evento TEXT NOT NULL,
                horario TEXT NOT NULL,
                quantidade_convidados INTEGER NOT NULL,
                materiais_extra TEXT,
                observacoes TEXT,
                valor_total REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'Agendado',
                pix_chave TEXT,
                pix_qr TEXT,
                status_pagamento TEXT NOT NULL DEFAULT 'pendente',
                pago_em TEXT,
                criado_em TEXT NOT NULL,
                FOREIGN KEY (cliente_id) REFERENCES clientes(id)
            );
            CREATE TABLE IF NOT EXISTS pedido_itens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pedido_id INTEGER NOT NULL,
                material_id INTEGER,
                nome_material TEXT NOT NULL,
                categoria TEXT NOT NULL,
                quantidade INTEGER NOT NULL,
                preco_unitario REAL NOT NULL,
                FOREIGN KEY (pedido_id) REFERENCES pedidos(id),
                FOREIGN KEY (material_id) REFERENCES materiais(id)
            );
        """)
        total = db.execute("SELECT COUNT(*) AS n FROM materiais").fetchone()["n"]
        if total == 0:
            db.executemany(
                "INSERT INTO materiais (categoria,nome,descricao,preco_unitario,unidade,ativo) VALUES (?,?,?,?,?,1)",
                CATALOGO_SEED,
            )

        colunas_pedidos = {row["name"] for row in db.execute("PRAGMA table_info(pedidos)").fetchall()}
        for coluna, tipo in {
            "pix_chave": "TEXT",
            "pix_qr": "TEXT",
            "status_pagamento": "TEXT NOT NULL DEFAULT 'pendente'",
            "pago_em": "TEXT",
        }.items():
            if coluna not in colunas_pedidos:
                db.execute(f"ALTER TABLE pedidos ADD COLUMN {coluna} {tipo}")


def esc(value: object) -> str:
    return html.escape(str(value or ""))


def fmt_money(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "§").replace(".", ",").replace("§", ".")


PIX_CHAVE_PADRAO = "46.140.249/0001-01"


def gerar_chave_pix() -> str:
    return PIX_CHAVE_PADRAO



def crc16_ccitt(data: bytes) -> str:
    # CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF)
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if (crc & 0x8000) else (crc << 1) & 0xFFFF
    return f"{crc:04X}"


def _tlv(tag: str, value: str) -> str:
    l = f"{len(value):02d}"
    return f"{tag}{l}{value}"


def gerar_payload_pix(chave: str, nome: str = "", cidade: str = "", valor: float | None = None, txid: str | None = None) -> str:
    # Monta o payload no formato EMV (BR Code / PIX) mínimo necessário
    # Referência simplificada do payload Pix (campos comuns para funcionar em apps bancários)
    # 00 - Payload Format Indicator
    payload = _tlv("00", "01")
    # 01 - Point of Initiation Method: '12' = dinâmico / '11' = estático
    payload += _tlv("01", "11")

    # 26 - Merchant Account Information (pix)
    # Subtags: 00=GUI, 01=chave PIX
    mai = _tlv("00", "br.gov.bcb.pix") + _tlv("01", chave)
    payload += _tlv("26", mai)

    # 52 - Merchant Category Code (0000 = unspecified)
    payload += _tlv("52", "0000")
    # 53 - Currency (986 = BRL)
    payload += _tlv("53", "986")

    # 54 - Amount (opcional)
    if valor is not None:
        # ensure dot as decimal separator, no thousands
        payload += _tlv("54", f"{valor:.2f}")

    # 58 - Country
    payload += _tlv("58", "BR")
    # 59 - Merchant Name (max 25)
    if nome:
        payload += _tlv("59", nome[:25])
    # 60 - Merchant City (max 15)
    if cidade:
        payload += _tlv("60", cidade[:15])

    # 62 - Additional Data Field Template (txid)
    if txid:
        adf = _tlv("05", txid)
        payload += _tlv("62", adf)

    # 63 - CRC (placeholder + real CRC appended)
    payload_for_crc = payload + "6304"
    crc = crc16_ccitt(payload_for_crc.encode("utf-8"))
    payload += _tlv("63", crc)
    return payload


def gerar_qr_visual(chave_pix: str) -> str:
    # Fallback visual quando a geração de imagem não estiver disponível
    seed = sum(ord(char) for char in chave_pix)
    linhas = []
    for row in range(11):
        celulas = []
        for col in range(11):
            ativado = ((seed + row * 17 + col * 13 + row * col) % 2 == 0)
            state = 'on' if ativado else 'off'
            celulas.append(f"<span class='qr-cell {state}'></span>")
        linhas.append(f"<div class='qr-row'>{''.join(celulas)}</div>")
    return ''.join(linhas)


def gerar_qr_image_from_payload(pedido_id: int, payload: str) -> str:
    try:
        import qrcode
        img = qrcode.make(payload)
        # unique filename with timestamp to avoid caching and collisions
        timestamp = int(datetime.now().timestamp())
        filename = f"pix_qr_{pedido_id}_{timestamp}.png"
        out_path = STATIC_DIR / filename
        STATIC_DIR.mkdir(parents=True, exist_ok=True)
        # Open file in binary mode and write the image to satisfy type checkers
        with open(out_path, "wb") as f:
            img.save(f)
        # cleanup older images for the same pedido (keep only the most recent QR_KEEP_COUNT)
        try:
            files = sorted(
                STATIC_DIR.glob(f"pix_qr_{pedido_id}_*.png"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for old in files[QR_KEEP_COUNT:]:
                try:
                    old.unlink()
                except Exception:
                    pass
        except Exception:
            pass
        return f"<img src='/static/{filename}' alt='QR Pix'/>"
    except Exception:
        # Se qrcode não estiver disponível, retorna visual fallback
        return gerar_qr_visual(payload)


def buscar_pedido_completo(pedido_id: int):
    with closing(get_db()) as db:
        pedido = db.execute(
            """SELECT p.*, c.nome, c.email, c.telefone, c.endereco
               FROM pedidos p
               JOIN clientes c ON c.id = p.cliente_id
               WHERE p.id = ?""",
            (pedido_id,),
        ).fetchone()
        if pedido is None:
            return None, []
        itens = db.execute(
            "SELECT * FROM pedido_itens WHERE pedido_id = ? ORDER BY categoria, nome_material",
            (pedido_id,),
        ).fetchall()
    return pedido, itens


def debug_recent_qr_page() -> bytes:
    # Lists recent pix QR images in /static for quick visual inspection
    files = []
    try:
        files = sorted(
            [p.name for p in STATIC_DIR.glob('pix_qr_*.png') if p.is_file()],
            key=lambda n: (STATIC_DIR / n).stat().st_mtime,
            reverse=True,
        )
    except Exception:
        files = []
    imgs = "".join(f"<div class='qr-sample'><img src='/static/{esc(n)}' alt='{esc(n)}' style='max-width:320px;border:1px solid var(--line);margin:8px;padding:8px;background:var(--card)'/></div>" for n in files)
    body = f"<section class='section-head'><h2>QR images</h2></section><div style='display:flex;flex-wrap:wrap'>{imgs or '<p>No QR images found.</p>'}</div>"
    return layout(body, title="QR debug")


def pedido_relatorio_page(pedido_id: int) -> bytes:
    pedido, itens = buscar_pedido_completo(pedido_id)
    if pedido is None:
        return not_found()

    lista_itens = "".join(
        f"<tr><td>{it['quantidade']}×</td><td>{esc(it['nome_material'])}</td><td>{esc(it['categoria'])}</td><td>{fmt_money(it['preco_unitario'])}</td><td>{fmt_money(it['quantidade'] * it['preco_unitario'])}</td></tr>"
        for it in itens
    )
    if not lista_itens:
        lista_itens = "<tr><td colspan='5'>Nenhum item registrado no pedido.</td></tr>"

    html_relatorio = f"""
    <section class='report-wrap'>
        <div class='report-header'>
            <div>
            {testimonials_section()}
            <p><strong>Status:</strong> {esc(pedido['status'])}</p>
            <p><strong>Pagamento:</strong> {esc(pedido['status_pagamento'])}</p>
        </div>

        <div class='report-card'>
            <h2>Materiais solicitados</h2>
            <table class='report-table'>
                <thead><tr><th>Qtd</th><th>Material</th><th>Categoria</th><th>Unit.</th><th>Total</th></tr></thead>
                <tbody>{lista_itens}</tbody>
            </table>
        </div>

        <div class='report-card total-box'>
            <p><strong>Valor total estimado:</strong> {fmt_money(pedido['valor_total'])}</p>
            <p><strong>Observações:</strong> {esc(pedido['observacoes'] or 'Nenhuma')}</p>
            <p><strong>Materiais extras:</strong> {esc(pedido['materiais_extra'] or 'Nenhum')}</p>
        </div>
    </section>
    """
    return layout(f"{html_relatorio}", "Relatório do pedido")


def confirmar_pagamento_pix(pedido_id: int) -> None:
    with closing(get_db()) as db, db:
        pedido = db.execute("SELECT * FROM pedidos WHERE id = ?", (pedido_id,)).fetchone()
        if pedido is None:
            raise ValueError("Pedido não encontrado.")
        chave_pix = PIX_CHAVE_PADRAO
        qr_html = pedido["pix_qr"] or gerar_qr_visual(chave_pix)
        db.execute(
            "UPDATE pedidos SET pix_chave = ?, pix_qr = ?, status_pagamento = 'pago', pago_em = ?, status = 'Confirmado' WHERE id = ?",
            (chave_pix, qr_html, datetime.now().isoformat(timespec="seconds"), pedido_id),
        )


def atualizar_chave_pix_do_pedido(pedido_id: int, chave_pix: str | None = None) -> str:
    chave = (chave_pix or PIX_CHAVE_PADRAO)
    # busca dados do pedido/cliente para preencher nome/valor (se disponíveis)
    with closing(get_db()) as db:
        pedido = db.execute(
            "SELECT p.*, c.nome, c.endereco FROM pedidos p JOIN clientes c ON c.id = p.cliente_id WHERE p.id = ?",
            (pedido_id,),
        ).fetchone()

    nome = pedido["nome"] if pedido is not None else ""
    endereco = pedido["endereco"] if pedido is not None else ""
    # tentativa simples de extrair cidade do endereço (opcional)
    cidade = ""
    if endereco:
        parts = endereco.split(",")
        if len(parts) >= 2:
            cidade = parts[-2].strip()

    valor = float(pedido["valor_total"]) if pedido is not None and pedido["valor_total"] else None
    txid = secrets.token_hex(8)

    try:
        payload = gerar_payload_pix(chave, nome=nome, cidade=cidade, valor=valor, txid=txid)
        qr_html = gerar_qr_image_from_payload(pedido_id, payload)
    except Exception:
        qr_html = gerar_qr_visual(chave)

    with closing(get_db()) as db, db:
        db.execute(
            "UPDATE pedidos SET pix_chave = ?, pix_qr = ? WHERE id = ?",
            (chave, qr_html, pedido_id),
        )
    return chave


def pedido_pix_page(pedido_id: int) -> bytes:
    pedido, itens = buscar_pedido_completo(pedido_id)
    if pedido is None:
        return not_found()

    chave_pix = PIX_CHAVE_PADRAO
    if pedido["pix_chave"] != chave_pix or not pedido["pix_qr"]:
        atualizar_chave_pix_do_pedido(pedido_id, chave_pix)
        pedido, itens = buscar_pedido_completo(pedido_id)
        if pedido is None:
            return not_found()

    qr_html = pedido["pix_qr"] or gerar_qr_visual(chave_pix)
    pagamento_status = "Pago" if pedido["status_pagamento"] == "pago" else "Pendente"
    return layout(
        f"""
        <section class='payment-wrap'>
            <p class='eyebrow'>PAGAMENTO VIA PIX</p>
            <h1>Finalize seu pedido</h1>
            <p class='lead'>Use a chave Pix gerada ou leia o QR Code.</p>

            <div class='payment-card'>
                <div class='payment-qr'>
                    <div class='qr-box'>{qr_html}</div>
                </div>
                <div class='payment-info'>
                    <p><strong>Valor:</strong> {fmt_money(pedido['valor_total'])}</p>
                    <p><strong>Chave Pix:</strong> <span class='pix-key'>{esc(chave_pix)}</span></p>
                    <p><strong>Status:</strong> {pagamento_status}</p>
                    <form method='post' action='/pedido/{pedido_id}/pix'>
                        <button class='button' type='submit'>Confirmar pagamento</button>
                    </form>
                    <a class='button secondary' href='/pedido/{pedido_id}/relatorio'>Ver relatório</a>
                </div>
            </div>
        </section>
        """,
        "Pagamento Pix",
    )


def comprovante_pix_page(pedido_id: int) -> bytes:
    pedido, _ = buscar_pedido_completo(pedido_id)
    if pedido is None:
        return not_found()
    if pedido["status_pagamento"] != "pago":
        return pedido_pix_page(pedido_id)

    return layout(
        f"""
        <section class='receipt-wrap'>
            <p class='eyebrow'>COMPROVANTE</p>
            <h1>Pagamento confirmado</h1>
            <div class='report-card'>
                <p><strong>Pedido:</strong> #{pedido['id']:04d}</p>
                <p><strong>Cliente:</strong> {esc(pedido['nome'])}</p>
                <p><strong>Valor pago:</strong> {fmt_money(pedido['valor_total'])}</p>
                <p><strong>Data do pagamento:</strong> {esc(pedido['pago_em'])}</p>
                <p><strong>Chave Pix:</strong> {esc(pedido['pix_chave'])}</p>
            </div>
            <div class='actions-row'>
                <button class='button' onclick='window.print()'>Imprimir comprovante</button>
                <a class='button secondary' href='/pedido/{pedido_id}/relatorio'>Ver relatório do pedido</a>
            </div>
        </section>
        """,
        "Comprovante Pix",
    )


def catalogo_ativo(db: sqlite3.Connection) -> list[sqlite3.Row]:
    return db.execute("SELECT * FROM materiais WHERE ativo = 1 ORDER BY categoria, nome").fetchall()


def agrupar_por_categoria(itens) -> dict[str, list]:
    grupos: dict[str, list] = {}
    for item in itens:
        grupos.setdefault(item["categoria"], []).append(item)
    return grupos


# --------------------------------------------------------------------------
# Layout / páginas públicas
# --------------------------------------------------------------------------

def layout(content: str, title: str = "Dial Eventos", active_menu: str = "") -> bytes:
    def menu_link(label: str, href: str, key: str) -> str:
        active_class = " class='active'" if active_menu == key else ""
        return f"<a{active_class} href='{href}'>{label}</a>"

    return f"""<!doctype html><html lang='pt-BR'><head>
    <meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
    <meta name='theme-color' content='#f2e8df'>
    <title>{esc(title)} | Dial Eventos</title>
    <link rel='preconnect' href='https://fonts.googleapis.com'>
    <link rel='preconnect' href='https://fonts.gstatic.com' crossorigin>
    <link href='https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@500;600;700&family=Inter:wght@400;500;600;700;800&display=swap' rel='stylesheet'>
    <link rel='stylesheet' href='/static/style.css'>
    </head><body><header><a class='brand' href='/' aria-label='Dial Eventos'><span class='brand-mark'>D</span><span class='brand-word'>Dial<span> Eventos</span></span></a>
    <nav class='main-nav'>{menu_link('Início', '/', 'inicio')}{menu_link('Catálogo', '/catalogo', 'catalogo')}{menu_link('Fazer pedido', '/pedido', 'pedido')}{menu_link('Agenda', '/admin', 'agenda')}</nav></header>
    <main>{content}</main><footer>Dial Eventos · Locação que dá vida ao seu evento</footer>
    <script src='/static/scripts.js'></script>
    </body></html>""".encode()


def home() -> bytes:
    with closing(get_db()) as db:
        categorias = db.execute(
            "SELECT categoria, COUNT(*) AS n FROM materiais WHERE ativo = 1 GROUP BY categoria ORDER BY categoria"
        ).fetchall()
    cards = "".join(
        f"<article class='showcase pink'><div class='icon'>✦</div><h3>{esc(c['categoria'])}</h3>"
        f"<p>{c['n']} item(ns) disponível(is) para locação.</p>"
        f"<span><a href='/catalogo?categoria={esc(c['categoria'])}'>Ver itens →</a></span></article>"
        for c in categorias
    )
    return layout(f"""
    <section class='hero hero-mini'>
        <div class='hero-inner'>
            <div class='hero-copy'>
                <p class='eyebrow'>EVENTOS MEMORÁVEIS</p>
                <h1>Materiais que transformam cada celebração.</h1>
                <p class='lead'>A Dial Eventos combina estética, praticidade e atendimento personalizado para criar experiências elegantes e bem organizadas.</p>
                <div class='hero-actions'>
                    <a class='button' href='/pedido'>Começar meu pedido →</a>
                    <a class='button secondary' href='/catalogo'>Ver catálogo</a>
                </div>
            </div>
            <div class='hero-quick-links' aria-hidden='false'>
                <a class='quick-link' href='/catalogo?categoria=Casamento'>Casamentos</a>
                <a class='quick-link' href='/catalogo?categoria=Aniversários'>Aniversários</a>
                <a class='quick-link' href='/catalogo?categoria=Corporativo'>Corporativo</a>
            </div>
        </div>
    </section>

    <section class='trust-bar'>
        <div><strong>+1.200</strong><span>clientes atendidos</span></div>
        <div><strong>4,9/5</strong><span>avaliação média</span></div>
        <div><strong>100%</strong><span>atendimento personalizado</span></div>
    </section>

    <section>
        <div class='section-head'>
            <div><p class='eyebrow'>MOSTRUÁRIO</p><h2>O que temos para o seu evento</h2></div>
            <a href='/catalogo'>Ver catálogo completo →</a>
        </div>
        <div class='grid'>{cards}</div>
    </section>

    <section class='feature-band'>
        <div class='section-head'>
            <div><p class='eyebrow'>POR QUE ESCOLHER</p><h2>Uma experiência pensada para cada detalhe</h2></div>
        </div>
        <div class='feature-grid'>
            <article class='feature-card'>
                <div class='feature-icon'>✦</div>
                <h3>Atendimento sob medida</h3>
                <p>Orientação prática para escolher os materiais certos e montar a proposta ideal para seu evento.</p>
            </article>
            <article class='feature-card'>
                <div class='feature-icon'>✦</div>
                <h3>Itens com bom acabamento</h3>
                <p>Materiais selecionados para garantir uma apresentação elegante, funcional e bem pensada.</p>
            </article>
            <article class='feature-card'>
                <div class='feature-icon'>✦</div>
                <h3>Organização e agilidade</h3>
                <p>Solicitação simples, acompanhamento claro e planejamento mais tranquilo para você.</p>
            </article>
        </div>
    </section>

    <section class='wedding-showcase'>
        <div class='section-head'>
            <div><p class='eyebrow'>CASAMENTOS</p><h2>Inspire-se para o seu grande dia</h2></div>
            <a href='/catalogo?categoria=Casamento'>Ver itens para casamento →</a>
        </div>
        <div class='wedding-gallery'>
            <figure><img src='/static/static/images/casamentos/casamento-cerimonia.png' alt='Cerimônia de casamento ao ar livre, com flores e iluminação delicada'><figcaption>Uma cerimônia acolhedora, com cada detalhe pensado para emocionar.</figcaption></figure>
            <figure><img src='/static/static/images/casamentos/casamento-recepcao.png' alt='Recepção de casamento com mesas decoradas, lustre e tecidos no teto'><figcaption>Uma recepção elegante para celebrar com quem você ama.</figcaption></figure>
        </div>
    </section>

    <section id='testimonials' class='testimonials'>
        <div class='section-head'>
            <div><p class='eyebrow'>DEPOIMENTOS</p><h2>O que nossos clientes dizem</h2></div>
        </div>
        <div class='testimonial-grid'>
            <blockquote>
                <p>“Tudo ficou impecável. O atendimento foi acolhedor e os materiais deram um toque especial à nossa festa.”</p>
                <footer>— Ana & Rafael</footer>
            </blockquote>
            <blockquote>
                <p>“A organização foi excelente e o resultado final ficou muito bonito, com um clima muito elegante.”</p>
                <footer>— Maria Helena</footer>
            </blockquote>
            <blockquote>
                <p>“Precisávamos de uma solução prática e bonita para o evento corporativo. Foi exatamente isso que encontramos.”</p>
                <footer>— Diretoria da empresa</footer>
            </blockquote>
        </div>
    </section>

    <section class='steps'><p class='eyebrow'>COMO FUNCIONA</p><h2>Organize seu aluguel em 3 passos</h2><div class='step-grid'><p><b>01</b> Escolha os materiais no catálogo</p><p><b>02</b> Preencha seus dados e o pedido</p><p><b>03</b> Receba a confirmação e acompanhe na agenda</p></div></section>
    """, active_menu="inicio")


def catalogo_page(categoria_filtro: str = "") -> bytes:
    with closing(get_db()) as db:
        itens = catalogo_ativo(db)
        categorias = sorted({i["categoria"] for i in itens})
    grupos = agrupar_por_categoria(itens)
    tabs = "<a class='tab" + (" active" if not categoria_filtro else "") + "' href='/catalogo'>Todos</a>" + "".join(
        f"<a class='tab{' active' if categoria_filtro == c else ''}' href='/catalogo?categoria={esc(c)}'>{esc(c)}</a>"
        for c in categorias
    )
    secoes = []
    for categoria, lista in grupos.items():
        if categoria_filtro and categoria != categoria_filtro:
            continue
        cards = "".join(
            f"<article class='item-card'><h4>{esc(i['nome'])}</h4><p>{esc(i['descricao'])}</p>"
            f"<div class='item-price'>{fmt_money(i['preco_unitario'])} <small>/ {esc(i['unidade'])}</small></div></article>"
            for i in lista
        )
        secoes.append(f"<section class='catalog-category'><h3>{esc(categoria)}</h3><div class='grid three'>{cards}</div></section>")
    body = "".join(secoes) or "<p class='empty'>Nenhum item disponível nesta categoria.</p>"
    return layout(f"""<section class='catalog-head'>
    <div class='catalog-head-copy'>
        <p class='eyebrow'>NOSSO ACERVO</p>
        <h1>Catálogo de materiais</h1>
        <p class='lead'>Explore por categoria e monte sua lista com materiais pensados para festas, casamentos e eventos corporativos.</p>
    </div>
    <div class='catalog-mini-stats'>
        <div><strong>{len(itens)}</strong><span>itens</span></div>
        <div><strong>{len(categorias)}</strong><span>categorias</span></div>
    </div>
    </section>
    <div class='filter-tabs'>{tabs}</div>
    {body}
    <section class='cta-bar'><p>Já sabe o que precisa?</p><a class='button' href='/pedido'>Ir para o formulário de pedido →</a></section>""",
        "Catálogo", "catalogo")


def pedido_form(error: str = "", valores: dict | None = None) -> bytes:
    valores = valores or {}
    error_html = f"<p class='alert error'>{esc(error)}</p>" if error else ""
    with closing(get_db()) as db:
        itens = catalogo_ativo(db)
    grupos = agrupar_por_categoria(itens)

    def icone_categoria(categoria: str) -> str:
        mapa = {
            "casamento": "💍",
            "casamentos": "💍",
            "cerimonia": "💒",
            "recepcao": "🎉",
            "recepção": "🎉",
            "aniversario": "🎂",
            "aniversários": "🎂",
            "aniversarios": "🎂",
            "corporativo": "🏢",
            "corporativos": "🏢",
            "evento corporativo": "🏢",
            "materiais": "✨",
            "mesas": "🪑",
            "mesa": "🪑",
            "toalhas de mesa": "🧺",
            "toalhas": "🧺",
            "peças decorativas": "🌿",
            "pecas decorativas": "🌿",
            "provençal": "🪵",
            "provencal": "🪵",
            "pranchão redondo": "🍽️",
            "pranchao redondo": "🍽️",
            "tecido jacar": "🧵",
            "tensionamento de malhas": "🎀",
            "receptivos": "🎁",
            "coffee break": "☕",
            "buffet": "🍽️",
            "buffets": "🍽️",
            "estacao de sobremesas": "🍰",
            "estação de sobremesas": "🍰",
            "buffet finger food": "🥐",
            "buffet jantar completo": "🍽️",
            "coffee break simples": "☕",
            "coffee break completo": "☕",
            "mesas bistro": "🪑",
            "mesas redondas": "🪑",
            "mesas retangulares": "🪑",
        }
        chave = categoria.strip().lower().replace("  ", " ")
        return mapa.get(chave, "✦")

    def paleta_categoria(categoria: str) -> tuple[str, str]:
        mapa = {
            "casamento": ("#f4e3b5", "#8a692d"),
            "casamentos": ("#f4e3b5", "#8a692d"),
            "aniversario": ("#fbd8d0", "#af5c4b"),
            "aniversários": ("#fbd8d0", "#af5c4b"),
            "aniversarios": ("#fbd8d0", "#af5c4b"),
            "corporativo": ("#dfeafc", "#45639a"),
            "corporativos": ("#dfeafc", "#45639a"),
            "mesas": ("#efe4de", "#6d5147"),
            "mesa": ("#efe4de", "#6d5147"),
            "buffet": ("#f9ddd1", "#a76044"),
            "coffee break": ("#f5dfbf", "#9b6937"),
            "toalhas de mesa": ("#eaf6e8", "#49724d"),
            "toalhas": ("#eaf6e8", "#49724d"),
            "provençal": ("#ece2d8", "#7a6049"),
            "provencal": ("#ece2d8", "#7a6049"),
            "peças decorativas": ("#e5f0e2", "#4e7d5a"),
            "pecas decorativas": ("#e5f0e2", "#4e7d5a"),
            "receptivos": ("#f4e6d2", "#a46d34"),
            "receptivos": ("#f4e6d2", "#a46d34"),
            "tecido jacar": ("#efe5f5", "#775f8d"),
            "tensionamento de malhas": ("#fbe5f5", "#924f78"),
            "pranchão redondo": ("#e8ebef", "#5d6774"),
            "pranchao redondo": ("#e8ebef", "#5d6774"),
        }
        chave = categoria.strip().lower().replace("  ", " ")
        return mapa.get(chave, ("#f5efe7", "#7b6255"))

    def campo(name, label, tipo="text", required=True, placeholder="", extra=""):
        req = "required" if required else ""
        val = esc(valores.get(name, ""))
        return f"<label>{label}<input {req} type='{tipo}' name='{name}' value='{val}' placeholder='{placeholder}' {extra}></label>"

    catalog_html = []
    for categoria, lista in grupos.items():
        linhas = "".join(
            f"<div class='item-row' data-categoria='{esc(categoria)}'>"
            f"<div class='item-row-media' style='--icon-bg:{paleta_categoria(categoria)[0]}; --icon-color:{paleta_categoria(categoria)[1]};'><span>{icone_categoria(categoria)}</span></div>"
            f"<div class='item-row-info'><b>{esc(i['nome'])}</b><small>{esc(i['descricao'])} · {fmt_money(i['preco_unitario'])}/{esc(i['unidade'])}</small></div>"
            f"<input class='qty-input' type='number' min='0' step='1' value='0' name='qtd_{i['id']}' "
            f"data-price='{i['preco_unitario']}' data-nome='{esc(i['nome'])}'>"
            f"</div>"
            for i in lista
        )
        bg, fg = paleta_categoria(categoria)
        catalog_html.append(
            f"<fieldset class='catalog-fieldset' data-categoria='{esc(categoria)}' style='--fieldset-accent:{bg}; --fieldset-text:{fg};'><legend>{esc(categoria)}</legend>{linhas}</fieldset>"
        )

    return layout(f"""<section class='form-wrap'>
    <div class='pedido-intro'>
        <p class='eyebrow'>NOVA SOLICITAÇÃO</p>
        <h1>Vamos planejar seu evento</h1>
        <p class='lead'>Preencha seus dados, escolha os materiais e sua solicitação será salva na agenda.</p>
    </div>
    {error_html}
    <div class='form-shell'>
    <form method='post' action='/pedido' id='pedido-form'>
    <h2 class='form-subtitle'>Seus dados</h2>
    <div class='form-grid'>
    {campo('nome', 'Nome completo', placeholder='Como devemos chamar você?')}
    {campo('email', 'E-mail', tipo='email', placeholder='voce@email.com')}
    {campo('telefone', 'Telefone', placeholder='(00) 00000-0000')}
    {campo('endereco', 'Endereço', placeholder='Rua, número e bairro')}
    <label>Tipo de evento<select required name='tipo_evento'><option value=''>Selecione</option>
        {"".join(f"<option {'selected' if valores.get('tipo_evento') == t else ''}>{t}</option>" for t in ('Casamento','Aniversário','Corporativo','Outro'))}
    </select></label>
    {campo('data_evento', 'Data do evento', tipo='date')}
    {campo('horario', 'Horário de retirada/entrega', tipo='time')}
    {campo('quantidade_convidados', 'Número de convidados', tipo='number', extra="min='1'", placeholder='Ex.: 80')}
    </div>

    <h2 class='form-subtitle'>Escolha os materiais</h2>
    <p class='lead small'>Informe a quantidade desejada de cada item. Deixe 0 para os que não precisar.</p>
    <div class='filter-tabs' id='pedido-tabs'>
        <a class='tab active' data-categoria='__all__'>Todos</a>
        {''.join(f"<a class='tab' data-categoria='{esc(c)}' style='--tab-bg:{paleta_categoria(c)[0]}; --tab-color:{paleta_categoria(c)[1]};'>{esc(c)}</a>" for c in grupos)}
    </div>
    <div class='catalog-form'>{''.join(catalog_html)}</div>

    <label>Outros materiais (não estão no catálogo)<textarea name='materiais_extra' placeholder='Ex.: algo específico que você precise e não encontrou acima'>{esc(valores.get('materiais_extra',''))}</textarea></label>
    <label>Observações<textarea name='observacoes' placeholder='Alguma informação adicional?'>{esc(valores.get('observacoes',''))}</textarea></label>

    <div class='total-bar'><span>Valor estimado</span><strong id='total-estimado'>{fmt_money(0)}</strong></div>
    <button class='button' type='submit'>Enviar pedido e agendar →</button></form></div></section>""", active_menu="pedido")


def create_order(data: dict[str, str]) -> tuple[int, float]:
    required = ("nome", "email", "telefone", "endereco", "tipo_evento", "data_evento", "horario", "quantidade_convidados")
    if any(not data.get(key, "").strip() for key in required):
        raise ValueError("Preencha todos os campos obrigatórios.")
    try:
        guests = int(data["quantidade_convidados"])
        if guests < 1:
            raise ValueError
        datetime.strptime(data["data_evento"], "%Y-%m-%d")
        datetime.strptime(data["horario"], "%H:%M")
    except ValueError as exc:
        raise ValueError("Verifique a data, o horário e o número de convidados.") from exc

    itens_selecionados = []
    with closing(get_db()) as db:
        catalogo = {str(i["id"]): i for i in catalogo_ativo(db)}
    for key, value in data.items():
        if not key.startswith("qtd_"):
            continue
        material_id = key[len("qtd_"):]
        material = catalogo.get(material_id)
        if not material:
            continue
        try:
            qtd = int(value)
        except ValueError:
            qtd = 0
        if qtd > 0:
            itens_selecionados.append((material, qtd))

    materiais_extra = data.get("materiais_extra", "").strip()
    if not itens_selecionados and not materiais_extra:
        raise ValueError("Selecione ao menos um material do catálogo ou descreva o que precisa em 'Outros materiais'.")

    valor_total = sum(m["preco_unitario"] * q for m, q in itens_selecionados)
    now = datetime.now().isoformat(timespec="seconds")
    with closing(get_db()) as db, db:
        client = db.execute(
            "INSERT INTO clientes (nome,email,telefone,endereco,criado_em) VALUES (?,?,?,?,?)",
            (data['nome'].strip(), data['email'].strip(), data['telefone'].strip(), data['endereco'].strip(), now),
        )
        order = db.execute(
            """INSERT INTO pedidos (cliente_id,tipo_evento,data_evento,horario,quantidade_convidados,materiais_extra,observacoes,valor_total,pix_chave,pix_qr,criado_em)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (client.lastrowid, data['tipo_evento'], data['data_evento'], data['horario'], guests,
             materiais_extra, data.get('observacoes', '').strip(), valor_total, PIX_CHAVE_PADRAO, gerar_qr_visual(PIX_CHAVE_PADRAO), now),
        )
        pedido_id = order.lastrowid
        for material, qtd in itens_selecionados:
            db.execute(
                """INSERT INTO pedido_itens (pedido_id,material_id,nome_material,categoria,quantidade,preco_unitario)
                    VALUES (?,?,?,?,?,?)""",
                (pedido_id, material["id"], material["nome"], material["categoria"], qtd, material["preco_unitario"]),
            )
        return pedido_id, valor_total  # type: ignore[return-value]


def success(order_id: int, valor_total: float) -> bytes:
    return layout(
        f"""<section class='confirmation'><div class='check'>✓</div><p class='eyebrow'>PEDIDO #{order_id:04d}</p><h1>Seu aluguel já foi agendado com sucesso!</h1><p class='lead'>Recebemos seu pedido, no valor estimado de <b>{fmt_money(valor_total)}</b>, e ele está salvo em nossa agenda. Em breve entraremos em contato para confirmar os detalhes.</p>
        <div class='actions-row'>
            <a class='button' href='/pedido/{order_id}/relatorio'>Imprimir relatório</a>
            <a class='button secondary' href='/pedido/{order_id}/pix'>Pagar com Pix</a>
        </div>
        <a class='text-link' href='/'>Voltar ao início</a></section>""",
        "Pedido confirmado",
    )


def testimonials_section() -> str:
    return """
    <section id='testimonials' class='testimonials'>
        <div class='section-head'>
            <div><p class='eyebrow'>DEPOIMENTOS</p><h2>O que nossos clientes dizem</h2></div>
        </div>
        <div class='testimonial-grid'>
            <blockquote>
                <p>“Tudo ficou impecável. O atendimento foi acolhedor e os materiais deram um toque especial à nossa festa.”</p>
                <footer>— Ana & Rafael</footer>
            </blockquote>
            <blockquote>
                <p>“A organização foi excelente e o resultado final ficou muito bonito, com um clima muito elegante.”</p>
                <footer>— Maria Helena</footer>
            </blockquote>
            <blockquote>
                <p>“Precisávamos de uma solução prática e bonita para o evento corporativo. Foi exatamente isso que encontramos.”</p>
                <footer>— Diretoria da empresa</footer>
            </blockquote>
        </div>
    </section>
    """


def testimonials_page() -> bytes:
    return layout(testimonials_section(), "Depoimentos")


# --------------------------------------------------------------------------
# Painel administrativo
# --------------------------------------------------------------------------

def admin(filtro_status: str = "") -> bytes:
    with closing(get_db()) as db:
        query = """SELECT p.*, c.nome, c.email, c.telefone FROM pedidos p
                   JOIN clientes c ON c.id = p.cliente_id"""
        params: tuple = ()
        if filtro_status:
            query += " WHERE p.status = ?"
            params = (filtro_status,)
        query += " ORDER BY p.data_evento, p.horario"
        orders = db.execute(query, params).fetchall()
        itens_por_pedido: dict[int, list] = {}
        if orders:
            ids = [o["id"] for o in orders]
            placeholders = ",".join("?" for _ in ids)
            for item in db.execute(f"SELECT * FROM pedido_itens WHERE pedido_id IN ({placeholders})", ids):
                itens_por_pedido.setdefault(item["pedido_id"], []).append(item)

    tabs = "<a class='tab" + (" active" if not filtro_status else "") + "' href='/admin'>Todos</a>" + "".join(
        f"<a class='tab{' active' if filtro_status == s else ''}' href='/admin?status={esc(s)}'>{esc(s)}</a>"
        for s in STATUS_OPCOES
    )

    def linha(o: sqlite3.Row) -> str:
        itens = itens_por_pedido.get(o["id"], [])
        lista_itens = "".join(f"<li>{it['quantidade']}× {esc(it['nome_material'])}</li>" for it in itens)
        extra = f"<li><i>Outros:</i> {esc(o['materiais_extra'])}</li>" if o["materiais_extra"] else ""
        materiais_html = f"<ul class='item-list'>{lista_itens}{extra}</ul>" if (lista_itens or extra) else "<small>Nenhum item</small>"
        select_status = "".join(
            f"<option value='{s}' {'selected' if o['status'] == s else ''}>{s}</option>" for s in STATUS_OPCOES
        )
        return (
            f"<tr><td>#{o['id']:04d}</td>"
            f"<td><b>{esc(o['nome'])}</b><small>{esc(o['email'])}<br>{esc(o['telefone'])}</small></td>"
            f"<td>{esc(o['tipo_evento'])}{materiais_html}</td>"
            f"<td>{esc(o['data_evento'])}<small>{esc(o['horario'])} · {o['quantidade_convidados']} convidados</small></td>"
            f"<td>{fmt_money(o['valor_total'])}</td>"
            f"<td><form method='post' action='/admin/pedido/{o['id']}/status' class='status-form'>"
            f"<select name='status' onchange='this.form.submit()'>{select_status}</select></form></td></tr>"
        )

    table = "".join(linha(o) for o in orders) or "<tr><td colspan='6' class='empty'>Nenhum agendamento encontrado.</td></tr>"
    return layout(
        f"""<section class='admin-head'><p class='eyebrow'>PAINEL ADMINISTRATIVO</p><h1>Agenda de locações</h1>
        <p class='lead'>{len(orders)} pedido(s) {"no status " + esc(filtro_status) if filtro_status else "registrado(s) no sistema"}.</p>
        <div class='filter-tabs'>{tabs}</div>
        <nav class='admin-links'><a href='/admin/materiais'>Gerenciar catálogo →</a><a href='/admin/clientes'>Ver clientes →</a></nav>
        </section>
        <section class='table-wrap'><table><thead><tr><th>Pedido</th><th>Cliente</th><th>Evento e materiais</th><th>Data</th><th>Valor</th><th>Status</th></tr></thead><tbody>{table}</tbody></table></section>""",
        "Agenda", "agenda",
    )


def update_status(pedido_id: int, novo_status: str) -> None:
    if novo_status not in STATUS_OPCOES:
        raise ValueError("Status inválido.")
    with closing(get_db()) as db, db:
        db.execute("UPDATE pedidos SET status = ? WHERE id = ?", (novo_status, pedido_id))


def admin_clientes() -> bytes:
    with closing(get_db()) as db:
        clientes = db.execute(
            """SELECT c.*, COUNT(p.id) AS total_pedidos, COALESCE(SUM(p.valor_total),0) AS total_gasto
               FROM clientes c LEFT JOIN pedidos p ON p.cliente_id = c.id
               GROUP BY c.id ORDER BY c.nome"""
        ).fetchall()
    rows = "".join(
        f"<tr><td><b>{esc(c['nome'])}</b><small>desde {esc(c['criado_em'][:10])}</small></td>"
        f"<td>{esc(c['email'])}<small>{esc(c['telefone'])}</small></td>"
        f"<td>{esc(c['endereco'])}</td>"
        f"<td>{c['total_pedidos']}</td><td>{fmt_money(c['total_gasto'])}</td></tr>"
        for c in clientes
    )
    table = rows or "<tr><td colspan='5' class='empty'>Nenhum cliente cadastrado ainda.</td></tr>"
    return layout(
        f"""<section class='admin-head'><p class='eyebrow'>CLIENTES</p><h1>Clientes cadastrados</h1>
        <p class='lead'>{len(clientes)} cliente(s) no sistema.</p>
        <nav class='admin-links'><a href='/admin'>← Voltar para agenda</a></nav></section>
        <section class='table-wrap'><table><thead><tr><th>Cliente</th><th>Contato</th><th>Endereço</th><th>Pedidos</th><th>Total gasto</th></tr></thead><tbody>{table}</tbody></table></section>""",
        "Clientes", "agenda",
    )


def admin_materiais(error: str = "") -> bytes:
    with closing(get_db()) as db:
        itens = db.execute("SELECT * FROM materiais ORDER BY ativo DESC, categoria, nome").fetchall()
    error_html = f"<p class='alert error'>{esc(error)}</p>" if error else ""
    rows = "".join(
        f"<tr class='{'inativo' if not i['ativo'] else ''}'><td>{esc(i['categoria'])}</td>"
        f"<td><b>{esc(i['nome'])}</b><small>{esc(i['descricao'])}</small></td>"
        f"<td>{fmt_money(i['preco_unitario'])} / {esc(i['unidade'])}</td>"
        f"<td><span class='badge {'ok' if i['ativo'] else 'off'}'>{'Ativo' if i['ativo'] else 'Inativo'}</span></td>"
        f"<td class='actions'>"
        f"<form method='post' action='/admin/materiais/{i['id']}/toggle'><button class='link-btn' type='submit'>{'Desativar' if i['ativo'] else 'Ativar'}</button></form>"
        f"<form method='post' action='/admin/materiais/{i['id']}/excluir' onsubmit=\"return confirm('Excluir este item do catálogo?');\"><button class='link-btn danger' type='submit'>Excluir</button></form>"
        f"</td></tr>"
        for i in itens
    )
    table = rows or "<tr><td colspan='5' class='empty'>Nenhum item cadastrado.</td></tr>"
    return layout(
        f"""<section class='admin-head'><p class='eyebrow'>CATÁLOGO</p><h1>Gerenciar materiais</h1>
        <p class='lead'>{len(itens)} item(ns) cadastrado(s).</p>
        <nav class='admin-links'><a href='/admin'>← Voltar para agenda</a></nav></section>
        {error_html}
        <section class='form-wrap narrow'><h2 class='form-subtitle'>Adicionar novo item</h2>
        <form method='post' action='/admin/materiais'>
        <div class='form-grid'>
        <label>Categoria<input required name='categoria' placeholder='Ex.: Coffee break'></label>
        <label>Nome<input required name='nome' placeholder='Nome do item'></label>
        <label>Preço unitário (R$)<input required type='number' step='0.01' min='0' name='preco_unitario' placeholder='0.00'></label>
        <label>Unidade<input required name='unidade' placeholder='un / pessoa / conjunto'></label>
        </div>
        <label>Descrição<textarea name='descricao' placeholder='Breve descrição do item'></textarea></label>
        <button class='button' type='submit'>Adicionar ao catálogo</button>
        </form></section>
        <section class='table-wrap'><table><thead><tr><th>Categoria</th><th>Item</th><th>Preço</th><th>Status</th><th>Ações</th></tr></thead><tbody>{table}</tbody></table></section>""",
        "Catálogo · Admin", "agenda",
    )


def add_material(data: dict[str, str]) -> None:
    required = ("categoria", "nome", "preco_unitario", "unidade")
    if any(not data.get(key, "").strip() for key in required):
        raise ValueError("Preencha categoria, nome, preço e unidade.")
    try:
        preco = float(data["preco_unitario"].replace(",", "."))
        if preco < 0:
            raise ValueError
    except ValueError as exc:
        raise ValueError("Informe um preço válido.") from exc
    with closing(get_db()) as db, db:
        db.execute(
            "INSERT INTO materiais (categoria,nome,descricao,preco_unitario,unidade,ativo) VALUES (?,?,?,?,?,1)",
            (data["categoria"].strip(), data["nome"].strip(), data.get("descricao", "").strip(), preco, data["unidade"].strip()),
        )


def toggle_material(material_id: int) -> None:
    with closing(get_db()) as db, db:
        db.execute("UPDATE materiais SET ativo = 1 - ativo WHERE id = ?", (material_id,))


def excluir_material(material_id: int) -> None:
    with closing(get_db()) as db, db:
        em_uso = db.execute("SELECT COUNT(*) AS n FROM pedido_itens WHERE material_id = ?", (material_id,)).fetchone()["n"]
        if em_uso:
            db.execute("UPDATE materiais SET ativo = 0 WHERE id = ?", (material_id,))
        else:
            db.execute("DELETE FROM materiais WHERE id = ?", (material_id,))


def not_found() -> bytes:
    return layout("<section class='confirmation'><h1>Página não encontrada.</h1><a class='button' href='/'>Ir para início</a></section>", "Não encontrada")


def serve_static(path: str):
    requested_path = Path(path)
    if requested_path.is_absolute() or ".." in requested_path.parts:
        return None
    file_path = STATIC_DIR / requested_path
    if not file_path.is_file() or STATIC_DIR not in file_path.resolve().parents:
        return None
    if file_path.suffix == ".css":
        content_type = "text/css; charset=utf-8"
    elif file_path.suffix == ".js":
        content_type = "application/javascript; charset=utf-8"
    elif file_path.suffix == ".png":
        content_type = "image/png"
    elif file_path.suffix in {".jpg", ".jpeg"}:
        content_type = "image/jpeg"
    elif file_path.suffix == ".webp":
        content_type = "image/webp"
    else:
        content_type = "application/octet-stream"
    return file_path.read_bytes(), content_type


def read_body(environ) -> dict[str, str]:
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError:
        length = 0
    raw = environ["wsgi.input"].read(length).decode() if length else ""
    parsed = parse_qs(raw)
    return {k: v[0] for k, v in parsed.items()}


ID_PATTERN = re.compile(r"^/admin/(pedido|materiais)/(\d+)/(status|toggle|excluir)$")
ORDER_ACTION_PATTERN = re.compile(r"^/pedido/(\d+)/(relatorio|pix|comprovante)$")


def application(environ, start_response):
    init_db()
    path, method = environ.get("PATH_INFO", "/"), environ.get("REQUEST_METHOD", "GET")
    qs = parse_qs(environ.get("QUERY_STRING", ""))

    def respond(body: bytes, status: str, content_type: str = "text/html; charset=utf-8"):
        start_response(status, [("Content-Type", content_type), ("Content-Length", str(len(body)))])
        return [body]

    def redirect(location: str, status: str = "303 See Other"):
        start_response(status, [("Location", location), ("Content-Length", "0")])
        return [b""]

    if path.startswith("/static/"):
        result = serve_static(path[len("/static/"):])
        if result is None:
            return respond(b"Not found", "404 Not Found", "text/plain; charset=utf-8")
        body, content_type = result
        return respond(body, "200 OK", content_type)

    match = ID_PATTERN.match(path)
    if match and method == "POST":
        entity, obj_id, action = match.group(1), int(match.group(2)), match.group(3)
        try:
            if entity == "pedido" and action == "status":
                data = read_body(environ)
                update_status(obj_id, data.get("status", ""))
                return redirect("/admin")
            if entity == "materiais" and action == "toggle":
                toggle_material(obj_id)
                return redirect("/admin/materiais")
            if entity == "materiais" and action == "excluir":
                excluir_material(obj_id)
                return redirect("/admin/materiais")
        except ValueError:
            return redirect("/admin")
        return respond(not_found(), "404 Not Found")

    if path == "/" and method == "GET":
        return respond(home(), "200 OK")

    if path == "/catalogo" and method == "GET":
        categoria = (qs.get("categoria") or [""])[0]
        return respond(catalogo_page(categoria), "200 OK")

    if path == "/pedido" and method == "GET":
        return respond(pedido_form(), "200 OK")

    if path == "/pedido" and method == "POST":
        values = read_body(environ)
        try:
            pedido_id, valor_total = create_order(values)
            return respond(success(pedido_id, valor_total), "201 Created")
        except ValueError as exc:
            return respond(pedido_form(str(exc), values), "400 Bad Request")

    order_match = ORDER_ACTION_PATTERN.match(path)
    if order_match and method == "GET":
        pedido_id = int(order_match.group(1))
        action = order_match.group(2)
        if action == "relatorio":
            return respond(pedido_relatorio_page(pedido_id), "200 OK")
        if action == "pix":
            return respond(pedido_pix_page(pedido_id), "200 OK")
        if action == "comprovante":
            return respond(comprovante_pix_page(pedido_id), "200 OK")

    if path == "/testimonials" and method == "GET":
        return respond(testimonials_page(), "200 OK")

    if path == "/debug/qr" and method == "GET":
        return respond(debug_recent_qr_page(), "200 OK")

    if order_match and method == "POST":
        pedido_id = int(order_match.group(1))
        action = order_match.group(2)
        if action == "pix":
            try:
                confirmar_pagamento_pix(pedido_id)
                return redirect(f"/pedido/{pedido_id}/comprovante")
            except ValueError:
                return redirect("/")

    if path == "/admin" and method == "GET":
        status_filtro = (qs.get("status") or [""])[0]
        return respond(admin(status_filtro), "200 OK")

    if path == "/admin/clientes" and method == "GET":
        return respond(admin_clientes(), "200 OK")

    if path == "/admin/materiais" and method == "GET":
        return respond(admin_materiais(), "200 OK")

    if path == "/admin/materiais" and method == "POST":
        values = read_body(environ)
        try:
            add_material(values)
            return redirect("/admin/materiais")
        except ValueError as exc:
            return respond(admin_materiais(str(exc)), "400 Bad Request")

    return respond(not_found(), "404 Not Found")


if __name__ == "__main__":
    init_db()
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    display_host = "localhost" if host == "0.0.0.0" else host
    print(f"Sistema disponível em http://{display_host}:{port}")
    make_server(host, port, application).serve_forever()
