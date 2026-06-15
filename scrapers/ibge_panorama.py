"""Scraper para IBGE Cidades — Panorama de Florianópolis.

Fonte: https://cidades.ibge.gov.br/brasil/sc/florianopolis/panorama
API:   https://servicodados.ibge.gov.br

Não requer Selenium — todos os dados são extraídos via API REST pública do IBGE.

Dados coletados:
  - Informações básicas do município (localidades API)
  - 43 indicadores em 7 temas: População, Trabalho e Rendimento, Educação,
    Economia, Saúde, Meio Ambiente, Território  — com metadados, valores,
    histórico completo, fontes e ranking estadual/nacional
  - Nomes mais populares (censo de nomes 2022)
  - Pirâmide etária completa (21 faixas × 2 sexos — Censo 2022)
"""

import json
import logging
import os
import sys
from datetime import datetime
from typing import Any, Optional

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scrapers.base_scraper import BaseScraper

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuração do município
# ---------------------------------------------------------------------------
MUNICIPIO_CODE_IBGE = 4205407   # Código IBGE completo (7 dígitos)
MUNICIPIO_CODE_API = "420540"   # Código de 6 dígitos usado na API de indicadores

API_BASE = "https://servicodados.ibge.gov.br/api"
URL_PANORAMA = "https://cidades.ibge.gov.br/brasil/sc/florianopolis/panorama"

# ---------------------------------------------------------------------------
# IDs dos indicadores exibidos no Panorama (43 total, obtidos das chamadas
# de rede da página Angular)
# ---------------------------------------------------------------------------
ALL_INDICATOR_IDS = [
    # População (7)
    29169, 29170, 96385, 29171, 96486, 96544, 96386,
    # Trabalho e Rendimento (3)
    143558, 143514, 60037,
    # Educação (11)
    60045, 78187, 78192, 5908, 5903, 5913, 5918, 5929, 5934, 5950, 5955,
    # Economia (5)
    47001, 329756, 28141, 60048, 29749,
    # Saúde (3)
    30279, 60032, 28242,
    # Meio Ambiente (7)
    95335, 60030, 60029, 60031, 93371, 77861, 82270,
    # Território (7)
    29167, 87529, 87530, 91245, 91247, 91249, 91251,
]

TEMAS: dict[str, dict[str, Any]] = {
    "populacao": {
        "nome": "População",
        "indicadores": [29169, 29170, 96385, 29171, 96486, 96544, 96386],
    },
    "trabalho_e_rendimento": {
        "nome": "Trabalho e Rendimento",
        "indicadores": [143558, 143514, 60037],
    },
    "educacao": {
        "nome": "Educação",
        "indicadores": [60045, 78187, 78192, 5908, 5903, 5913, 5918, 5929, 5934, 5950, 5955],
    },
    "economia": {
        "nome": "Economia",
        "indicadores": [47001, 329756, 28141, 60048, 29749],
    },
    "saude": {
        "nome": "Saúde",
        "indicadores": [30279, 60032, 28242],
    },
    "meio_ambiente": {
        "nome": "Meio Ambiente",
        "indicadores": [95335, 60030, 60029, 60031, 93371, 77861, 82270],
    },
    "territorio": {
        "nome": "Território",
        "indicadores": [29167, 87529, 87530, 91245, 91247, 91249, 91251],
    },
}

# IDs da pirâmide etária — 21 faixas × 2 sexos = 42 indicadores (Censo 2022)
PIRAMIDE_IDS = [
    97512, 97513, 97527, 97528, 97545, 97546, 97563, 97564,
    97581, 97582, 97599, 97600, 97617, 97618, 97635, 97636,
    97653, 97654, 97671, 97672, 97689, 97690, 97707, 97708,
    97725, 97726, 97743, 97744, 97761, 97762, 97779, 97780,
    97797, 97798, 97815, 97816, 97833, 97834, 97851, 97852,
    97869, 97870,
]


def _ids_to_param(ids: list[int]) -> str:
    """Codifica lista de IDs como 'id1%7Cid2%7C...' (pipe URL-encoded)."""
    return "%7C".join(str(i) for i in ids)


