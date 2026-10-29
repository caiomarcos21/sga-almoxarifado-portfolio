from datetime import datetime
from decimal import Decimal
from sqlalchemy import ForeignKey, Numeric, String, DateTime, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base

ZONAS = ["EPI/EPC e ferramental", "POSTES E CRUZETAS", "CABOS e FIOS", "FERRAGENS e SUCATAS"]
INCIDENCIAS = ["BA", "OT", "SOB", "INCIDÊNCIA", "ANE", "DT", "SGD", "SGM", "RENO", "TRANSFERENCIA"]


class Material(Base):
    __tablename__ = "material"
    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    descricao: Mapped[str] = mapped_column(String(300))
    zona: Mapped[str] = mapped_column(String(60), index=True)
    unidade: Mapped[str] = mapped_column(String(10), default="UN")
    quantidade: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class Ficha(Base):
    __tablename__ = "ficha"
    id: Mapped[int] = mapped_column(primary_key=True)
    numero_documento: Mapped[str] = mapped_column(String(40), unique=True)
    solicitante: Mapped[str] = mapped_column(String(120))
    lead_equipe: Mapped[str] = mapped_column(String(120))
    local_obra: Mapped[str] = mapped_column(String(200))
    incidencia: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="EM_SEPARACAO")  # EM_SEPARACAO|BAIXADA|ESTORNADA
    token_qr: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    baixado_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    itens: Mapped[list["FichaItem"]] = relationship(back_populates="ficha", cascade="all, delete-orphan")


class FichaItem(Base):
    __tablename__ = "ficha_item"
    id: Mapped[int] = mapped_column(primary_key=True)
    ficha_id: Mapped[int] = mapped_column(ForeignKey("ficha.id"), index=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("material.id"))
    quantidade: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    qtd_devolvida: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0)
    acrescimo: Mapped[bool] = mapped_column(Boolean, default=False)
    adicionado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    ficha: Mapped[Ficha] = relationship(back_populates="itens")
    material: Mapped[Material] = relationship()


class Movimentacao(Base):
    """Livro de movimentações. Nunca é apagado nem alterado pela importação do MB."""
    __tablename__ = "movimentacao"
    id: Mapped[int] = mapped_column(primary_key=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("material.id"), index=True)
    ficha_id: Mapped[int | None] = mapped_column(ForeignKey("ficha.id"), nullable=True)
    tipo: Mapped[str] = mapped_column(String(20), index=True)  # SAIDA|ESTORNO|DEVOLUCAO|SUCATA|ENTRADA
    quantidade: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    incidencia: Mapped[str | None] = mapped_column(String(20), nullable=True)
    documento: Mapped[str | None] = mapped_column(String(40), nullable=True)
    responsavel: Mapped[str | None] = mapped_column(String(120), nullable=True)
    local_obra: Mapped[str | None] = mapped_column(String(200), nullable=True)
    observacao: Mapped[str | None] = mapped_column(String(300), nullable=True)
    data_hora: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    material: Mapped[Material] = relationship()


class ImportacaoCatalogo(Base):
    __tablename__ = "importacao_catalogo"
    id: Mapped[int] = mapped_column(primary_key=True)
    arquivo: Mapped[str] = mapped_column(String(260))
    inseridos: Mapped[int]
    atualizados: Mapped[int]
    ignorados: Mapped[int]
    data_hora: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class SessaoAtiva(Base):
    __tablename__ = "sessao_ativa"
    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    usuario_login: Mapped[str] = mapped_column(String(50), index=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    expira_em: Mapped[datetime] = mapped_column(DateTime)


class Usuario(Base):
    __tablename__ = "usuario"
    id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    nome: Mapped[str] = mapped_column(String(100))
    perfil: Mapped[str] = mapped_column(String(30), default="OPERADOR")  # ADMIN | OPERADOR
    salt: Mapped[str] = mapped_column(String(64))
    senha_hash: Mapped[str] = mapped_column(String(128))
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    ultimo_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class EstadoCentralDB(Base):
    """Persistência resiliente de todo o estado operacional do SGA no Banco de Dados."""
    __tablename__ = "estado_central"
    id: Mapped[int] = mapped_column(primary_key=True)
    dados_json: Mapped[str] = mapped_column(String)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
