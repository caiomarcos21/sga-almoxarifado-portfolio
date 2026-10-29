import time
import io
import json
import secrets
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import hashlib
import qrcode
from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile, Header, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from . import schemas
from .database import BASE_URL, Base, engine, get_db, SessionLocal
from .importador_mb import importar_mb
from .models import (Ficha, FichaItem, ImportacaoCatalogo, Material, Movimentacao, Usuario, EstadoCentralDB, SessaoAtiva, INCIDENCIAS, ZONAS)

Base.metadata.create_all(engine)
app = FastAPI(title="Almoxarifado - Equipamentos Elétricos")

# ------------------------------------------------------------------ Segurança e Autenticação Criptografada (PBKDF2-SHA256)
def gerar_hash_senha(senha: str, salt: str = None) -> tuple[str, str]:
    if not salt:
        salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac(
        'sha256',
        senha.encode('utf-8'),
        salt.encode('utf-8'),
        100000
    ).hex()
    return hashed, salt


def verificar_hash_senha(senha_digitada: str, salt: str, hash_esperado: str) -> bool:
    hashed, _ = gerar_hash_senha(senha_digitada, salt)
    return secrets.compare_digest(hashed, hash_esperado)


CHAVES_SECRETAS_VALIDAS = {
    "demo-2026",
    "demo-2026",
    "demo-2026",
    "demo-2026",
    "demo-2026",
}

SESSAO_CACHE: dict[str, dict] = {}

USUARIOS_OFICIAIS = {
    "caio": {"nome": "Caio (admin)", "perfil": "ADMIN", "senha": "admin123"},
    "operador1": {"nome": "Operador 1", "perfil": "OPERADOR", "senha": "operador123"},
    "operador2": {"nome": "Operador 2", "perfil": "OPERADOR", "senha": "operador123"},
    "operador3": {"nome": "Operador 3", "perfil": "OPERADOR", "senha": "operador123"},
}


def sincronizar_usuarios_banco():
    """Garante que todos os usuários oficiais estejam cadastrados com hash seguro no Banco de Dados."""
    try:
        with SessionLocal() as db:
            for login_user, dados in USUARIOS_OFICIAIS.items():
                user = db.query(Usuario).filter(Usuario.login == login_user).first()
                h, s = gerar_hash_senha(dados["senha"])
                if not user:
                    user = Usuario(
                        login=login_user,
                        nome=dados["nome"],
                        perfil=dados["perfil"],
                        salt=s,
                        senha_hash=h
                    )
                    db.add(user)
                else:
                    # Atualiza hash de senha caso tenha sido alterada
                    user.nome = dados["nome"]
                    user.perfil = dados["perfil"]
                    user.salt = s
                    user.senha_hash = h
            db.commit()
    except Exception as e:
        print("Erro ao sincronizar usuarios no banco:", e)


@app.on_event("startup")
def startup_event():
    sincronizar_usuarios_banco()


@app.post("/api/auth/login")
def login_usuario(body: dict, db: Session = Depends(get_db)):
    login = (body.get("usuario") or "").strip().lower()
    senha = (body.get("senha") or "").strip()

    if not login or not senha:
        raise HTTPException(status_code=400, detail="Usuário e senha são obrigatórios.")

    if login == "admin":
        login = "caio"

    user = db.query(Usuario).filter(Usuario.login == login).first()
    
    # Se ainda não estiver no banco, tenta os usuários oficiais padrão
    if not user and login in USUARIOS_OFICIAIS:
        sincronizar_usuarios_banco()
        user = db.query(Usuario).filter(Usuario.login == login).first()

    if user and login in USUARIOS_OFICIAIS:
        # Se a senha informada não conferir com o hash salvo no banco, mas for a oficial, atualiza
        if not verificar_hash_senha(senha, user.salt, user.senha_hash):
            if senha == USUARIOS_OFICIAIS[login]["senha"]:
                h_novo, s_novo = gerar_hash_senha(senha)
                user.salt = s_novo
                user.senha_hash = h_novo
                db.commit()

    if not user or not verificar_hash_senha(senha, user.salt, user.senha_hash):
        nome_exib = user.nome if user else login
        raise HTTPException(
            status_code=401,
            detail=f"Senha incorreta para {nome_exib}! Verifique sua senha e tente novamente."
        )

    user.ultimo_login = datetime.now()
    token_sessao = secrets.token_hex(24)
    expira_em = datetime.now() + timedelta(days=7)

    SESSAO_CACHE[token_sessao] = {
        "usuario": user.login,
        "expira_em": expira_em
    }

    try:
        sessao_db = SessaoAtiva(
            token=token_sessao,
            usuario_login=user.login,
            expira_em=expira_em
        )
        db.add(sessao_db)
        db.commit()
    except Exception as e:
        db.rollback()
        print("Aviso ao persistir sessao ativa:", e)

    return {
        "status": "ok",
        "token": token_sessao,
        "usuario": {
            "login": user.login,
            "nome": user.nome,
            "perfil": user.perfil
        }
    }