def _parse_valor(raw: str) -> Any:
    """Tenta converter string da API para int ou float; mantém str caso contrário."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    # Tenta inteiro
    try:
        return int(s)
    except ValueError:
        pass
    # Tenta float (API pode retornar "537211" ou "0.847")
    try:
        return float(s)
    except ValueError:
        pass
    # Retorna string (ex: "Mata Atlântica", "Pertence")
    return s


class IbgePanoramaScraper(BaseScraper):
    """Scraper para o Panorama Municipal do IBGE Cidades.

    Usa exclusivamente a API REST pública ``servicodados.ibge.gov.br``.
    Nenhuma renderização JS é necessária.

    Args:
        municipio_code: Código IBGE completo (7 dígitos) do município.
                        Default: Florianópolis (4205407).
    """

    def __init__(self, municipio_code: int = MUNICIPIO_CODE_IBGE) -> None:
        super().__init__(
            name="ibge_panorama",
            base_url=API_BASE,
            rate_limit_delay=0.4,
        )
        self.municipio_code = municipio_code
        # A API de indicadores usa código de 6 dígitos (remove dígito verificador)
        self.municipio_code_api = str(municipio_code)[:-1]

    # ------------------------------------------------------------------
    # Headers
    # ------------------------------------------------------------------

    def _api_headers(self) -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7",
            "Origin": "https://cidades.ibge.gov.br",
            "Referer": "https://cidades.ibge.gov.br/",
        }

    def _fetch_json(self, url: str) -> Any:
        """Faz GET e retorna JSON; retorna None em caso de falha."""
        response = self._make_request(url, headers=self._api_headers())
        if response is None:
            logger.error("Falha ao buscar: %s", url)
            return None
        try:
            return response.json()
        except Exception as exc:
            logger.error("Erro ao parsear JSON de %s: %s", url, exc)
            return None

    # ------------------------------------------------------------------
    # 1. Informações do município
    # ------------------------------------------------------------------

    def _fetch_municipio_info(self) -> dict[str, Any]:
        """Dados básicos via localidades API."""
        url = f"{API_BASE}/v1/localidades/municipios/{self.municipio_code}"
        data = self._fetch_json(url)
        if not data:
            return {}

        uf = (
            data.get("microrregiao", {})
            .get("mesorregiao", {})
            .get("UF", {})
        )
        regiao = uf.get("regiao", {})
        reg_imediata = data.get("regiao-imediata", {})
        reg_intermediaria = reg_imediata.get("regiao-intermediaria", {})
        microrregiao = data.get("microrregiao", {})
        mesorregiao = microrregiao.get("mesorregiao", {})

        # Monta o contexto para a API de ranking
        self._contexto = (
            f"BR,{uf.get('id')},{microrregiao.get('id')},{reg_imediata.get('id')}"
        )

        return {
            "codigo_ibge": data.get("id"),
            "codigo_api": self.municipio_code_api,
            "nome": data.get("nome"),
            "estado": {
                "id": uf.get("id"),
                "sigla": uf.get("sigla"),
                "nome": uf.get("nome"),
            },
            "regiao_brasil": {
                "id": regiao.get("id"),
                "sigla": regiao.get("sigla"),
                "nome": regiao.get("nome"),
            },
            "mesorregiao": {"id": mesorregiao.get("id"), "nome": mesorregiao.get("nome")},
            "microrregiao": {"id": microrregiao.get("id"), "nome": microrregiao.get("nome")},
            "regiao_imediata": {"id": reg_imediata.get("id"), "nome": reg_imediata.get("nome")},
            "regiao_intermediaria": {
                "id": reg_intermediaria.get("id"),
                "nome": reg_intermediaria.get("nome"),
            },
        }

    # ------------------------------------------------------------------
    # 2. Metadados dos indicadores (nome, unidade, fontes, notas)
    # ------------------------------------------------------------------

    def _fetch_metadata(self, ids: list[int]) -> dict[int, dict[str, Any]]:
        url = f"{API_BASE}/v1/pesquisas/indicadores/{_ids_to_param(ids)}?localidade=&lang=pt"
        data = self._fetch_json(url)
        if not data:
            return {}

        result: dict[int, dict[str, Any]] = {}
        for item in data:
            ind_id = item.get("id")
            unidade = item.get("unidade", {})

            # Consolida fontes únicas de todos os períodos
            fontes_set: set[str] = set()
            for periodo_fontes in item.get("fonte", []):
                for f in periodo_fontes.get("fontes", []):
                    if f:
                        fontes_set.add(f.strip())

            # Consolida notas únicas
            notas_set: set[str] = set()
            for nota_entry in item.get("nota", []):
                for n in nota_entry.get("notas", []):
                    if n:
                        notas_set.add(n.strip())

            result[ind_id] = {
                "nome": item.get("indicador", ""),
                "unidade": unidade.get("id", ""),
                "unidade_multiplicador": unidade.get("multiplicador", 1),
                "fontes": sorted(fontes_set),
                "notas": sorted(notas_set),
            }
        return result

    # ------------------------------------------------------------------
    # 3. Resultados dos indicadores (valores por ano)
    # ------------------------------------------------------------------

    def _fetch_results(self, ids: list[int]) -> dict[int, dict[str, Any]]:
        url = (
            f"{API_BASE}/v1/pesquisas/indicadores/{_ids_to_param(ids)}"
            f"/resultados/{self.municipio_code_api}"
        )
        data = self._fetch_json(url)
        if not data:
            return {}

        result: dict[int, dict[str, Any]] = {}
        for item in data:
            ind_id = item.get("id")
            res_list = item.get("res", [])
            if not res_list:
                continue
            raw_res: dict[str, str] = res_list[0].get("res", {})
            # Filtra períodos com valor preenchido
            historico = {
                ano: _parse_valor(val)
                for ano, val in raw_res.items()
                if val is not None and str(val).strip() not in ("", "-")
            }
            result[ind_id] = historico
        return result

    # ------------------------------------------------------------------
    # 4. Rankings (posição no estado e no país)
    # ------------------------------------------------------------------

    def _fetch_rankings(
        self,
        ids: list[int],
        results: dict[int, dict[str, Any]],
    ) -> dict[int, dict[str, Any]]:
        """Busca posição de cada indicador no estado e no Brasil."""
        contexto = getattr(self, "_contexto", f"BR,42,42016,420001")

        # Monta parâmetro com o ano mais recente de cada indicador
        ranking_parts: list[str] = []
        for ind_id in ids:
            hist = results.get(ind_id, {})
            if not hist:
                continue
            latest_year = max(hist.keys())
            ranking_parts.append(f"{ind_id}({latest_year})")

        if not ranking_parts:
            return {}

        url = (
            f"{API_BASE}/v1/pesquisas/indicadores/ranking/{_ids_to_param_str(ranking_parts)}"
            f"?localidade={self.municipio_code_api}"
            f"&contexto={contexto}"
            f"&upper=0&lower=0&natureza=4"
        )
        data = self._fetch_json(url)
        if not data:
            return {}

        rankings: dict[int, dict[str, Any]] = {}
        for item in data:
            ind_id = item.get("id")
            res_list = item.get("res", [])
            if not res_list:
                continue
            r = res_list[0]
            rankings[ind_id] = {
                "posicao_br": r.get("posicao_br"),
                "total_br": r.get("total_br"),
                "posicao_uf": r.get("posicao_uf"),
                "total_uf": r.get("total_uf"),
            }
        return rankings

    # ------------------------------------------------------------------
    # 5. Nomes mais populares (Censo 2022)
    # ------------------------------------------------------------------

    def _fetch_nomes_populares(self) -> dict[str, Any]:
        url = f"{API_BASE}/v3/nomes/2022/localidade/{self.municipio_code}"
        data = self._fetch_json(url)
        if not data:
            # Fallback: ranking geral de nomes sem filtro de localidade
            url_fallback = f"{API_BASE}/v2/censos/nomes/ranking?municipio={self.municipio_code_api}"
            data = self._fetch_json(url_fallback)

        if not data or not isinstance(data, list):
            logger.warning("Nomes populares não disponíveis.")
            return {}

        nomes: dict[str, Any] = {}
        for item in data:
            tipo = str(item.get("tipo", item.get("sexo", ""))).upper()
            nome = str(item.get("nome", "")).strip().title()
            frequencia = item.get("frequencia") or item.get("proporcao")
            if tipo in ("M", "MASCULINO") and "masculino" not in nomes:
                nomes["masculino"] = {"nome": nome, "frequencia": frequencia}
            elif tipo in ("F", "FEMININO") and "feminino" not in nomes:
                nomes["feminino"] = {"nome": nome, "frequencia": frequencia}
            elif tipo in ("S", "SOBRENOME") and "sobrenome" not in nomes:
                nomes["sobrenome"] = {"nome": nome, "frequencia": frequencia}

        return nomes

    # ------------------------------------------------------------------
    # 6. Pirâmide etária (Censo 2022)
    # ------------------------------------------------------------------

    def _fetch_piramide_etaria(self) -> list[dict[str, Any]]:
        """Busca dados da pirâmide etária — 21 faixas por sexo."""
        ids_param = _ids_to_param(PIRAMIDE_IDS)

        # Resultados
        url_res = (
            f"{API_BASE}/v1/pesquisas/10101/periodos/2022"
            f"/indicadores/{ids_param}/resultados/{self.municipio_code_api}"
        )
        results_data = self._fetch_json(url_res)

        # Metadados (nomes das faixas etárias)
        url_meta = f"{API_BASE}/v1/pesquisas/indicadores/{ids_param}?localidade=&lang=pt"
        meta_data = self._fetch_json(url_meta)

        if not results_data:
            logger.warning("Pirâmide etária não disponível.")
            return []

        # Mapeia id → valor 2022
        id_to_value: dict[int, Any] = {}
        for item in results_data:
            ind_id = item.get("id")
            res_list = item.get("res", [])
            if res_list:
                val = res_list[0].get("res", {}).get("2022")
                id_to_value[ind_id] = _parse_valor(val)

        # Mapeia id → nome do indicador (ex: "Homens - 0 a 4 anos")
        id_to_nome: dict[int, str] = {}
        if meta_data:
            for item in meta_data:
                id_to_nome[item.get("id")] = item.get("indicador", "")

        # Agrupa em pares (masculino, feminino) por faixa etária
        pyramid: list[dict[str, Any]] = []
        pairs = list(zip(PIRAMIDE_IDS[::2], PIRAMIDE_IDS[1::2]))
        for male_id, female_id in pairs:
            nome_masc = id_to_nome.get(male_id, "")
            # Extrai faixa etária do nome (remove prefixo de sexo)
            faixa = (
                nome_masc
                .replace("Homens - ", "")
                .replace("Homens de ", "")
                .replace(" anos", "")
                .strip()
            )
            pyramid.append({
                "faixa_etaria": faixa or nome_masc,
                "nome_indicador_masculino": nome_masc,
                "nome_indicador_feminino": id_to_nome.get(female_id, ""),
                "masculino": id_to_value.get(male_id),
                "feminino": id_to_value.get(female_id),
            })

        return pyramid

    # ------------------------------------------------------------------
    # Montagem do indicador individual
    # ------------------------------------------------------------------

    def _build_indicador(
        self,
        ind_id: int,
        metadata: dict[int, dict],
        results: dict[int, dict],
        rankings: dict[int, dict],
    ) -> dict[str, Any]:
        meta = metadata.get(ind_id, {})
        hist = results.get(ind_id, {})
        rank = rankings.get(ind_id, {})

        valor_atual = None
        periodo_atual = None
        if hist:
            periodo_atual = max(hist.keys())
            valor_atual = hist[periodo_atual]

        return {
            "id_ibge": ind_id,
            "nome": meta.get("nome", f"Indicador {ind_id}"),
            "valor_atual": valor_atual,
            "periodo_atual": periodo_atual,
            "unidade": meta.get("unidade", ""),
            "historico": hist,
            "ranking": {
                "posicao_brasil": rank.get("posicao_br"),
                "total_municipios_brasil": rank.get("total_br"),
                "posicao_estado": rank.get("posicao_uf"),
                "total_municipios_estado": rank.get("total_uf"),
            } if rank else None,
            "fontes": meta.get("fontes", []),
            "notas": meta.get("notas", []),
        }

    # ------------------------------------------------------------------
    # scrape() — método principal
    # ------------------------------------------------------------------

    def scrape(self) -> dict[str, Any]:
        """Executa o scraping completo e retorna o JSON estruturado."""
        logger.info("Iniciando scraping IBGE Panorama — código %s", self.municipio_code)

        # 1. Dados do município (também define self._contexto para rankings)
        logger.info("[1/6] Buscando dados do município...")
        municipio = self._fetch_municipio_info()

        # 2. Metadados dos indicadores
        logger.info("[2/6] Buscando metadados dos indicadores...")
        metadata = self._fetch_metadata(ALL_INDICATOR_IDS)
        logger.info("  → %d indicadores com metadados", len(metadata))

        # 3. Resultados históricos
        logger.info("[3/6] Buscando resultados dos indicadores...")
        results = self._fetch_results(ALL_INDICATOR_IDS)
        logger.info("  → %d indicadores com resultados", len(results))

        # 4. Rankings
        logger.info("[4/6] Buscando rankings...")
        rankings = self._fetch_rankings(ALL_INDICATOR_IDS, results)
        logger.info("  → %d indicadores com ranking", len(rankings))

        # 5. Nomes populares
        logger.info("[5/6] Buscando nomes populares...")
        nomes_populares = self._fetch_nomes_populares()

        # 6. Pirâmide etária
        logger.info("[6/6] Buscando pirâmide etária...")
        piramide = self._fetch_piramide_etaria()
        logger.info("  → %d faixas etárias", len(piramide))

        # ---------------------------------------------------------------
        # Monta saída estruturada
        # ---------------------------------------------------------------
        temas_output: dict[str, Any] = {}
        for tema_key, tema_info in TEMAS.items():
            indicadores_output: dict[str, Any] = {}
            for ind_id in tema_info["indicadores"]:
                ind_data = self._build_indicador(ind_id, metadata, results, rankings)
                nome_key = _slugify(ind_data["nome"]) or f"indicador_{ind_id}"
                indicadores_output[nome_key] = ind_data

            temas_output[tema_key] = {
                "nome": tema_info["nome"],
                "total_indicadores": len(indicadores_output),
                "indicadores": indicadores_output,
            }

        total_indicadores = sum(
            len(t["indicadores"]) for t in temas_output.values()
        )

        output: dict[str, Any] = {
            "municipio": municipio,
            "temas": temas_output,
            "nomes_populares": nomes_populares,
            "piramide_etaria_censo_2022": {
                "ano_referencia": 2022,
                "total_faixas": len(piramide),
                "faixas": piramide,
            },
            "resumo": {
                "total_temas": len(temas_output),
                "total_indicadores": total_indicadores,
                "piramide_disponivel": len(piramide) > 0,
            },
            "fonte": "IBGE Cidades",
            "url_origem": URL_PANORAMA,
            "api_base": "https://servicodados.ibge.gov.br/api",
            "data_coleta": datetime.now().isoformat(),
        }

        logger.info(
            "Scraping concluído — %d temas, %d indicadores, %d faixas etárias",
            len(temas_output),
            total_indicadores,
            len(piramide),
        )
        return output


# ---------------------------------------------------------------------------
# Helpers de string
# ---------------------------------------------------------------------------

def _ids_to_param_str(parts: list[str]) -> str:
    """Codifica lista de strings como 'p1%7Cp2%7C...'."""
    return "%7C".join(parts)


def _slugify(text: str) -> str:
    """Converte nome do indicador em chave de dicionário legível."""
    import unicodedata
    # Normaliza acentos
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_text = nfkd.encode("ascii", "ignore").decode("ascii")
    # Substitui caracteres especiais por underscore
    slug = ""
    for ch in ascii_text.lower():
        if ch.isalnum():
            slug += ch
        elif ch in (" ", "-", "_", "/"):
            slug += "_"
    # Remove underscores múltiplos e trunca
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_")[:60]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    scraper = IbgePanoramaScraper()
    data = scraper.scrape()

    output_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data",
    )
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "ibge_panorama_florianopolis.json")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    logger.info("JSON salvo em: %s", output_path)

    # Resumo rápido
    resumo = data.get("resumo", {})
    logger.info(
        "Resumo: %d temas | %d indicadores | pirâmide=%s",
        resumo.get("total_temas", 0),
        resumo.get("total_indicadores", 0),
        "sim" if resumo.get("piramide_disponivel") else "não",
    )


if __name__ == "__main__":
    main()
