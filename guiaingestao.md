# Guia de ingestão — CragAncoraCitys

Olá! Este documento explica como **enviar dados** pro portal CragAncoraCitys (Âncora + CragData).

Você manda HTML, CSV, JSON, planilhas, PDFs etc. pela API. O sistema processa automaticamente (ETL), indexa no banco e os dados passam a aparecer no **chat** e no **data-wall**.

**URL base (produção):** `https://ancora.craggroup.com`

**Endpoint principal:** `POST /entry/documents`

> Também funciona em `POST /api/entry/documents` (mesma coisa).

---

## O que acontece depois que você envia

1. A API responde na hora com `status: "pending"` e um `id` do documento
2. O backend processa em background (extração de texto, chunks, entidades)
3. O status muda para `done` (sucesso) ou `error` (falha)
4. Com `done`, o conteúdo já entra no chat e no grafo

Tempo típico: alguns segundos a ~1 minuto, dependendo do tamanho do arquivo.

---

## Formatos aceitos

| `format` | Exemplos de uso |
|----------|-----------------|
| `json` | APIs, dados estruturados, relatórios em JSON |
| `html` | Páginas web salvas, portais da prefeitura |
| `csv` | Planilhas de gastos, licitações, listagens |
| `txt` / `md` | Texto puro, atas, notas |
| `pdf` | Documentos escaneados (via upload de arquivo) |
| `docx` | Word |
| `xlsx` / `xls` | Excel |

---

## Resposta padrão (sucesso)

```json
{
  "id": "a1b2c3d4-....",
  "title": "Relatório de licitações",
  "status": "pending",
  "message": "Documento recebido via /entry/documents. ETL em processamento."
}
```

Guarde o `id` — serve pra consultar o status depois.

---

## Forma 1 — JSON (recomendada pra scripts e integrações)

**Headers:** `Content-Type: application/json`

**Body:**

```json
{
  "title": "Nome legível do documento",
  "format": "json",
  "content": { "ano": 2024, "licitacoes": 15, "valor_total": 1200000 },
  "origin_url": "https://site-da-cidade.gov.br/dados/licitacoes"
}
```

| Campo | Obrigatório | Descrição |
|-------|-------------|-----------|
| `title` | sim | Título que aparece no sistema |
| `format` | sim | Tipo do conteúdo (`json`, `html`, `csv`, `txt`...) |
| `content` | sim | Texto **ou** objeto/array (quando `format` é `json`) |
| `origin_url` | não | Link de onde veio o dado (ajuda na rastreabilidade) |

### Exemplo com cURL

```bash
curl -X POST "https://ancora.craggroup.com/entry/documents" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Licitações 2024",
    "format": "json",
    "content": {
      "municipio": "Âncora",
      "ano": 2024,
      "itens": [
        {"numero": "001/2024", "valor": 50000},
        {"numero": "002/2024", "valor": 120000}
      ]
    },
    "origin_url": "https://exemplo.gov.br/transparencia"
  }'
```

### Exemplo com Python

```python
import httpx

payload = {
    "title": "Licitações 2024",
    "format": "json",
    "content": {"ano": 2024, "total": 2},
    "origin_url": "https://exemplo.gov.br/dados",
}

r = httpx.post(
    "https://ancora.craggroup.com/entry/documents",
    json=payload,
    timeout=60,
)
r.raise_for_status()
print(r.json())  # {"id": "...", "status": "pending", ...}
```

### Enviar HTML ou CSV como texto no JSON

```json
{
  "title": "Página da transparência",
  "format": "html",
  "content": "<html><body><h1>Relatório</h1><p>Conteúdo...</p></body></html>"
}
```

```json
{
  "title": "Gastos janeiro",
  "format": "csv",
  "content": "data,valor,orgao\n2024-01-15,1000,obras\n2024-01-20,500,saude"
}
```

---

## Forma 2 — Corpo bruto (arquivo direto no POST)

Útil quando você já tem o arquivo e quer mandar o binário/texto sem montar JSON.

**Query params obrigatórios na URL:**
- `title` — nome do documento
- `format` — tipo (`html`, `csv`, `json`, `txt`...)

**Opcional:** `origin_url`

### HTML

```bash
curl -X POST \
  "https://ancora.craggroup.com/entry/documents?title=Portal+Transparencia&format=html&origin_url=https://site.gov.br" \
  -H "Content-Type: text/html" \
  --data-binary @pagina.html
```

