// Aberto direto do disco (file://) a API não responde: redireciona para o servidor local.
if (location.protocol === 'file:') location.replace('http://localhost:8000');

const $ = (s, r = document) => r.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = n => Number(n ?? 0).toLocaleString('pt-BR', { maximumFractionDigits: 3 });
const fmtData = s => s ? new Date(s.replace(' ', 'T')).toLocaleString('pt-BR') : '—';
const modal = id => bootstrap.Modal.getOrCreateInstance(document.getElementById(id));
const STATUS = { EM_SEPARACAO: ['warning text-dark', 'Em separação'], BAIXADA: ['success', 'Baixada'], ESTORNADA: ['secondary', 'Estornada'] };
const TIPO_COR = { SAIDA: 'danger', ESTORNO: 'info', DEVOLUCAO: 'success', SUCATA: 'dark', ENTRADA: 'primary', AJUSTE: 'secondary' };

let meta = { zonas: [], incidencias: [] };
let zonaAtual = '';
let fichaAcrescimo = null, tokenConfirmar = null;

async function api(url, opts = {}) {
  if (opts.body && !(opts.body instanceof FormData)) {
    opts.headers = { 'Content-Type': 'application/json' };
    opts.body = JSON.stringify(opts.body);
  }
  const r = await fetch('/api' + url, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const d = data.detail;
    throw new Error(Array.isArray(d) ? d.map(e => e.msg).join('; ') : d || 'Erro na requisição');
  }
  return data;
}
function aviso(msg, tipo = 'success') {
  $('#alerta').innerHTML = `<div class="alert alert-${tipo} alert-dismissible"><span>${esc(msg)}</span><button class="btn-close" data-bs-dismiss="alert"></button></div>`;
  window.scrollTo(0, 0);
}
const tratar = fn => async (...a) => { try { await fn(...a); } catch (e) { aviso(e.message, 'danger'); } };

/* ---------- Navegação ---------- */
const carregadores = { estoque: carregarEstoque, fichas: carregarFichas, sucatas: carregarSucatas, catalogo: carregarImportacoes, relatorios: () => {} };
function ir(view) {
  document.querySelectorAll('.view').forEach(v => v.classList.toggle('d-none', v.id !== 'view-' + view));
  document.querySelectorAll('#menu .nav-link').forEach(a => a.classList.toggle('active', a.dataset.view === view));
  tratar(carregadores[view])();
}
$('#menu').addEventListener('click', e => { const a = e.target.closest('[data-view]'); if (a) ir(a.dataset.view); });

/* ---------- Estoque por zona ---------- */
function montarAbas() {
  const abas = [['', 'Todas'], ...meta.zonas.map(z => [z, z])];
  $('#abasZona').innerHTML = abas.map(([v, t]) =>
    `<li class="nav-item"><a class="nav-link ${v === zonaAtual ? 'active' : ''}" role="button" data-zona="${esc(v)}">${esc(t)}</a></li>`).join('');
}
$('#abasZona').addEventListener('click', e => {
  const a = e.target.closest('[data-zona]'); if (!a) return;
  zonaAtual = a.dataset.zona; tratar(carregarEstoque)();
});
$('#cardsZona').addEventListener('click', e => {
  const c = e.target.closest('[data-zona]'); if (!c) return;
  zonaAtual = zonaAtual === c.dataset.zona ? '' : c.dataset.zona; tratar(carregarEstoque)();
});
let tBusca; $('#busca').addEventListener('input', () => { clearTimeout(tBusca); tBusca = setTimeout(tratar(carregarEstoque), 300); });

