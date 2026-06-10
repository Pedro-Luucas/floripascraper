# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Projeto: FloripaScraper

Scraper de dados públicos de Florianópolis para alimentar um chatbot IA com dados governamentais e abertos.

## Stack

- **Python 3.10+** (usar `python --version` para confirmar)
- **venv** para ambiente virtual
- **JSON** como formato de armazenamento (um arquivo por fonte)
- **requests** para sites com API aberta
- **Selenium** para sites que requerem renderização JS

## Estrutura de Diretórios

```
floripascraper/
├── scrapers/           # Scripts de scraping (um por site/fonte)
│   ├── exemplo.py
│   └── ...
├── data/               # Arquivos JSON (um por fonte de dados)
├── utils/              # Funções globais (utilities)
│   ├── normalizers.py  # Padronização de dados (CEP, CNPJ, CPF, data, etc.)
│   ├── retry_handler.py # Retry com backoff para requisições HTTP
│   └── robots_checker.py # Verificação de robots.txt
├── requirements.txt    # Dependências Python
├── .gitignore
├── CLAUDE.md
├── README.md
└── PLANO.md
```

## Comandos Comuns

### Setup do ambiente
```powershell
cd floripascraper
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Executar scrapers
```powershell
# Executar um scraper específico
python scrapers\nome_do_scraper.py

# Executar todos (futuro)
python run_all.py
```

### Verificar dados coletados
```powershell
# Listar arquivos JSON
Get-ChildItem data\

# Verificar conteúdo de um arquivo JSON
Get-Content data\licitacoes.json | ConvertFrom-Json
```

## Regras de Desenvolvimento

### Funções Globais de Normalização (utils/normalizers.py)
- **OBRIGATÓRIO**: Todos os scrapers DEVEM usar `utils/normalizers.py` para padronizar dados
- Incluir: CEP, CNPJ, CPF, data, telefone, preço/valor monetário
- Se um normalizer não existir, criar antes de prosseguir com o scraper

### Cada Scraper é Independente
- Um arquivo `.py` por site/fonte
- Cada scraper cria seu próprio arquivo JSON em `data/` conforme necessidade
- Não precisa seguir schema fixo — adapta ao que o site oferece

### Dados Tratados
- Dados DEVEM ser normalizados antes de salvar no banco
- Incluir metadados: `fonte` (nome do site), `url_origem`, `data_coleta`
- Não salvar HTML bruto — salvar dados parseados e tratados

### Tratamento de Erros
- Implementar retry com backoff para requisições HTTP
- Logar erros e continuar (não parar todo o processo por um site falhar)
- Salvar URLs que falharam para retry posterior

### Código
- Type hints em todas as funções
- Docstrings descritivas
- Sem `print()` para debug — usar logging
- Não hardcodar credenciais ou tokens

## Portais a Fazer Scraping

### Alta Prioridade
1. `transparencia.e-publica.net` - Portal de transparência geral
2. `pmf.sc.gov.br` - Site oficial Prefeitura Municipal de Florianópolis
3. `cigaobras.pmf.sc.gov.br` - Portal de obras e transparência

### Secundários (verificar conforme desenvolvimento)
- Portal da Transparência municipal
- Dados abertos governamentais (dados.gov.br)
- Outros sites mencionados pelo usuário

## Notas Importantes

- Scraper é **one-time run** — não precisa de scheduler
- Se site tem API aberta, usar `requests` (não Selenium)
- Se site requer JS rendering, usar Selenium com Chrome headless
- Verificar `robots.txt` e termos de uso antes de fazer scraping
- Respeitar rate limits — adicionar delays entre requisições