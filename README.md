# Dial Eventos — Sistema de locação de materiais para eventos

Aplicação 100% Python (biblioteca padrão), sem dependências externas.
Todo o HTML é gerado dentro de `app.py` — não há motor de templates.

## Estrutura
```
dial-eventos/
├── app.py              # aplicação WSGI (rotas, banco de dados, HTML)
├── static/
│   ├── style.css        # estilos do site
│   └── scripts.js       # interações do lado do cliente
└── sistema_eventos.db   # criado automaticamente na primeira execução
```

## Como rodar localmente
```bash
python3 app.py
```
Acesse http://localhost:8000

Portas/host personalizados (útil para deploy):
```bash
PORT=8080 HOST=0.0.0.0 python3 app.py
```

## Rotas públicas
- `GET /` — página inicial (mostra as categorias do catálogo)
- `GET /catalogo` — catálogo completo, com filtro `?categoria=`
- `GET /pedido` — formulário de solicitação (dados do cliente + seleção de
  materiais com quantidade + campo livre para itens fora do catálogo)
- `POST /pedido` — cria cliente + pedido + itens do pedido no banco (SQLite)
  e calcula o valor total estimado
- `GET /static/<arquivo>` — CSS e JS

## Painel administrativo
- `GET /admin` — todos os pedidos, com filtro por status, itens
  detalhados e valor; permite trocar o status do pedido (dropdown que
  salva automaticamente)
- `POST /admin/pedido/<id>/status` — atualiza o status de um pedido
- `GET /admin/clientes` — lista de clientes cadastrados, com total de
  pedidos e valor total gasto por cliente
- `GET /admin/materiais` — gestão do catálogo (listar, adicionar)
- `POST /admin/materiais` — adiciona um novo item ao catálogo
- `POST /admin/materiais/<id>/toggle` — ativa/desativa um item
- `POST /admin/materiais/<id>/excluir` — remove um item (se ele já foi
  usado em algum pedido, o sistema apenas o desativa, para não quebrar o
  histórico)

## Catálogo de materiais
O catálogo já vem populado (na primeira execução) com itens de exemplo nas
categorias:

Peças decorativas · Provençal · Pranchão redondo · Toalhas de mesa ·
Tecido jacar · Tensionamento de malhas (cadeiras) · Receptivos ·
Coffee break · Buffet · Mesas

Cada item tem nome, descrição, preço unitário e unidade (`un`, `pessoa`,
`conjunto`). Tudo isso é 100% editável pelo painel `/admin/materiais` —
os valores de exemplo servem apenas de ponto de partida.

## Como funciona o pedido
No formulário `/pedido`, os materiais aparecem agrupados por categoria com
um campo de quantidade para cada item (0 = não incluir). O JavaScript
(`static/scripts.js`) calcula o **valor estimado em tempo real** conforme o
usuário digita as quantidades, e permite filtrar os grupos por categoria —
mas o formulário funciona normalmente mesmo sem JavaScript habilitado
(o cálculo final e a validação sempre acontecem no servidor).

Ao enviar, o sistema:
1. Valida os campos obrigatórios, data, horário e nº de convidados;
2. Cria (ou registra) o cliente;
3. Cria o pedido com o valor total calculado a partir dos itens
   selecionados;
4. Grava cada item escolhido em `pedido_itens`, junto com o preço no
   momento do pedido (histórico não muda se o preço do catálogo mudar
   depois).

## Banco de dados
Tabelas: `clientes`, `materiais` (catálogo), `pedidos` e `pedido_itens`
(itens de cada pedido, ligando pedido ↔ material). Todas as conexões usam
`with closing(get_db()) as db, db:` para garantir commit/rollback e
fechamento da conexão.

## Deploy rápido em um VPS
```bash
# Executar em segundo plano
nohup python3 app.py > server.log 2>&1 &

# (opcional) rodar como serviço systemd, colocando este bloco em
# /etc/systemd/system/dial-eventos.service
[Unit]
Description=Dial Eventos
After=network.target

[Service]
WorkingDirectory=/caminho/para/dial-eventos
ExecStart=/usr/bin/python3 app.py
Environment=PORT=8000
Restart=always

[Install]
WantedBy=multi-user.target
```

Depois: `sudo systemctl enable --now dial-eventos`.

> Para produção real, recomenda-se colocar um proxy reverso (nginx/Caddy)
> na frente do `wsgiref`, já que ele é um servidor simples, adequado para
> desenvolvimento e cargas baixas — não para alto tráfego concorrente.

## Sobre os arquivos `index.html` e `scripts.js` originais
O `index.html` que fazia parte do projeto usava sintaxe de template Jinja
(`{{ url_for(...) }}`), que não existe nesta arquitetura (WSGI puro, sem
Flask) — por isso ele nunca foi de fato servido pelo `app.py`. Todo o
conteúdo relevante dele (hero, mostruário, formulário) já estava replicado
dentro de `app.py`, então o arquivo separado foi descartado para não haver
duas fontes de verdade divergentes. O `scripts.js` estava vazio e agora foi
implementado e está de fato conectado ao site (referenciado em toda página).