async function carregarEstoque() {
  montarAbas();
  const todos = await api('/materiais?limite=5000');
  $('#cardsZona').innerHTML = meta.zonas.map(z => {
    const its = todos.filter(m => m.zona === z);
    return `<div class="col-6 col-lg-3"><div class="card card-zona p-3 ${z === zonaAtual ? 'ativa' : ''}" data-zona="${esc(z)}">
      <small class="text-muted">${esc(z)}</small><h4 class="mb-0">${its.length} <small class="fs-6">códigos</small></h4>
      <small>${fmt(its.reduce((s, m) => s + m.quantidade, 0))} un. em estoque</small></div></div>`;
  }).join('');
  const q = $('#busca').value.trim().toLowerCase();
  const lista = todos.filter(m => (!zonaAtual || m.zona === zonaAtual) &&
    (!q || m.codigo.toLowerCase().includes(q) || m.descricao.toLowerCase().includes(q))).slice(0, 300);
  $('#tabelaMateriais').innerHTML = lista.map(m => `<tr>
    <td><span class="mat-link" data-perfil="${esc(m.codigo)}">${esc(m.codigo)}</span></td>
    <td>${esc(m.descricao)}</td><td><span class="badge text-bg-light border">${esc(m.zona)}</span></td>
    <td class="text-end ${m.quantidade <= 0 ? 'text-danger fw-bold' : ''}">${fmt(m.quantidade)} ${esc(m.unidade)}</td>
    <td><button class="btn btn-sm btn-outline-secondary" data-perfil="${esc(m.codigo)}"><i class="bi bi-graph-up"></i></button></td></tr>`).join('')
    || '<tr><td colspan="5" class="text-center text-muted py-4">Nenhum material. Importe o relatório MB ou cadastre manualmente.</td></tr>';
}

/* ---------- Perfil do material ---------- */
let codigoPerfil = null;
document.addEventListener('click', e => {
  const p = e.target.closest('[data-perfil]');
  if (p) { codigoPerfil = p.dataset.perfil; tratar(abrirPerfil)(); }
});
$('#perfilDias').addEventListener('change', tratar(abrirPerfil));
async function abrirPerfil() {
  const d = await api(`/materiais/${encodeURIComponent(codigoPerfil)}/perfil?dias=${$('#perfilDias').value}`);
  $('#perfilTitulo').textContent = `${d.material.codigo} — ${d.material.descricao}`;
  const kpi = (t, v, c = 'primary') => `<div class="col-6 col-md-3"><div class="card p-3 border-${c}"><small class="text-muted">${t}</small><h4 class="mb-0">${v}</h4></div></div>`;
  $('#perfilCorpo').innerHTML = `<div class="row g-3 mb-3">
    ${kpi('Estoque atual', fmt(d.material.quantidade) + ' ' + esc(d.material.unidade), 'warning')}
    ${kpi('Última saída', fmtData(d.ultima_saida), 'danger')}
    ${kpi('Média mensal', fmt(d.media_mensal), 'success')}
    ${kpi('Média por saída', fmt(d.media_por_saida))}
    ${kpi('Saídas no período', d.numero_saidas)}
    ${kpi('Consumo líquido', fmt(d.consumo_liquido_periodo))}
    ${kpi('Média diária', fmt(d.media_diaria))}
    <div class="col-6 col-md-3"><div class="card p-3"><small class="text-muted">Por incidência</small>
      ${Object.entries(d.por_incidencia).map(([k, v]) => `<span class="badge badge-incidencia me-1">${esc(k)}: ${fmt(v)}</span>`).join('') || '—'}</div></div></div>
    <h6>Histórico recente</h6><div class="table-responsive"><table class="table table-sm"><thead><tr><th>Data/Hora</th><th>Tipo</th><th>Qtd</th><th>Incidência</th><th>Documento</th><th>Responsável</th><th>Local</th></tr></thead><tbody>
    ${d.historico_recente.map(h => `<tr><td>${fmtData(h.data_hora)}</td><td><span class="badge text-bg-${TIPO_COR[h.tipo]}">${h.tipo}</span></td>
      <td>${fmt(h.quantidade)}</td><td>${esc(h.incidencia || '—')}</td><td>${esc(h.documento || '—')}</td><td>${esc(h.responsavel || '—')}</td><td>${esc(h.local_obra || '—')}</td></tr>`).join('')
      || '<tr><td colspan="7" class="text-muted">Sem movimentações.</td></tr>'}</tbody></table></div>`;
  modal('modalPerfil').show();
}

