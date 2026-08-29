import sqlite3, urllib.request, datetime

db = sqlite3.connect('sistema_eventos.db')
now = datetime.datetime.now().isoformat(timespec='seconds')
cur = db.execute(
    'INSERT INTO clientes (nome,email,telefone,endereco,criado_em) VALUES (?,?,?,?,?)',
    ('Teste Pix validacao', 'validacao@email.com', '11999999999', 'Rua C, 3', now),
)
pedido = db.execute(
    'INSERT INTO pedidos (cliente_id,tipo_evento,data_evento,horario,quantidade_convidados,materiais_extra,observacoes,valor_total,status,criado_em) VALUES (?,?,?,?,?,?,?,?,?,?)',
    (cur.lastrowid, 'Casamento', '2030-12-20', '19:00', 30, '', '', 250.0, 'Agendado', now),
)
db.commit()
pedido_id = pedido.lastrowid
body = urllib.request.urlopen(f'http://localhost:8000/pedido/{pedido_id}/pix').read().decode('utf-8')
print('pedido_id=', pedido_id)
print('pix_found=', 'PAGAMENTO VIA PIX' in body)
print('button_found=', 'Confirmar pagamento' in body)
print('key_found=', 'pix-key' in body or 'Chave Pix' in body)
