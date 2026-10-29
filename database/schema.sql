-- =====================================================================
-- Almoxarifado de Equipamentos Elétricos - Microsoft SQL Server
-- =====================================================================
IF DB_ID('almoxarifado') IS NULL CREATE DATABASE almoxarifado;
GO
USE almoxarifado;
GO

-- ---------- Tabelas de domínio ----------
CREATE TABLE zona (
    id    INT IDENTITY PRIMARY KEY,
    nome  NVARCHAR(60) NOT NULL UNIQUE
);
INSERT INTO zona (nome) VALUES
 (N'EPI/EPC e ferramental'), (N'POSTES E CRUZETAS'), (N'CABOS e FIOS'), (N'FERRAGENS e SUCATAS');

CREATE TABLE incidencia (
    codigo VARCHAR(20) PRIMARY KEY
);
INSERT INTO incidencia (codigo) VALUES
 ('BA'),('OT'),('SOB'),('INCIDÊNCIA'),('ANE'),('DT'),('SGD'),('SGM'),('RENO');

-- ---------- Materiais (catálogo - sincronizado com o relatório MB) ----------
CREATE TABLE material (
    id          INT IDENTITY PRIMARY KEY,
    codigo      VARCHAR(40)   NOT NULL UNIQUE,      -- chave de negócio (upsert do MB)
    descricao   NVARCHAR(300) NOT NULL,
    zona_id     INT           NOT NULL REFERENCES zona(id),
    unidade     VARCHAR(10)   NOT NULL DEFAULT 'UN',
    quantidade  DECIMAL(14,3) NOT NULL DEFAULT 0 CONSTRAINT ck_material_qtd CHECK (quantidade >= 0),
    ativo       BIT           NOT NULL DEFAULT 1,
    criado_em   DATETIME2     NOT NULL DEFAULT SYSDATETIME(),
    atualizado_em DATETIME2   NOT NULL DEFAULT SYSDATETIME()
);
CREATE INDEX ix_material_zona ON material(zona_id);

-- ---------- Fichas de serviço (saída) ----------
CREATE TABLE ficha (
    id               INT IDENTITY PRIMARY KEY,
    numero_documento VARCHAR(40)  NOT NULL UNIQUE,   -- número único do serviço
    solicitante      NVARCHAR(120) NOT NULL,
    lead_equipe      NVARCHAR(120) NOT NULL,
    local_obra       NVARCHAR(200) NOT NULL,
    incidencia       VARCHAR(20)  NOT NULL REFERENCES incidencia(codigo),
    status           VARCHAR(20)  NOT NULL DEFAULT 'EM_SEPARACAO'
        CONSTRAINT ck_ficha_status CHECK (status IN ('EM_SEPARACAO','BAIXADA','ESTORNADA')),
    token_qr         VARCHAR(64)  NOT NULL UNIQUE,   -- conteúdo único do QR Code
    criado_em        DATETIME2    NOT NULL DEFAULT SYSDATETIME(),
    baixado_em       DATETIME2    NULL
);

CREATE TABLE ficha_item (
    id            INT IDENTITY PRIMARY KEY,
    ficha_id      INT NOT NULL REFERENCES ficha(id),
    material_id   INT NOT NULL REFERENCES material(id),
    quantidade    DECIMAL(14,3) NOT NULL CHECK (quantidade > 0),
    qtd_devolvida DECIMAL(14,3) NOT NULL DEFAULT 0,
    acrescimo     BIT NOT NULL DEFAULT 0,            -- item incluído após a criação da ficha
    adicionado_em DATETIME2 NOT NULL DEFAULT SYSDATETIME()
);
CREATE INDEX ix_ficha_item_ficha ON ficha_item(ficha_id);

-- ---------- Livro de movimentações (histórico imutável) ----------
-- Referência por material_id: o upsert do MB nunca apaga materiais,
-- portanto o histórico permanece intacto.
CREATE TABLE movimentacao (
    id           BIGINT IDENTITY PRIMARY KEY,
    material_id  INT NOT NULL REFERENCES material(id),
    ficha_id     INT NULL REFERENCES ficha(id),
    tipo         VARCHAR(20) NOT NULL
        CONSTRAINT ck_mov_tipo CHECK (tipo IN ('SAIDA','ESTORNO','DEVOLUCAO','SUCATA','ENTRADA','AJUSTE')),
    quantidade   DECIMAL(14,3) NOT NULL CHECK (quantidade > 0),
    incidencia   VARCHAR(20) NULL REFERENCES incidencia(codigo),
    documento    VARCHAR(40) NULL,
    responsavel  NVARCHAR(120) NULL,
    local_obra   NVARCHAR(200) NULL,
    observacao   NVARCHAR(300) NULL,
    data_hora    DATETIME2 NOT NULL DEFAULT SYSDATETIME()
);
CREATE INDEX ix_mov_material_data ON movimentacao(material_id, data_hora DESC);
CREATE INDEX ix_mov_tipo_data     ON movimentacao(tipo, data_hora DESC);

-- ---------- Auditoria das importações do MB ----------
CREATE TABLE importacao_catalogo (
    id           INT IDENTITY PRIMARY KEY,
    arquivo      NVARCHAR(260) NOT NULL,
    inseridos    INT NOT NULL,
    atualizados  INT NOT NULL,
    ignorados    INT NOT NULL,
    data_hora    DATETIME2 NOT NULL DEFAULT SYSDATETIME()
);
GO