/* ---------- Linhas de itens (ficha / acréscimo) ---------- */
function addLinhaItem(containerId) {
  const div = document.createElement('div');
  div.className = 'row g-2 mb-2 linha-item';
  div.innerHTML = `<div class="col-7"><input class="form-control it-codigo" list="dlCodigos" placeholder="Código" required></div>
    <div class="col-3"><input class="form-control it-qtd" type="number" step="any" min="0.001" placeholder="Qtd" required></div>
    <div class="col-2"><button type="button" class="btn btn-outline-danger w-100" onclick="this.closest('.linha-item').remove()"><i class="bi bi-trash"></i></button></div>`;
  document.getElementById(containerId).appendChild(div);
}
function coletarItens(containerId) {
  return [...document.querySelectorAll(`#${containerId} .linha-item`)].map(l => ({
    codigo: $('.it-codigo', l).value.trim(), quantidade: parseFloat($('.it-qtd', l).value) })).filter(i => i.codigo);
}
async function popularDatalist() {
  const ms = await api('/materiais?limite=5000');
  let dl = $('#dlCodigos'); if (!dl) { dl = document.createElement('datalist'); dl.id = 'dlCodigos'; document.body.appendChild(dl); }
  dl.innerHTML = ms.map(m => `<option value="${esc(m.codigo)}">${esc(m.descricao)}</option>`).join('');
}
$('#modalFicha').addEventListener('show.bs.modal', () => {
  $('#linhasItens').innerHTML = ''; addLinhaItem('linhasItens'); tratar(popularDatalist)();
});

/* ---------- Fichas ---------- */
$('#filtroStatus').addEventListener('change', tratar(carregarFichas));
async function carregarFichas() {
  const fs = await api('/fichas' + ($('#filtroStatus').value ? '?status=' + $('#filtroStatus').value : ''));
  $('#listaFichas').innerHTML = fs.map(f => {
    const [cor, nome] = STATUS[f.status];
    return `<div class="col-md-6 col-xl-4"><div class="card h-100"><div class="card-body">
      <div class="d-flex justify-content-between"><h6 class="mb-0">Doc. ${esc(f.numero_documento)}</h6><span class="badge text-bg-${cor}">${nome}</span></div>
      <small class="text-muted">${fmtData(f.criado_em)} · <span class="badge badge-incidencia">${esc(f.incidencia)}</span></small>
      <div class="small mt-2"><b>Solicitante:</b> ${esc(f.solicitante)}<br><b>LEAD:</b> ${esc(f.lead_equipe)}<br><b>Local:</b> ${esc(f.local_obra)}</div>
      <ul class="small mt-2 mb-0">${f.itens.map(i => `<li>${esc(i.codigo)} — ${esc(i.descricao)}: <b>${fmt(i.quantidade)}</b>
        ${i.acrescimo ? '<span class="badge text-bg-info">acréscimo</span>' : ''}${i.qtd_devolvida ? ` <span class="text-success">(dev. ${fmt(i.qtd_devolvida)})</span>` : ''}</li>`).join('')}</ul></div>
      <div class="card-footer d-flex gap-1 flex-wrap">
        <button class="btn btn-sm btn-outline-dark" onclick="abrirQR(${f.id})"><i class="bi bi-qr-code"></i> QR</button>
        ${f.status === 'EM_SEPARACAO' ? `<button class="btn btn-sm btn-outline-primary" onclick="abrirAcrescimo(${f.id})"><i class="bi bi-plus-circle"></i> Acréscimo</button>
          <button class="btn btn-sm btn-success" onclick="baixar(${f.id})"><i class="bi bi-check2"></i> Baixar</button>` : ''}
        ${f.status !== 'ESTORNADA' ? `<button class="btn btn-sm btn-outline-danger" onclick="estornar(${f.id})"><i class="bi bi-arrow-counterclockwise"></i> ${f.status === 'BAIXADA' ? 'Estornar' : 'Cancelar'}</button>` : ''}
      </div></div></div>`;
  }).join('') || '<p class="text-muted">Nenhuma ficha.</p>';
}
$('#formFicha').addEventListener('submit', tratar(async e => {
  e.preventDefault();
  const d = Object.fromEntries(new FormData(e.target));
  d.itens = coletarItens('linhasItens');
  const f = await api('/fichas', { method: 'POST', body: d });
  modal('modalFicha').hide(); e.target.reset(); await carregarFichas(); abrirQR(f.id);
}));
window.abrirAcrescimo = id => { fichaAcrescimo = id; $('#linhasAcrescimo').innerHTML = ''; addLinhaItem('linhasAcrescimo'); tratar(popularDatalist)(); modal('modalAcrescimo').show(); };
$('#formAcrescimo').addEventListener('submit', tratar(async e => {
  e.preventDefault();
  await api(`/fichas/${fichaAcrescimo}/acrescimo`, { method: 'POST', body: { itens: coletarItens('linhasAcrescimo') } });
  modal('modalAcrescimo').hide(); aviso('Materiais acrescentados à ficha.'); carregarFichas();
}));
window.baixar = tratar(async id => {
  if (!confirm('Confirmar baixa? O estoque será reduzido.')) return;
  await api(`/fichas/${id}/baixa`, { method: 'POST' }); aviso('Baixa realizada com sucesso.'); carregarFichas();
});
window.estornar = tratar(async id => {
  if (!confirm('Desfazer esta saída? O material volta ao estoque.')) return;
  await api(`/fichas/${id}/estorno`, { method: 'POST', body: {} }); aviso('Estorno realizado.'); carregarFichas();
});

