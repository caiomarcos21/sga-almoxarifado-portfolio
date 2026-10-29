@echo off
title SGA Eletrico - Almoxarifado Enel Tiangua
color 0A
cls
echo ========================================================================
echo        SGA ELETRICO - GESTAO DE ALMOXARIFADO ENEL TIANGUA / MRO
echo ========================================================================
echo.
echo  Iniciando servidor central de rede local...
echo.

cd /d "%~dp0backend"
if not exist .venv (
    echo  Criando ambiente virtual Python...
    python -m venv .venv
)
call .venv\Scripts\activate
pip install -q -r requirements.txt

echo.
echo ========================================================================
echo   SERVIDOR ATIVO NA REDE LOCAL (MULTI-DISPOSITIVOS)!
echo ========================================================================
echo   [1] Acesso neste computador:    http://localhost:8000
echo   [2] Acesso por outros PCs:      http://192.168.0.8:8000
echo   [3] Acesso pelo CELULAR/TABLET: http://192.168.0.8:8000
echo.
echo   * Conecte o celular no mesmo Wi-Fi e abra o link acima no navegador.
echo   * Usuarios pre-configurados:
echo       - Almoxarife (Admin):  admin    / senha: enel2026
echo       - Operador de Campo:   operador / senha: 1234
echo ========================================================================
echo.
start "" http://localhost:8000
uvicorn app.main:app --host 0.0.0.0 --port 8000
pause
