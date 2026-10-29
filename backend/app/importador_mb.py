"""Importação/sincronização do relatório MB (xlsx, xls, csv, txt, pdf) com UPSERT por código.

Garantias:
- Nunca apaga materiais (histórico em `movimentacao`/`ficha_item` referencia material.id).
- Código existente  -> atualiza descrição (e unidade/zona se vierem no arquivo).
- Código novo       -> insere.
- O estoque de itens existentes NÃO é sobrescrito (é controlado pelas movimentações),
  a menos que `atualizar_estoque=True` (inventário/contagem).
"""
import csv
import io
import re
import unicodedata
from html.parser import HTMLParser
from decimal import Decimal, InvalidOperation

from openpyxl import load_workbook
from sqlalchemy.orm import Session

from .models import Material, ImportacaoCatalogo, Movimentacao, ZONAS

ALIASES = {
    "codigo": {
        "codigo", "cod", "codigo material", "material", "sap", "cod material", "cod.", "item",
        "material e4e", "material sie", "codigo a ser utilizado", "material 1"
    },
    "descricao": {
        "descricao", "texto breve", "texto breve material", "texto breve de material", "denominacao",
        "desc", "descricao material", "descricao do material"
    },
    "zona": {"zona", "categoria", "grupo", "familia"},
    "unidade": {
        "unidade", "um", "umb", "umd", "udm", "und", "unid", "un",
        "unidade de medida basica", "unid.medida basica"
    },
    "quantidade": {
        "quantidade", "qtd", "qtde", "estoque", "saldo", "utilizacao livre", "livre utilizacao",
        "estoque livre", "qtd livre", "saldo livre", "quantidade validada"
    },
}

ZONA_KEYWORDS = [
    ("POSTES E CRUZETAS", ("poste", "cruzeta")),
    ("CABOS e FIOS", ("cabo", "fio ", "condutor", "cordoalha")),
    ("EPI/EPC e ferramental", ("epi", "epc", "luva", "capacete", "cinto", "ferramenta", "bota", "talabarte", "perneira", "oculos")),
]


def _norm(txt) -> str:
    s = unicodedata.normalize("NFKD", str(txt or "")).encode("ascii", "ignore").decode()
    return s.strip().lower()


