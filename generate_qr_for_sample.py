from app import init_db, get_db, atualizar_chave_pix_do_pedido, PIX_CHAVE_PADRAO
from contextlib import closing
from datetime import datetime

init_db()
now = datetime.now().isoformat(timespec="seconds")
with closing(get_db()) as db, db:
    cur = db.execute(
        "INSERT INTO clientes (nome,email,telefone,endereco,criado_em) VALUES (?,?,?,?,?)",
        ("Dilton Batista de Souza", "dilton@example.com", "71 99910-3676", "Salvador, BA", now),
    )
    order = db.execute(
        """INSERT INTO pedidos (cliente_id,tipo_evento,data_evento,horario,quantidade_convidados,materiais_extra,observacoes,valor_total,pix_chave,pix_qr,criado_em)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (cur.lastrowid, "Teste", "2030-01-01", "12:00", 10, "", "", 100.0, PIX_CHAVE_PADRAO, "", now),
    )
    pedido_id = order.lastrowid

print("Pedido criado:", pedido_id)
chave = atualizar_chave_pix_do_pedido(pedido_id, PIX_CHAVE_PADRAO)
print("Chave usada:", chave)
print(f"QR image esperado em: static/pix_qr_{pedido_id}.png")