@app.get("/api/auth/usuarios")
def listar_usuarios_publicos(db: Session = Depends(get_db)):
    """Retorna os perfis públicos disponíveis (SEM NENHUMA SENHA NEM HASH)."""
    users = db.query(Usuario).all()
    if not users:
        sincronizar_usuarios_banco()
        users = db.query(Usuario).all()
    return [
        {"login": u.login, "nome": u.nome, "perfil": u.perfil}
        for u in users
    ]


def autenticacao_obrigatoria(
    authorization: str | None = Header(None),
    x_auth_token: str | None = Header(None),
    x_gatekeeper_key: str | None = Header(None),
    chave: str | None = Query(None),
    db: Session = Depends(get_db)
) -> dict:
    agora = datetime.now()

    # 1. Validação por token de sessão (Bearer ou X-Auth-Token)
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    elif x_auth_token:
        token = x_auth_token.strip()

    if token:
        # Cache em memória (alta performance para requisições de 5s)
        cached = SESSAO_CACHE.get(token)
        if cached and cached.get("expira_em") and cached["expira_em"] > agora:
            return {"tipo": "token", "usuario": cached["usuario"]}

        # Banco de dados
        try:
            sessao_db = db.query(SessaoAtiva).filter(SessaoAtiva.token == token).first()
            if sessao_db and sessao_db.expira_em and sessao_db.expira_em > agora:
                SESSAO_CACHE[token] = {
                    "usuario": sessao_db.usuario_login,
                    "expira_em": sessao_db.expira_em
                }
                return {"tipo": "token", "usuario": sessao_db.usuario_login}
        except Exception as e:
            print("Erro ao verificar token no banco:", e)

    # 2. Validação por chave do Gatekeeper (Header X-Gatekeeper-Key ou Query Param ?chave=)
    chave_enviada = (x_gatekeeper_key or chave or "").strip().lower()
    if chave_enviada and chave_enviada in CHAVES_SECRETAS_VALIDAS:
        return {"tipo": "gatekeeper", "chave": chave_enviada}

    raise HTTPException(
        status_code=401,
        detail="Acesso não autorizado. É necessário fornecer um token de sessão válido ou a chave secreta autorizada do SGA."
    )


