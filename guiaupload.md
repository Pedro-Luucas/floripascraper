# Guia de camadas GIS — CragAncoraCitys

Envie **shapefiles**, **GeoJSON**, **JSON com lat/lng**, **CSV** ou **ZIP** pela API. Cada conjunto vira uma **camada** com tag = nome do arquivo, visível no mapa do **Visão geral** (`/data-wall`) e no chat.

**URL base (produção):** `https://ancora.craggroup.com`

**Endpoint principal:** `POST /entry/mapas/upload`

> Alias equivalente: `POST /api/entry/mapas/upload` e `POST /api/mapas/upload`

---

## Formatos aceitos

| Envio | Arquivos |
|-------|----------|
| Shapefile | `.shp` + `.shx` + `.dbf` + `.prj` (`.cst` opcional) — **todos no mesmo POST** |
| GeoJSON / JSON | `.json` ou `.geojson` |
| CSV | colunas de latitude/longitude (ou lat/lng) |
| ZIP | um `.zip` com shapefile ou GeoJSON dentro |

Cada request = **uma camada**. Vários shapefiles na mesma pasta = vários POSTs (use o script abaixo).

---

## Resposta (sucesso)

```json
{
  "layer_id": "a1b2c3d4-....",
  "name": "obras municipais",
  "status": "ready",
  "feature_count": 142,
  "geometry_type": "Polygon",
  "message": "Camada recebida via /entry/mapas/upload. Visível no Visão geral."
}
```

---

## Upload — multipart (recomendado)

**Campo de arquivos:** `files` (pode repetir — um campo por arquivo)

**Query opcional:** `?name=Nome+da+Camada` (tag exibida no mapa)

### cURL — shapefile completo

```bash
curl -X POST "https://ancora.craggroup.com/entry/mapas/upload?name=Obras+Municipais" \
  -F "files=@/caminho/obras.shp" \
  -F "files=@/caminho/obras.shx" \
  -F "files=@/caminho/obras.dbf" \
  -F "files=@/caminho/obras.prj"
```

### cURL — ZIP

```bash
curl -X POST "https://ancora.craggroup.com/entry/mapas/upload" \
  -F "files=@/caminho/camada.zip"
```

### cURL — GeoJSON

```bash
curl -X POST "https://ancora.craggroup.com/entry/mapas/upload?name=Bairros" \
  -F "files=@/caminho/bairros.geojson"
```

---

## Script Python (pasta inteira)

No repositório:

```bash
pip install httpx
python scripts/upload_map_layers.py ./pasta_com_mapas/
python scripts/upload_map_layers.py -r ./gis/          # subpastas
python scripts/upload_map_layers.py --dry-run ./gis/  # só listar
python scripts/upload_map_layers.py --base-url http://localhost ./teste.zip
```

O script agrupa automaticamente `.shp` + sidecars e envia cada conjunto como uma camada.

### Exemplo mínimo em Python

```python
import httpx
from pathlib import Path

BASE = "https://ancora.craggroup.com"
DIR = Path("./obras")

files = [
    ("files", (p.name, p.read_bytes(), "application/octet-stream"))
    for p in [DIR / "obras.shp", DIR / "obras.shx", DIR / "obras.dbf", DIR / "obras.prj"]
    if p.exists()
]

r = httpx.post(
    f"{BASE}/entry/mapas/upload",
    params={"name": "Obras Municipais"},
    files=files,
    timeout=300,
)
r.raise_for_status()
print(r.json())
```

---

## Consultar camadas

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| `GET` | `/entry/mapas/layers` | Lista todas as camadas |
| `GET` | `/entry/mapas/layers/{id}` | Metadados (cor, feições, bbox…) |
| `GET` | `/entry/mapas/layers/{id}/geojson` | GeoJSON processado |

```bash
curl "https://ancora.craggroup.com/entry/mapas/layers"
```

---

## Onde aparece no portal

1. **Documentos → Mapas** — lista e gerencia camadas
2. **Visão geral** (`/data-wall`) — mapa à direita, camadas visíveis com cores
3. **Chat / Intelli** — atributos das camadas entram no contexto da IA

---

## Erros comuns

| Erro | Causa | Solução |
|------|-------|---------|
| `Nenhum arquivo .shp encontrado` | Faltou `.shx`/`.dbf` ou arquivos em POSTs separados | Envie todos juntos no mesmo multipart |
| `Nenhuma feição geográfica` | Shapefile vazio ou CRS inválido | Confira `.prj` e dados no QGIS |
| `Tipos não suportados` | Extensão errada | Use só formatos da tabela acima |

---

## Autenticação

Hoje o endpoint é **aberto** (mesmo modelo do `/entry/documents`). Se precisar de API key no futuro, avise para configurarmos no servidor.