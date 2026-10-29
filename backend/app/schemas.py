from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, Field

Incidencia = Literal["BA", "OT", "SOB", "INCIDÊNCIA", "ANE", "DT", "SGD", "SGM", "RENO", "TRANSFERENCIA"]
Zona = Literal["EPI/EPC e ferramental", "POSTES E CRUZETAS", "CABOS e FIOS", "FERRAGENS e SUCATAS"]


class MaterialIn(BaseModel):
    codigo: str = Field(min_length=1, max_length=40)
    descricao: str = Field(min_length=1, max_length=300)
    zona: Zona
    unidade: str = "UN"
    quantidade: Decimal = Field(default=0, ge=0)


class ItemIn(BaseModel):
    codigo: str
    quantidade: Decimal = Field(gt=0)


class FichaIn(BaseModel):
    numero_documento: str = Field(min_length=1, max_length=40)
    solicitante: str = Field(min_length=1)
    lead_equipe: str = Field(min_length=1)
    local_obra: str = Field(min_length=1)
    incidencia: Incidencia
    itens: list[ItemIn] = Field(min_length=1)


class AcrescimoIn(BaseModel):
    itens: list[ItemIn] = Field(min_length=1)


class EstornoIn(BaseModel):
    observacao: str | None = None


class DevolucaoIn(BaseModel):
    numero_documento: str
    codigo: str
    quantidade: Decimal = Field(gt=0)
    destino: Literal["DEVOLUCAO", "SUCATA"] = "DEVOLUCAO"
    responsavel: str | None = None
    observacao: str | None = None