/* ---------- QR Code / confirmação ---------- */
window.abrirQR = tratar(async id => {
  const f = await api('/fichas/' + id); mostrarQR(f);
});
function mostrarQR(f) {
  tokenConfirmar = f.token_qr;
  $('#qrTitulo').textContent = `Ficha ${f.numero_documento}`;
  $('#qrImg').src = `/api/fichas/${f.id}/qrcode?t=${Date.now()}`;
  $('#qrResumo').innerHTML = `<b>${esc(f.solicitante)}</b> · LEAD ${esc(f.lead_equipe)} · ${esc(f.local_obra)}<br>
    <span class="badge text-bg-${STATUS[f.status][0]}">${STATUS[f.status][1]}</span>
    <ul class="mt-2">${f.itens.map(i => `<li>${esc(i.codigo)} — ${esc(i.descricao)}: <b>${fmt(i.quantidade)}</b> (estoque ${fmt(i.estoque_atual)})</li>`).join('')}</ul>`;
  $('#btnConfirmarBaixa').classList.toggle('d-none', f.status !== 'EM_SEPARACAO');
  modal('modalQR').show();
}
$('#btnConfirmarBaixa').addEventListener('click', tratar(async () => {
  await api(`/fichas/token/${tokenConfirmar}/baixa`, { method: 'POST' });
  modal('modalQR').hide(); aviso('Baixa automática realizada: estoque atualizado.'); carregarFichas(); carregarEstoque();
}));
$('#modalQR').addEventListener('hidden.bs.modal', () => document.body.classList.remove('imprimindo-qr'));
window.addEventListener('beforeprint', () => { if ($('#modalQR').classList.contains('show')) document.body.classList.add('imprimindo-qr'); });

/* ---------- Sucatas e devoluções ---------- */
async function carregarSucatas() {
  const d = await api('/sucatas-devolucoes?dias=30');
  $('#sucEnt').textContent = fmt(d.total_entradas); $('#sucSai').textContent = fmt(d.total_saidas);
  $('#tabelaSucatas').innerHTML = d.movimentos.map(m => `<tr><td>${fmtData(m.data_hora)}</td>
    <td>${m.sentido === 'ENTRADA' ? '<span class="text-success">▲ Entrada</span>' : '<span class="text-danger">▼ Saída</span>'}</td>
    <td><span class="badge text-bg-${TIPO_COR[m.tipo]}">${m.tipo}</span></td><td>${esc(m.codigo)}</td><td>${esc(m.descricao)}</td>
    <td class="text-end">${fmt(m.quantidade)}</td><td>${esc(m.documento || '—')}</td><td>${esc(m.responsavel || '—')}</td></tr>`).join('')
    || '<tr><td colspan="8" class="text-center text-muted py-3">Sem movimentações no período.</td></tr>';
}
$('#formDevolucao').addEventListener('submit', tratar(async e => {
  e.preventDefault();
  const d = Object.fromEntries(new FormData(e.target)); d.quantidade = parseFloat(d.quantidade);
  await api('/devolucoes', { method: 'POST', body: d });
  modal('modalDevolucao').hide(); e.target.reset(); aviso('Registrado com sucesso.'); carregarSucatas();
}));