### CSV

```bash
curl -X POST \
  "https://ancora.craggroup.com/entry/documents?title=Planilha+Gastos&format=csv" \
  -H "Content-Type: text/csv" \
  --data-binary @dados.csv
```

### JSON (arquivo .json)

```bash
curl -X POST \
  "https://ancora.craggroup.com/entry/documents?title=Dados+Abertos&format=json" \
  -H "Content-Type: application/json" \
  --data-binary @dados.json
```

---

## Forma 3 — Upload de arquivo (multipart)

**Endpoint:** `POST /entry/documents/upload`

```bash
curl -X POST "https://ancora.craggroup.com/entry/documents/upload" \
  -F "title=Relatório anual" \
  -F "format=pdf" \
  -F "file=@/caminho/relatorio.pdf" \
  -F "origin_url=https://exemplo.gov.br/relatorio.pdf"
```

Campos do formulário:

| Campo | Obrigatório | Descrição |
|-------|-------------|-----------|
| `file` | sim | O arquivo |
| `title` | não | Título (default: "Documento") |
| `format` | não | Se omitir, tenta deduzir pela extensão do arquivo |
| `origin_url` | não | URL de origem |

Também dá pra mandar texto no multipart (sem arquivo):

```bash
curl -X POST "https://ancora.craggroup.com/entry/documents" \
  -F "title=Nota técnica" \
  -F "format=txt" \
  -F "content=Texto completo do documento aqui..."
```

---

## Consultar status do documento

Depois de enviar, use o `id` retornado:

```bash
curl "https://ancora.craggroup.com/api/documents/{id}"
```

Exemplo de resposta quando terminou:

```json
{
  "id": "a1b2c3d4-....",
  "title": "Licitações 2024",
  "source": "entry",
  "file_type": "json",
  "status": "done",
  "error_message": null,
  "chunk_count": 3,
  "created_at": "2026-06-10T18:00:00Z"
}
```

**Status possíveis:**

| Status | Significado |
|--------|-------------|
| `pending` | Na fila |
| `processing` | ETL rodando |
| `done` | Pronto — já indexado |
| `error` | Falhou — veja `error_message` |

### Listar todos os documentos

```bash
curl "https://ancora.craggroup.com/api/documents"
```

---

## Enviar vários documentos em lote

A API recebe **um documento por request**. Pra lote, rode um loop:

```python
import httpx
from pathlib import Path

BASE = "https://ancora.craggroup.com/entry/documents"
arquivos = Path("./dados").glob("*.csv")

with httpx.Client(timeout=120) as client:
    for path in arquivos:
        r = client.post(
            BASE,
            params={"title": path.stem, "format": "csv"},
            headers={"Content-Type": "text/csv"},
            content=path.read_bytes(),
        )
        r.raise_for_status()
        doc = r.json()
        print(f"OK {path.name} -> id={doc['id']}")
```

**Dica:** espere 1–2 segundos entre requests se forem muitos arquivos grandes.

---

## Erros comuns

| Código / mensagem | Causa | Solução |
|-------------------|-------|---------|
| `400` formato não suportado | `format` inválido | Use um dos formatos da tabela acima |
| `400` corpo vazio | POST sem conteúdo | Envie `content` ou `file` |
| `400` JSON inválido | JSON malformado | Valide o JSON antes de enviar |
| `502` / timeout | Servidor sobrecarregado | Tente de novo; arquivos muito grandes podem demorar |
| `status: error` no documento | Conteúdo ilegível ou vazio | Confira se o PDF tem texto, se o CSV não está vazio etc. |

---

## Checklist rápido antes de mandar

- [ ] `title` descritivo (aparece no chat e no grafo)
- [ ] `format` correto pro tipo de dado
- [ ] `origin_url` quando souber de onde veio
- [ ] Guardar o `id` da resposta
- [ ] Conferir `GET /api/documents/{id}` até `status: done`

---

## Alternativa: interface web

Se preferir não usar API, dá pra subir pela tela:

**https://ancora.craggroup.com/documentos**

Lá tem drag-and-drop de arquivos e botão de varredura automática (Brave + CragData).

---

## Dúvidas

Fala com o João se precisar de:

- confirmar o domínio exato (`ancora.craggroup.com`)
- chave de API no futuro (hoje o endpoint está aberto, sem autenticação)
- formato de dado específico que não está entrando

**Docs interativas da API (Swagger):** `https://ancora.craggroup.com/api/docs`