def _codigo(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def _dec(v) -> Decimal:
    try:
        return Decimal(str(v).replace(",", ".")) if v not in (None, "") else Decimal(0)
    except InvalidOperation:
        return Decimal(0)


class _TabelaHTML(HTMLParser):
    """Lê <table> de .xls 'falso' (HTML) exportado pelo SAP."""
    def __init__(self):
        super().__init__()
        self.linhas, self._row, self._cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = ""

    def handle_data(self, data):
        if self._cell is not None:
            self._cell += data

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(self._cell.strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.linhas.append(self._row)
            self._row = None


def _decodificar(conteudo: bytes) -> str:
    if conteudo[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return conteudo.decode("utf-16")
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return conteudo.decode(enc)
        except UnicodeDecodeError:
            pass
    return conteudo.decode("latin-1")


def _mapear_cabecalho(linhas: list[list]):
    for i, row in enumerate(linhas[:50]):
        cols = {}
        for j, cell in enumerate(row):
            n = _norm(cell)
            for campo, nomes in ALIASES.items():
                if n in nomes and campo not in cols:
                    cols[campo] = j
        if "codigo" in cols and "descricao" in cols:
            return i, cols
    return None, None


def _extrair_pdf(conteudo: bytes) -> list[list]:
    import pdfplumber
    linhas = [["Material", "Texto breve material", "Utilização livre"]]
    with pdfplumber.open(io.BytesIO(conteudo)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for line in text.split("\n"):
                line = line.strip()
                if not line or "Texto breve" in line or "Utiliza" in line:
                    continue
                # Formato: [Código] [Descrição ...] [Quantidade]
                m = re.match(r"^([A-Za-z0-9\-_]+)\s+(.+?)\s+([0-9\.,]+)$", line)
                if m:
                    cod, desc, qtd = m.groups()
                    linhas.append([cod, desc, qtd])
                else:
                    m2 = re.match(r"^([A-Za-z0-9\-_]+)\s+(.+)$", line)
                    if m2:
                        linhas.append([m2.group(1), m2.group(2), "0"])
    return linhas


def _ler_linhas_e_cabecalho(nome: str, conteudo: bytes) -> tuple[list[list], int, dict]:
    """
    Detecta formato e busca em todas as abas (se for Excel) até achar a aba
    que contém as colunas de Código e Descrição.
    """
    # 1. PDF
    if conteudo[:4] == b"%PDF" or nome.lower().endswith(".pdf"):
        linhas = _extrair_pdf(conteudo)
        h, cols = _mapear_cabecalho(linhas)
        if h is not None:
            return linhas, h, cols

    # 2. XLSX
    if conteudo[:2] == b"PK":
        wb = load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
        # Prioriza abas que costumam ter os materiais: MB52, Material, Planilha1, etc.
        nomes_abas = sorted(wb.sheetnames, key=lambda s: 0 if any(k in s.lower() for k in ("mb52", "material", "catalogo", "base")) else 1)
        for sname in nomes_abas:
            linhas = [list(r) for r in wb[sname].iter_rows(values_only=True)]
            h, cols = _mapear_cabecalho(linhas)
            if h is not None:
                return linhas, h, cols

    # 3. XLS binário (BIFF)
    if conteudo[:4] == b"\xd0\xcf\x11\xe0":
        import xlrd
        wb = xlrd.open_workbook(file_contents=conteudo)
        nomes_abas = sorted(wb.sheet_names(), key=lambda s: 0 if any(k in s.lower() for k in ("mb52", "material", "catalogo", "base")) else 1)
        for sname in nomes_abas:
            sh = wb.sheet_by_name(sname)
            linhas = [sh.row_values(i) for i in range(sh.nrows)]
            h, cols = _mapear_cabecalho(linhas)
            if h is not None:
                return linhas, h, cols

    # 4. HTML (típico export do SAP disfarçado de .xls)
    texto = _decodificar(conteudo)
    if "<table" in texto[:30000].lower():
        p = _TabelaHTML()
        p.feed(texto)
        h, cols = _mapear_cabecalho(p.linhas)
        if h is not None:
            return p.linhas, h, cols

    # 5. CSV / TXT delimitado
    try:
        dialect = csv.Sniffer().sniff(texto[:4096], delimiters=";,\t|")
    except csv.Error:
        dialect = csv.excel
    linhas = [r for r in csv.reader(io.StringIO(texto), dialect)]
    h, cols = _mapear_cabecalho(linhas)
    if h is not None:
        return linhas, h, cols

    raise ValueError("Cabeçalho não encontrado: o arquivo precisa conter colunas de Código/Material e Descrição/Texto Breve.")


def _inferir_zona(descricao: str) -> str:
    d = _norm(descricao)
    for zona, kws in ZONA_KEYWORDS:
        if any(k in d for k in kws):
            return zona
    return "FERRAGENS e SUCATAS"


def _zona_valida(v) -> str | None:
    n = _norm(v)
    for z in ZONAS:
        if _norm(z) == n:
            return z
    return None


def importar_mb(db: Session, nome: str, conteudo: bytes, atualizar_estoque: bool = False) -> dict:
    linhas, h, cols = _ler_linhas_e_cabecalho(nome, conteudo)
    existentes = {m.codigo: m for m in db.query(Material).all()}
    ins = upd = ign = 0

    # 1ª passada: consolida o arquivo (MB52 repete o material por centro/depósito -> soma a quantidade)
    consolidado: dict[str, dict] = {}
    for row in linhas[h + 1:]:
        get = lambda campo: row[cols[campo]] if campo in cols and cols[campo] < len(row) else None
        codigo, desc = _codigo(get("codigo")), str(get("descricao") or "").strip()
        if not codigo or not desc:
            ign += 1
            continue
        c = consolidado.setdefault(codigo, {"desc": desc, "zona": _zona_valida(get("zona")),
                                            "unidade": str(get("unidade") or "").strip()[:10] or None,
                                            "qtd": Decimal(0)})
        c["qtd"] += _dec(get("quantidade"))

    for codigo, c in consolidado.items():
        desc, zona_arq, unidade = c["desc"], c["zona"], c["unidade"]
        m = existentes.get(codigo)
        if m is None:
            qtd = c["qtd"]
            m = Material(codigo=codigo, descricao=desc[:300], zona=zona_arq or _inferir_zona(desc),
                         unidade=unidade or "UN", quantidade=qtd)
            db.add(m)
            db.flush()
            if qtd > 0:
                db.add(Movimentacao(material_id=m.id, tipo="ENTRADA", quantidade=qtd,
                                    observacao=f"Carga inicial via MB ({nome})"))
            existentes[codigo] = m
            ins += 1
        else:
            m.descricao = desc[:300]
            if zona_arq:
                m.zona = zona_arq
            if unidade:
                m.unidade = unidade
            m.ativo = True
            if atualizar_estoque and "quantidade" in cols:
                delta = c["qtd"] - m.quantidade
                if delta != 0:
                    db.add(Movimentacao(material_id=m.id, tipo="AJUSTE", quantidade=abs(delta),
                                        observacao=f"Ajuste de inventário via MB ({nome})"))
                    m.quantidade = c["qtd"]
            upd += 1

    db.add(ImportacaoCatalogo(arquivo=nome[:260], inseridos=ins, atualizados=upd, ignorados=ign))
    db.commit()
    return {"arquivo": nome, "inseridos": ins, "atualizados": upd, "ignorados": ign}
