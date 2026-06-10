# Plano de Ação — FloripaScraper

Plano para outro agente (ou futuro Claude) implementar toda a aplicação do zero.

---

## Fase 1: Setup Inicial

### 1.1 Requisitos e estrutura
- [ ] Criar `requirements.txt` com dependências:
  - `requests`
  - `selenium`
  - `webdriver-manager`
  - `beautifulsoup4`
  - `lxml`
  - `fake-useragent`
- [ ] Criar estrutura de diretórios:
  ```
  floripascraper/
  ├── scrapers/
  ├── database/
  ├── utils/
  ```

### 1.2 Módulo de Normalização (`utils/normalizers.py`)
- [ ] Criar arquivo com funções de padronização:
  - [ ] `normalize_cnpj(cnpj: str) -> str` — Remove pontuação, valida CNPJ
  - [ ] `normalize_cpf(cpf: str) -> str` — Remove pontuação, valida CPF
  - [ ] `normalize_cep(cep: str) -> str` — Formata como 00000-000
  - [ ] `normalize_data(data: str, formato_origem: str) -> str` — Converte para ISO 8601
  - [ ] `normalize_telefone(tel: str) -> str` — Formata como +55 48 XXXXX-XXXX
  - [ ] `normalize_moeda(valor: str) -> float` — Converte "R$ 1.234,56" para 1234.56
  - [ ] `normalize_preco(valor: str) -> float` — Versão simplificada para preços sem símbolo
- [ ] Adicionar tratamento de exceções e logging
- [ ] Adicionar type hints e docstrings

### 1.3 Módulo de Banco de Dados (`database/db_manager.py`)
- [ ] Criar utilitário para conexão SQLite
- [ ] Função para criar tabela dinamicamente
- [ ] Função para insert com tratamento de erros
- [ ] Metadados automáticos: `fonte`, `url_origem`, `data_coleta`

---

## Fase 2: Scrapers

### 2.1 Scraper Base (`scrapers/base_scraper.py`)
- [ ] Criar classe base com:
  - Configuração de headers (User-Agent realista)
  - Retry com backoff exponencial
  - Logging estruturado
  - Método para salvar no banco

### 2.2 Portal: transparencia.e-publica.net
- [ ] Analisar estrutura do site
- [ ] Identificar endpoints da API (se houver)
- [ ] Identificar necessidade de autenticação
- [ ] Mapear dados disponíveis (licitações, contratos, etc.)
- [ ] Implementar scraper com Selenium (se necessário)
- [ ] Criar tabela(s) específica(s) no SQLite
- [ ] Testar e validar dados coletados

### 2.3 Portal: pmf.sc.gov.br
- [ ] Analisar estrutura do site
- [ ] Identificar se tem API aberta
- [ ] Mapear seções: notícias, secretarias, serviços, etc.
- [ ] Implementar scraper (requests ou Selenium)
- [ ] Criar tabela(s) e salvar dados

### 2.4 Portal: cigaobras.pmf.sc.gov.br
- [ ] Analisar estrutura
- [ ] Identificar dados de obras públicas
- [ ] Implementar scraper
- [ ] Criar tabela(s) e salvar dados

### 2.5 Scrapers Adicionais (conforme necessidade)
- [ ] Implementar cada novo scraper seguindo padrão:
  1. Analisar site
  2. Criar arquivo em `scrapers/`
  3. Usar normalizers para dados
  4. Salvar no banco com metadados

---

## Fase 3: Utilitários e Qualidade

### 3.1 Retry e Error Handling
- [ ] Implementar sistema de retry para URLs que falharam
- [ ] Log de erros estruturado
- [ ] Relatório de execução (quantos dados coletados, quantos erros)

### 3.2 Robustez
- [ ] Rate limiting entre requisições
- [ ] Tratamento de CAPTCHA (se houver)
- [ ] Verificação de `robots.txt`

---

## Fase 4: Execução e Validação

### 4.1 Script Principal
- [ ] Criar `run_all.py` que executa todos os scrapers em sequência
- [ ] Log consolidado de toda a execução
- [ ] Estatísticas finais (tabelas criadas, registros por tabela)

### 4.2 Validação
- [ ] Verificar dados no SQLite após execução
- [ ] Spot-check em algumas tabelas
- [ ] Verificar que normalizers foram aplicados corretamente

---

## Notas de Implementação

1. **Ordem**: Fazer setup primeiro (Fase 1), depois scrapers (Fase 2), depois utilitários (Fase 3)
2. **Testar cada scraper**: Não esperar até o fim para verificar dados — testar conforme implementa
3. **Não duplicar lógica**: Usar `base_scraper.py` e `normalizers.py` em todos os scrapers
4. **Fallback**: Se um scraper falhar, continuar para o próximo — não parar tudo
5. **Metadados**: Toda tabela deve ter colunas `fonte`, `url_origem`, `data_coleta`

---

## Estrutura Final Esperada

```
floripascraper/
├── scrapers/
│   ├── base_scraper.py      # Classe base
│   ├── transparencia_epublica.py
│   ├── pmf_sc.py
│   ├── cigaobras.py
│   └── ... (mais conforme necessário)
├── database/
│   └── db_manager.py
├── utils/
│   └── normalizers.py
├── run_all.py
├── requirements.txt
├── .gitignore
├── CLAUDE.md
├── README.md
└── PLANO.md
```

---

## Checklist de Conclusão

- [ ] requirements.txt criado e funcional
- [ ] normalizers.py com todas as funções
- [ ] db_manager.py funcionando
- [ ] base_scraper.py como base para todos
- [ ] Todos os portais principais raspados
- [ ] Dados no SQLite tratados e normalizados
- [ ] run_all.py executa todos os scrapers
- [ ] Documentação atualizada