/* ---------- Relatório A4 ---------- */
$('#btnGerarRel').addEventListener('click', tratar(async () => {
  const d = await api(`/relatorios/saidas?codigos=${encodeURIComponent($('#relCodigos').value)}&dias=${$('#relDias').value}`);
  $('#folhaRelatorio').innerHTML = `<h4>Relatório de Saídas de Materiais</h4>
    <p>Período: últimos ${d.periodo_dias} dias · Códigos: ${d.codigos.length ? esc(d.codigos.join(', ')) : 'todos'} · Gerado em ${fmtData(d.gerado_em)}</p>
    <table><thead><tr><th>Documento</th><th>Responsável</th><th>Data e hora</th><th>Local</th><th>Código</th><th>Descrição</th><th>Qtd</th><th>Inc.</th></tr></thead><tbody>
    ${d.linhas.map(l => `<tr><td>${esc(l.documento)}</td><td>${esc(l.responsavel)}</td><td>${fmtData(l.data_hora)}</td><td>${esc(l.local_obra)}</td>
      <td>${esc(l.codigo)}</td><td>${esc(l.descricao)}</td><td>${fmt(l.quantidade)}</td><td>${esc(l.incidencia)}</td></tr>`).join('')
      || '<tr><td colspan="8">Sem saídas no período.</td></tr>'}</tbody></table>
    <p class="mt-2">Total de registros: ${d.linhas.length}</p>`;
}));

/* ---------- Importação MB ---------- */
async function carregarImportacoes() {
  const h = await api('/catalogo/importacoes');
  $('#tabelaImport').innerHTML = h.map(i => `<tr><td>${fmtData(i.data_hora)}</td><td>${esc(i.arquivo)}</td><td>${i.inseridos}</td><td>${i.atualizados}</td><td>${i.ignorados}</td></tr>`).join('')
    || '<tr><td colspan="5" class="text-muted">Nenhuma importação.</td></tr>';
}
$('#btnImportar').addEventListener('click', tratar(async () => {
  const file = $('#arquivoMB').files[0];
  if (!file) throw new Error('Selecione o arquivo MB.');
  const fd = new FormData(); fd.append('arquivo', file);
  $('#btnImportar').disabled = true;
  try {
    const r = await api(`/catalogo/importar?atualizar_estoque=${$('#chkEstoque').checked}`, { method: 'POST', body: fd });
    $('#resultadoImport').innerHTML = `<div class="alert alert-success mb-0"><b>${esc(r.arquivo)}</b><br>
      Novos: ${r.inseridos} · Atualizados: ${r.atualizados} · Ignorados: ${r.ignorados}<br><small>Histórico preservado.</small></div>`;
    carregarImportacoes();
  } finally { $('#btnImportar').disabled = false; }
}));

/* ---------- Inicialização ---------- */
(tratar(async () => {
  meta = await api('/metadados');
  document.querySelectorAll('.incidencia-sel').forEach(s => s.innerHTML = meta.incidencias.map(i => `<option>${esc(i)}</option>`).join(''));
  document.querySelectorAll('.zona-sel').forEach(s => s.innerHTML = meta.zonas.map(z => `<option>${esc(z)}</option>`).join(''));
  $('#formMaterial').addEventListener('submit', tratar(async e => {
    e.preventDefault();
    const d = Object.fromEntries(new FormData(e.target)); d.quantidade = parseFloat(d.quantidade || 0);
    await api('/materiais', { method: 'POST', body: d });
    modal('modalMaterial').hide(); e.target.reset(); aviso('Material cadastrado.'); carregarEstoque();
  }));
  // QR escaneado: /?confirmar=TOKEN abre a ficha para confirmar a baixa
  const token = new URLSearchParams(location.search).get('confirmar');
  await carregarEstoque();
  if (token) {
    history.replaceState(null, '', '/');
    mostrarQR(await api('/fichas/token/' + encodeURIComponent(token)));
  }
}))();
