# FloripaScraper

Scraper de dados públicos de Florianópolis para alimentar um chatbot IA com conhecimento sobre dados governamentais e abertos.

## Objetivo

Agregar a maior quantidade possível de dados públicos de Florianópolis (prefeitura, transparência, dados geográficos) em arquivos JSON para posterior integração com um chatbot baseado em Vector DB.

## Fontes de Dados

- **Portal de Transparência** (transparencia.e-publica.net)
- **Prefeitura Municipal de Florianópolis** (pmf.sc.gov.br)
- **CIGA Obras** (cigaobras.pmf.sc.gov.br)
- Outros portais governamentais conforme desenvolvimento

## Stack Tecnológica

| Tecnologia | Uso |
|------------|-----|
| Python 3.10+ | Linguagem principal |
| JSON | Armazenamento de dados (um arquivo por fonte) |
| requests | HTTP para sites com API |
| Selenium | Renderização JS para sites dinâmicos |

## Instalação

```powershell
# Clonar/criar diretório
cd floripascraper

# Criar ambiente virtual
python -m venv venv
.\venv\Scripts\Activate.ps1

# Instalar dependências
pip install -r requirements.txt
```

## Estrutura

```
floripascraper/
├── scrapers/       # Scripts de scraping (um por fonte)
├── data/           # Arquivos JSON (um por fonte de dados)
├── utils/          # Funções de normalização (CEP, CNPJ, etc.)
├── requirements.txt
└── README.md
```

## Uso

**1. Executar scrapers:**
```powershell
python run_all.py
```

**2. Enviar para API:**
```powershell
python upload_to_api.py
```

**3. Verificar dados coletados:**
```powershell
# Listar arquivos JSON
Get-ChildItem data\

# Verificar conteúdo de um arquivo JSON
Get-Content data\licitacoes.json | ConvertFrom-Json
```

## Dados Normalizados

Todos os dados são tratados antes de salvar:
- CNPJ/CPF
- CEP
- Datas
- Telefones
- Valores monetários

## Status do Projeto

🚧 Em desenvolvimento — scrapers sendo criados conforme necessidade.

## Contribuição

Scrapers são independentes. Cada site/fonte tem seu próprio arquivo em `scrapers/`.