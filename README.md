# Almoxarifado – Equipamentos Elétricos

Sistema web de gestão de almoxarifado (isoladores, para-raios, postes, chaves fusível etc.).

**Stack:** Python 3.11+ · FastAPI · SQLAlchemy · Microsoft SQL Server · HTML/JS + Bootstrap 5.

```
almoxarifado/
├── database/schema.sql        # DDL completo (SQL Server)
├── backend/app/
│   ├── database.py            # conexão (DATABASE_URL, BASE_URL)
│   ├── models.py              # Material, Ficha, FichaItem, Movimentacao, ImportacaoCatalogo
│   ├── schemas.py             # validação (zonas e incidências obrigatórias)
│   ├── importador_mb.py       # upsert do relatório MB (xlsx/csv)
│   └── main.py                # endpoints REST + serve o frontend
├── frontend/                  # dashboard (index.html, css/, js/)
└── exemplo_mb.csv             # modelo de arquivo MB
```

## Modelo de dados
- `zona`, `incidencia`: tabelas de domínio (4 zonas; BA, OT, SOB, INCIDÊNCIA, ANE, DT, SGD, SGM, RENO).
- `material` (código único, descrição, zona, quantidade).
- `ficha` (nº documento único, solicitante, LEAD, local, incidência, status, `token_qr` único) e `ficha_item`.
- `movimentacao`: livro imutável (SAIDA, ESTORNO, DEVOLUCAO, SUCATA, ENTRADA, AJUSTE) com documento, responsável, local, data/hora. Alimenta as métricas, a tela de sucatas e os relatórios.
- **Histórico preservado no MB:** o upsert é feito por `codigo`, nunca apaga materiais e não toca em `movimentacao`.

## Como rodar
1. **Banco (opcional)** – rode `database/schema.sql` no SQL Server. Sem isso, a aplicação usa SQLite local (`almoxarifado.db`) e cria as tabelas sozinha. Com SQL Server, instale o *ODBC Driver 18*.
2. **Backend**
   ```powershell
   cd almoxarifado\backend
   python -m venv .venv ; .\.venv\Scripts\activate
   pip install -r requirements.txt
   # SQL Server (opcional):
   $env:DATABASE_URL="mssql+pyodbc://usuario:senha@SERVIDOR/almoxarifado?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes"
   # URL que o celular alcança (vai dentro do QR Code):
   $env:BASE_URL="http://IP-DO-SERVIDOR:8000"
   uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```
3. Abra `http://localhost:8000` (docs da API em `/docs`).
4. Vá em **Importar MB** e envie seu arquivo (ou teste com `exemplo_mb.csv`).

## Endpoints principais
| Método | Rota | Função |
|---|---|---|
| GET/POST | `/api/materiais` | listar (filtros `zona`, `q`) / cadastrar |
| GET | `/api/materiais/{codigo}/perfil?dias=` | última saída, médias, histórico |
| POST | `/api/fichas` | cria ficha (gera `token_qr`) |
| GET | `/api/fichas/{id}/qrcode` | PNG do QR Code |
| POST | `/api/fichas/{id}/acrescimo` | inclui materiais (só em separação) |
| POST | `/api/fichas/{id}/baixa` · `/api/fichas/token/{token}/baixa` | baixa automática do estoque |
| POST | `/api/fichas/{id}/estorno` | desfaz a saída (ou cancela se em separação) |
| POST | `/api/devolucoes` | devolução ao estoque ou sucata |
| GET | `/api/sucatas-devolucoes` | dashboard de sucatas/devoluções |
| GET | `/api/relatorios/saidas?codigos=&dias=` | dados do relatório A4 |
| POST | `/api/catalogo/importar` | upload do MB (upsert) |

## Fluxo do QR Code
O QR contém `BASE_URL/?confirmar=TOKEN`. Ao escanear, o dashboard abre a ficha com o botão **Confirmar baixa**, que executa a baixa (idempotente: uma ficha só baixa uma vez; estoque insuficiente bloqueia com erro 409). A baixa exige confirmação deliberada para evitar que um GET acidental altere o estoque.

## Importação do MB
Reconhece o cabeçalho automaticamente (Código/Cod/Material, Descrição/Texto breve, e opcionalmente Zona, Unidade, Quantidade). Código novo → insere (zona do arquivo ou inferida pela descrição; padrão "FERRAGENS e SUCATAS"). Código existente → atualiza descrição/unidade/zona. O **estoque existente não é sobrescrito**, salvo se marcar "atualizar estoque (inventário)", caso em que o ajuste é registrado como `AJUSTE`.

## Relatório A4
Tela **Relatórios** → *Gerar* → *Imprimir / PDF* (escolha "Salvar como PDF"; o CSS `@page A4` oculta menus).

## Próximos passos recomendados
Autenticação/perfis de usuário, migrações (Alembic) e paginação para catálogos muito grandes.