ORIGENS_PERMITIDAS = [
    "http://localhost:8000",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:3000",
    "http://127.0.0.1:5500",
    "http://localhost",
    "http://127.0.0.1",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGENS_PERMITIDAS,
    allow_origin_regex=r"^(https://.*\.onrender\.com|http://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+)(:\d+)?)$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_no_cache_headers_for_frontend(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path in ["/", "/index.html", "/sw.js", "/manifest.json"] or path.endswith(".html"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response
ZONA_SUCATA = "FERRAGENS e SUCATAS"


def f(x):
    return float(x) if x is not None else None


def _material_dict(m: Material):
    return {"id": m.id, "codigo": m.codigo, "descricao": m.descricao, "zona": m.zona,
            "unidade": m.unidade, "quantidade": f(m.quantidade)}


def _mov_dict(mv: Movimentacao):
    return {"id": mv.id, "tipo": mv.tipo, "codigo": mv.material.codigo, "descricao": mv.material.descricao,
            "quantidade": f(mv.quantidade), "incidencia": mv.incidencia, "documento": mv.documento,
            "responsavel": mv.responsavel, "local_obra": mv.local_obra, "observacao": mv.observacao,
            "data_hora": mv.data_hora.isoformat(sep=" ", timespec="seconds"),
            "sentido": "SAIDA" if mv.tipo == "SAIDA" else "ENTRADA"}


def _ficha_dict(fi: Ficha):
    return {"id": fi.id, "numero_documento": fi.numero_documento, "solicitante": fi.solicitante,
            "lead_equipe": fi.lead_equipe, "local_obra": fi.local_obra, "incidencia": fi.incidencia,
            "status": fi.status, "token_qr": fi.token_qr,
            "criado_em": fi.criado_em.isoformat(sep=" ", timespec="seconds"),
            "baixado_em": fi.baixado_em.isoformat(sep=" ", timespec="seconds") if fi.baixado_em else None,
            "itens": [{"id": i.id, "codigo": i.material.codigo, "descricao": i.material.descricao,
                       "unidade": i.material.unidade, "quantidade": f(i.quantidade),
                       "qtd_devolvida": f(i.qtd_devolvida), "acrescimo": i.acrescimo,
                       "estoque_atual": f(i.material.quantidade)} for i in fi.itens]}


def _get_material(db: Session, codigo: str) -> Material:
    m = db.query(Material).filter(Material.codigo == codigo.strip()).first()
    if not m:
        raise HTTPException(404, f"Material {codigo} não encontrado no catálogo")
    return m


def _get_ficha(db: Session, ficha_id: int) -> Ficha:
    fi = db.get(Ficha, ficha_id)
    if not fi:
        raise HTTPException(404, "Ficha não encontrada")
    return fi


def _add_itens(db: Session, ficha: Ficha, itens: list[schemas.ItemIn], acrescimo: bool):
    for it in itens:
        m = _get_material(db, it.codigo)
        ficha.itens.append(FichaItem(material=m, quantidade=it.quantidade, acrescimo=acrescimo))


def _mov(db, m, tipo, qtd, ficha: Ficha | None = None, **kw):
    db.add(Movimentacao(material_id=m.id, ficha_id=ficha.id if ficha else None, tipo=tipo, quantidade=qtd,
                        incidencia=ficha.incidencia if ficha else None,
                        documento=ficha.numero_documento if ficha else None,
                        local_obra=ficha.local_obra if ficha else None, **kw))


# ------------------------------------------------------------------ Metadados
@app.get("/api/metadados")
def metadados():
    return {"zonas": ZONAS, "incidencias": INCIDENCIAS}


# ------------------------------------------------------------------ Materiais
@app.get("/api/materiais")
def listar_materiais(zona: str | None = None, q: str | None = None, limite: int = 500,
                     db: Session = Depends(get_db)):
    qs = db.query(Material).filter(Material.ativo.is_(True))
    if zona:
        qs = qs.filter(Material.zona == zona)
    if q:
        like = f"%{q.strip()}%"
        qs = qs.filter(or_(Material.codigo.like(like), Material.descricao.like(like)))
    return [_material_dict(m) for m in qs.order_by(Material.codigo).limit(limite)]


@app.post("/api/materiais", status_code=201)
def criar_material(body: schemas.MaterialIn, db: Session = Depends(get_db)):
    if db.query(Material).filter(Material.codigo == body.codigo.strip()).first():
        raise HTTPException(409, "Código já cadastrado")
    m = Material(codigo=body.codigo.strip(), descricao=body.descricao, zona=body.zona,
                 unidade=body.unidade, quantidade=body.quantidade)
    db.add(m)
    db.flush()
    if body.quantidade > 0:
        _mov(db, m, "ENTRADA", body.quantidade, observacao="Cadastro inicial")
    db.commit()
    return _material_dict(m)


@app.get("/api/materiais/{codigo}/perfil")
def perfil_material(codigo: str, dias: int = Query(90, ge=1, le=3650), db: Session = Depends(get_db)):
    m = _get_material(db, codigo)
    desde = datetime.now() - timedelta(days=dias)
    movs = db.query(Movimentacao).filter(Movimentacao.material_id == m.id)
    saidas = movs.filter(Movimentacao.tipo == "SAIDA")
    ultima = saidas.order_by(Movimentacao.data_hora.desc()).first()

    def soma(tipos):
        return db.query(func.coalesce(func.sum(Movimentacao.quantidade), 0)).filter(
            Movimentacao.material_id == m.id, Movimentacao.tipo.in_(tipos),
            Movimentacao.data_hora >= desde).scalar()

    bruto = Decimal(soma(["SAIDA"]))
    liquido = bruto - Decimal(soma(["ESTORNO", "DEVOLUCAO", "SUCATA"]))  # consumo efetivo
    n_saidas = saidas.filter(Movimentacao.data_hora >= desde).count()
    por_inc = db.query(Movimentacao.incidencia, func.sum(Movimentacao.quantidade)).filter(
        Movimentacao.material_id == m.id, Movimentacao.tipo == "SAIDA", Movimentacao.data_hora >= desde
    ).group_by(Movimentacao.incidencia).all()
    recentes = movs.order_by(Movimentacao.data_hora.desc(), Movimentacao.id.desc()).limit(20).all()
    return {
        "material": _material_dict(m), "periodo_dias": dias,
        "ultima_saida": ultima.data_hora.isoformat(sep=" ", timespec="seconds") if ultima else None,
        "total_saidas_periodo": f(bruto), "consumo_liquido_periodo": f(liquido), "numero_saidas": n_saidas,
        "media_diaria": round(f(liquido) / dias, 3),
        "media_mensal": round(f(liquido) / dias * 30, 2),
        "media_por_saida": round(f(bruto) / n_saidas, 2) if n_saidas else 0,
        "por_incidencia": {i or "-": f(q) for i, q in por_inc},
        "historico_recente": [_mov_dict(x) for x in recentes],
    }


# ------------------------------------------------------------------ Fichas
@app.post("/api/fichas", status_code=201)
def criar_ficha(body: schemas.FichaIn, db: Session = Depends(get_db)):
    if db.query(Ficha).filter(Ficha.numero_documento == body.numero_documento.strip()).first():
        raise HTTPException(409, "Número de documento já utilizado")
    fi = Ficha(numero_documento=body.numero_documento.strip(), solicitante=body.solicitante,
               lead_equipe=body.lead_equipe, local_obra=body.local_obra, incidencia=body.incidencia,
               token_qr=secrets.token_urlsafe(24))
    _add_itens(db, fi, body.itens, acrescimo=False)
    db.add(fi)
    db.commit()
    return _ficha_dict(fi)


@app.get("/api/fichas")
def listar_fichas(status: str | None = None, db: Session = Depends(get_db)):
    qs = db.query(Ficha)
    if status:
        qs = qs.filter(Ficha.status == status)
    return [_ficha_dict(x) for x in qs.order_by(Ficha.criado_em.desc()).limit(100)]


@app.get("/api/fichas/token/{token}")
def ficha_por_token(token: str, db: Session = Depends(get_db)):
    fi = db.query(Ficha).filter(Ficha.token_qr == token).first()
    if not fi:
        raise HTTPException(404, "QR Code inválido")
    return _ficha_dict(fi)


@app.get("/api/fichas/{ficha_id}")
def obter_ficha(ficha_id: int, db: Session = Depends(get_db)):
    return _ficha_dict(_get_ficha(db, ficha_id))


@app.get("/api/fichas/{ficha_id}/qrcode")
def qrcode_ficha(ficha_id: int, db: Session = Depends(get_db)):
    fi = _get_ficha(db, ficha_id)
    img = qrcode.make(f"{BASE_URL}/?confirmar={fi.token_qr}", box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(buf.getvalue(), media_type="image/png")


@app.post("/api/fichas/{ficha_id}/acrescimo")
def acrescimo(ficha_id: int, body: schemas.AcrescimoIn, db: Session = Depends(get_db)):
    fi = _get_ficha(db, ficha_id)
    if fi.status != "EM_SEPARACAO":
        raise HTTPException(409, "Só é possível acrescentar materiais em fichas em separação")
    _add_itens(db, fi, body.itens, acrescimo=True)
    db.commit()
    return _ficha_dict(fi)


def _baixar(db: Session, fi: Ficha):
    if fi.status != "EM_SEPARACAO":
        raise HTTPException(409, f"Ficha já está {fi.status}; baixa não pode ser repetida")
    faltas = []
    totais: dict[int, Decimal] = {}
    for it in fi.itens:
        totais[it.material_id] = totais.get(it.material_id, Decimal(0)) + it.quantidade
    for it in fi.itens:
        if it.material.quantidade < totais[it.material_id]:
            faltas.append(f"{it.material.codigo}: estoque {it.material.quantidade}, pedido {totais[it.material_id]}")
    if faltas:
        raise HTTPException(409, "Estoque insuficiente - " + "; ".join(sorted(set(faltas))))
    agora = datetime.now()
    for it in fi.itens:
        it.material.quantidade -= it.quantidade
        _mov(db, it.material, "SAIDA", it.quantidade, fi, responsavel=fi.solicitante, data_hora=agora,
             observacao=f"LEAD: {fi.lead_equipe}" + (" (acréscimo)" if it.acrescimo else ""))
    fi.status, fi.baixado_em = "BAIXADA", agora
    db.commit()
    return _ficha_dict(fi)


@app.post("/api/fichas/{ficha_id}/baixa")
def baixa_ficha(ficha_id: int, db: Session = Depends(get_db)):
    return _baixar(db, _get_ficha(db, ficha_id))


@app.post("/api/fichas/token/{token}/baixa")
def baixa_por_qr(token: str, db: Session = Depends(get_db)):
    fi = db.query(Ficha).filter(Ficha.token_qr == token).first()
    if not fi:
        raise HTTPException(404, "QR Code inválido")
    return _baixar(db, fi)


@app.post("/api/fichas/{ficha_id}/estorno")
def estorno(ficha_id: int, body: schemas.EstornoIn | None = None, db: Session = Depends(get_db)):
    """Desfaz a saída: devolve ao estoque o saldo não devolvido. Em separação, apenas cancela."""
    fi = _get_ficha(db, ficha_id)
    if fi.status == "ESTORNADA":
        raise HTTPException(409, "Ficha já estornada")
    if fi.status == "BAIXADA":
        for it in fi.itens:
            resto = it.quantidade - it.qtd_devolvida
            if resto > 0:
                it.material.quantidade += resto
                it.qtd_devolvida = it.quantidade
                _mov(db, it.material, "ESTORNO", resto, fi, responsavel=fi.solicitante,
                     observacao=(body.observacao if body else None) or "Estorno de saída")
    fi.status = "ESTORNADA"
    db.commit()
    return _ficha_dict(fi)


# ------------------------------------------------------------------ Devoluções / Sucatas
@app.post("/api/devolucoes", status_code=201)
def devolver(body: schemas.DevolucaoIn, db: Session = Depends(get_db)):
    fi = db.query(Ficha).filter(Ficha.numero_documento == body.numero_documento.strip()).first()
    if not fi:
        raise HTTPException(404, "Ficha não encontrada")
    if fi.status != "BAIXADA":
        raise HTTPException(409, "Só é possível devolver material de ficha baixada")
    it = next((i for i in fi.itens if i.material.codigo == body.codigo.strip()), None)
    if not it:
        raise HTTPException(404, "Código não pertence a esta ficha")
    # soma de todas as linhas do mesmo código (itens + acréscimos)
    linhas = [i for i in fi.itens if i.material_id == it.material_id]
    disponivel = sum((i.quantidade - i.qtd_devolvida for i in linhas), Decimal(0))
    if body.quantidade > disponivel:
        raise HTTPException(409, f"Quantidade excede o saldo devolvível ({disponivel})")
    restante = body.quantidade
    for i in linhas:
        take = min(restante, i.quantidade - i.qtd_devolvida)
        i.qtd_devolvida += take
        restante -= take
    if body.destino == "DEVOLUCAO":
        it.material.quantidade += body.quantidade  # volta ao estoque utilizável
    # SUCATA: material retirado de serviço - registrado, sem retornar ao saldo utilizável
    _mov(db, it.material, body.destino, body.quantidade, fi,
         responsavel=body.responsavel or fi.solicitante, observacao=body.observacao)
    db.commit()
    return _ficha_dict(fi)


@app.get("/api/sucatas-devolucoes")
def sucatas_devolucoes(dias: int = Query(30, ge=1, le=3650), db: Session = Depends(get_db)):
    desde = datetime.now() - timedelta(days=dias)
    movs = (db.query(Movimentacao).join(Material)
            .filter(Movimentacao.data_hora >= desde)
            .filter(or_(Movimentacao.tipo.in_(["DEVOLUCAO", "SUCATA", "ESTORNO"]),
                     (Material.zona == ZONA_SUCATA) & Movimentacao.tipo.notin_(["ENTRADA", "AJUSTE"])))
            .order_by(Movimentacao.data_hora.desc(), Movimentacao.id.desc()).limit(300).all())
    rows = [_mov_dict(x) for x in movs]
    ent = sum(r["quantidade"] for r in rows if r["sentido"] == "ENTRADA")
    sai = sum(r["quantidade"] for r in rows if r["sentido"] == "SAIDA")
    return {"periodo_dias": dias, "total_entradas": ent, "total_saidas": sai, "movimentos": rows}


# ------------------------------------------------------------------ Relatórios
@app.get("/api/relatorios/saidas")
def relatorio_saidas(codigos: str = "", dias: int = Query(30, ge=1, le=3650), db: Session = Depends(get_db)):
    lista = [c.strip() for c in codigos.split(",") if c.strip()]
    desde = datetime.now() - timedelta(days=dias)
    qs = (db.query(Movimentacao).join(Material)
          .filter(Movimentacao.tipo == "SAIDA", Movimentacao.data_hora >= desde))
    if lista:
        qs = qs.filter(Material.codigo.in_(lista))
    rows = [_mov_dict(x) for x in qs.order_by(Movimentacao.data_hora.desc()).limit(2000)]
    return {"gerado_em": datetime.now().isoformat(sep=" ", timespec="seconds"), "periodo_dias": dias,
            "codigos": lista, "linhas": rows}


# ------------------------------------------------------------------ Catálogo MB
@app.post("/api/catalogo/importar")
async def importar_catalogo(arquivo: UploadFile = File(...), atualizar_estoque: bool = False,
                            db: Session = Depends(get_db)):
    try:
        return importar_mb(db, arquivo.filename or "mb.xlsx", await arquivo.read(), atualizar_estoque)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.get("/api/catalogo/importacoes")
def historico_importacoes(db: Session = Depends(get_db)):
    return [{"arquivo": i.arquivo, "inseridos": i.inseridos, "atualizados": i.atualizados,
             "ignorados": i.ignorados, "data_hora": i.data_hora.isoformat(sep=" ", timespec="seconds")}
            for i in db.query(ImportacaoCatalogo).order_by(ImportacaoCatalogo.id.desc()).limit(10)]


# ------------------------------------------------------------------ Sincronização de Estado Central (Multi-dispositivos / Rede)
ESTADO_FILE = Path(__file__).resolve().parents[2] / "database" / "estado_sga.json"
BACKUP_DIR = Path(__file__).resolve().parents[2] / "database" / "backups"
TRANSACOES_LOG = Path(__file__).resolve().parents[2] / "database" / "historico_transacoes.jsonl"


@app.get("/api/sync/estado")
def obter_estado_central(auth: dict = Depends(autenticacao_obrigatoria), db: Session = Depends(get_db)):
    # 1. Tenta carregar do Banco de Dados (PostgreSQL / SQLite)
    try:
        reg_db = db.query(EstadoCentralDB).filter(EstadoCentralDB.id == 1).first()
        if reg_db and reg_db.dados_json:
            return json.loads(reg_db.dados_json)
    except Exception:
        pass

    # 2. Fallback para arquivo local
    if ESTADO_FILE.exists():
        try:
            with open(ESTADO_FILE, "r", encoding="utf-8") as f:
                dados = json.load(f)
                # Sincroniza com o Banco de Dados
                try:
                    reg_novo = EstadoCentralDB(id=1, dados_json=json.dumps(dados, ensure_ascii=False))
                    db.merge(reg_novo)
                    db.commit()
                except Exception:
                    pass
                return dados
        except Exception:
            pass
    return None


@app.post("/api/sync/estado")
def salvar_estado_central(body: dict, auth: dict = Depends(autenticacao_obrigatoria), db: Session = Depends(get_db)):
    ESTADO_FILE.parent.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Carrega estado existente para proteção de integridade (do Banco ou Arquivo)
    estado_anterior = {}
    try:
        reg_db = db.query(EstadoCentralDB).filter(EstadoCentralDB.id == 1).first()
        if reg_db and reg_db.dados_json:
            estado_anterior = json.loads(reg_db.dados_json)
    except Exception:
        pass

    if not estado_anterior and ESTADO_FILE.exists():
        try:
            with open(ESTADO_FILE, "r", encoding="utf-8") as f:
                estado_anterior = json.load(f)
        except Exception:
            pass

    # 2. Proteção contra perda acidental de fichas de saída
    novas_fichas = body.get("fichas", [])
    if not isinstance(novas_fichas, list):
        novas_fichas = []

    fichas_anteriores = estado_anterior.get("fichas", [])
    if not isinstance(fichas_anteriores, list):
        fichas_anteriores = []

    # Exclusão explícita de ficha por ID ou documento
    id_excluir = body.get("excluir_ficha_id")
    if id_excluir:
        fichas_anteriores = [f for f in fichas_anteriores if str(f.get("id")) != str(id_excluir)]
        novas_fichas = [f for f in novas_fichas if str(f.get("id")) != str(id_excluir)]

    doc_excluir = body.get("excluir_ficha_doc")
    if doc_excluir and not id_excluir:
        fichas_anteriores = [f for f in fichas_anteriores if f.get("documento") != doc_excluir]
        novas_fichas = [f for f in novas_fichas if f.get("documento") != doc_excluir]

    # Se novas_fichas for vazio e existiam fichas anteriores e não é reset explícito, preserva para não zerar
    if not novas_fichas and fichas_anteriores and not body.get("forcar_limpeza_fichas"):
        novas_fichas = fichas_anteriores
    elif fichas_anteriores and novas_fichas and not (doc_excluir or id_excluir):
        # Mesclagem segura por ID único para permitir fichas estornadas e refeitas com o mesmo documento
        mapa_fichas = {}
        for f in fichas_anteriores:
            chave = str(f.get("id")) if f.get("id") else f"{f.get('documento')}_{f.get('status')}"
            mapa_fichas[chave] = f
        for f in novas_fichas:
            chave = str(f.get("id")) if f.get("id") else f"{f.get('documento')}_{f.get('status')}"
            mapa_fichas[chave] = f
        novas_fichas = list(mapa_fichas.values())

    body["fichas"] = novas_fichas

    # 3. Mesclagem e proteção de historicoMovimentacoes (nunca perde entradas de outros operadores)
    novos_movs = body.get("historicoMovimentacoes", [])
    if not isinstance(novos_movs, list):
        novos_movs = []

    movs_anteriores = estado_anterior.get("historicoMovimentacoes", [])
    if not isinstance(movs_anteriores, list):
        movs_anteriores = []

    # Expurgar definitivamente qualquer registro provisório ou teste de sucata (15kg / RENO260730)
    def eh_movimento_valido(m):
        if not isinstance(m, dict):
            return False
        if m.get("id") == "SUC-1792842000000-RENO":
            return False
        doc = str(m.get("documento") or "").upper()
        if "260730" in doc:
            return False
        if str(m.get("qtd")) == "15" and ("260730" in doc or "RENO" in str(m.get("descricao") or "").upper()):
            return False
        if "teste" in str(m.get("motivo") or "").lower():
            return False
        # Expurgar registros duplicados/fantasmas da baixa 23910587 sem ID ou com timestamp duplicado
        if doc == "23910587":
            dh = str(m.get("dataHora") or "")
            if not m.get("id") or "11:03:11" in dh:
                return False
        # Correção da entrada de sucata 111736 na incidência 42319039 (excluir 2 unidades: de 3 para 1)
        if m.get("id") == "SUC-1793184124766-12141-111736" or (str(m.get("codigo")) == "111736" and doc == "42319039"):
            m["qtd"] = 1
        return True

    movs_anteriores = [m for m in movs_anteriores if eh_movimento_valido(m)]
    novos_movs = [m for m in novos_movs if eh_movimento_valido(m)]

    id_excluir_mov = body.get("excluir_mov_id")
    if id_excluir_mov:
        movs_anteriores = [m for m in movs_anteriores if str(m.get("id")) != str(id_excluir_mov)]
        novos_movs = [m for m in novos_movs if str(m.get("id")) != str(id_excluir_mov)]

    # Deduplicação canônica universal de movimentações
    def _gerar_chave_canonica_mov(m):
        doc = str(m.get("documento") or "").strip().upper()
        cod = str(m.get("codigo") or "").strip()
        tipo = str(m.get("tipo") or "").strip().upper()
        qtd = str(m.get("qtd") or "").strip()
        dh = str(m.get("dataHora") or "").strip()[:16]  # até o minuto
        return f"{doc}_{cod}_{tipo}_{qtd}_{dh}"

    # IDs de estornos/saídas canceladas obsoletas que não devem ser reinseridas
    ids_expurgo_estornos = {
        "mov_12_1792841976_780655", "mov_6_1792841976_780655",
        "mov_13_1792841976_310632", "mov_7_1792841976_310632",
        "mov_14_1792841976_251841", "mov_8_1792841976_251841",
        "mov_15_1792841976_240116", "mov_9_1792841976_240116",
        "mov_16_1792841976_170074", "mov_10_1792841976_170074",
    }

    # Flag para forçar substituição direta quando necessário
    if body.get("forcar_substituicao_movimentacoes"):
        movs_finais = [m for m in novos_movs if str(m.get("id")) not in ids_expurgo_estornos]
    else:
        mapa_movs = {}
        todos_movs = movs_anteriores + novos_movs
        for m in todos_movs:
            if not m:
                continue
            mid = str(m.get("id") or "")
            if mid in ids_expurgo_estornos:
                continue
            ck = _gerar_chave_canonica_mov(m)
            if ck in mapa_movs:
                if not mapa_movs[ck].get("id") and m.get("id"):
                    mapa_movs[ck] = m
            else:
                mapa_movs[ck] = m
        movs_finais = list(mapa_movs.values())

    body["historicoMovimentacoes"] = movs_finais

    # Atualização de saldo de materiais e integridade operacional
    # Salva diretamente a lista de materiais atualizada enviada pelo cliente, respeitando todas as baixas e devoluções.
    if body.get("materiais"):
        pass

    # Log transacional em arquivo append-only (NUNCA sobrescrito)
    if movs_finais:
        try:
            with open(TRANSACOES_LOG, "a", encoding="utf-8") as tf:
                for m in movs_finais[:5]:
                    tf.write(json.dumps(m, ensure_ascii=False) + "\n")
        except Exception:
            pass

    # 4. Grava o estado oficial no Arquivo e no Banco de Dados com timestamp
    body["timestamp"] = int(time.time() * 1000)
    estado_json_str = json.dumps(body, ensure_ascii=False, indent=2)
    with open(ESTADO_FILE, "w", encoding="utf-8") as f:
        f.write(estado_json_str)

    try:
        reg_db = EstadoCentralDB(id=1, dados_json=estado_json_str, atualizado_em=datetime.now())
        db.merge(reg_db)
        db.commit()
    except Exception as e:
        print("Erro ao persistir estado no banco:", e)

    return {"status": "ok", "mensagem": "Estado sincronizado com sucesso", "total_fichas": len(novas_fichas)}
# ------------------------------------------------------------------ Frontend estático
FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")